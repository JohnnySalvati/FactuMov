import logging
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.dependencies import (
    CurrentUserDep,
    SessionDep,
    enforce_rate_limit,
    get_current_user,
)
from factumov.enums import CondicionIva
from factumov.exceptions import (
    ArcaError,
    DuplicateError,
    DuplicateFiscalIdentityNameError,
    DuplicateFiscalIdentityTaxIdError,
    FiscalIdentityInUseError,
    InUseError,
    PadronError,
)
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.schemas.fiscal_identity import (
    DelegationStatus,
    FiscalIdentityCreate,
    FiscalIdentityLookup,
    FiscalIdentityRead,
    FiscalIdentityUpdate,
    PointOfSaleRead,
    PointsOfSale,
)
from factumov.services import arca, notifications, padron, wsfe
from factumov.services.rate_limit import RateLimiter
from factumov.services.wsfe import DelegationCheck

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/fiscal-identities",
    tags=["fiscal_identities"],
    dependencies=[Depends(get_current_user)],
)


def get_fiscal_identity_or_404(
    fiscal_identity_id: uuid.UUID, db: SessionDep, user: CurrentUserDep
) -> FiscalIdentity:
    """404 sobre la identidad fiscal de otro usuario — ver `routers/customer.py`."""
    fiscal_identity = fiscal_identity_crud.get_by_id(db, fiscal_identity_id, user.id)
    if fiscal_identity is None:
        raise HTTPException(status_code=404, detail="Identidad fiscal no encontrada")
    return fiscal_identity


FiscalIdentityDep = Annotated[FiscalIdentity, Depends(get_fiscal_identity_or_404)]

# Verificar la delegación sale a WSAA y a WSFE, y esa cuota la fija ARCA contra el
# certificado de FactuMov, que es uno solo para todos los usuarios.
#
# Eran diez por hora cuando la única forma de gastarlos era apretar el botón. Ahora la
# pantalla verifica sola al abrir una identidad que todavía no está verificada, así que el
# presupuesto lo comparten un gesto deliberado y una consulta automática: alguien que está
# configurando tres CUIT y navega entre ellos llegaba a diez sin hacer nada raro. Treinta
# sigue siendo un techo bajo —la delegación no cambia varias veces por hora— y deja lugar para
# que el chequeo automático no le coma el turno al botón.
_VERIFY_DELEGATION_LIMITER = RateLimiter(limit=30, window_seconds=60 * 60)

# La lista de puntos de venta sale a la misma llamada de WSFE, pero con su propio presupuesto.
# Compartir el de arriba haría que armar modelos —donde el editor consulta cada vez que se
# cambia de identidad fiscal— le comiera los turnos a la verificación de delegación, que es la
# que desbloquea al usuario nuevo. Sesenta por hora alcanza de sobra: el editor cachea la
# respuesta por identidad, así que una sesión normal gasta uno por CUIT.
_POINTS_OF_SALE_LIMITER = RateLimiter(limit=60, window_seconds=60 * 60)


@router.get("", response_model=list[FiscalIdentityRead])
def list_fiscal_identities(db: SessionDep, user: CurrentUserDep) -> list[FiscalIdentity]:
    return fiscal_identity_crud.get_all(db, user.id)


@router.get("/lookup/{tax_id}", response_model=FiscalIdentityLookup)
def lookup_fiscal_identity(tax_id: str, user: CurrentUserDep) -> FiscalIdentityLookup:
    """Los datos de un CUIT según el padrón de ARCA, para sembrar el alta de una identidad.

    **Es el primer paso del alta y no un extra.** Al usuario se le pide el CUIT, que es lo
    único que sabe de memoria, y el resto —razón social, domicilio, condición frente al IVA—
    lo trae ARCA. La condición es la que más se gana: es un dato fiscal que el usuario suele
    saber decir mal, y de ella depende la letra de todo lo que emita.

    **No escribe nada**, igual que `GET /customers/lookup/{tax_id}` y que la importación de
    PDF: devuelve una propuesta que el usuario revisa y confirma con `POST /fiscal-identities`.
    Consultar dos veces el mismo CUIT no puede dejar dos identidades.

    **404** cuando ARCA no tiene datos de ese CUIT o cuando lo que llegó no es un CUIT; **502**
    cuando no se pudo preguntar. La pantalla no queda sin salida con ninguno de los dos: ofrece
    cargar los datos a mano, que es la misma regla que hace que la importación de un PDF
    ilegible tenga un "empezar en blanco".

    No hace falta que el usuario haya delegado nada: el padrón se consulta con FactuMov como
    `cuitRepresentada`. La delegación hace falta para *emitir*, no para consultar.
    """
    enforce_rate_limit(padron.LIMITER, str(user.id))

    try:
        taxpayer = padron.get_taxpayer(tax_id)
    except PadronError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ArcaError:
        # Ver `_ask_arca`: sin este log, un 502 no deja ningún rastro de su causa.
        logger.exception("Falló la consulta al padrón del CUIT %s", tax_id)
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar el padrón de ARCA. Probá de nuevo, o cargá los "
            "datos a mano.",
        )

    return FiscalIdentityLookup(
        tax_id=taxpayer.tax_id,
        name=taxpayer.name,
        # Consumidor final no es una condición que un emisor pueda tener — ver el schema.
        condicion_iva=(
            None if taxpayer.condicion_iva is CondicionIva.FINAL else taxpayer.condicion_iva
        ),
        address=taxpayer.address,
        active=taxpayer.active,
    )


@router.get("/{fiscal_identity_id}", response_model=FiscalIdentityRead)
def get_fiscal_identity(fiscal_identity: FiscalIdentityDep) -> FiscalIdentity:
    return fiscal_identity


@router.post("", response_model=FiscalIdentityRead, status_code=201)
def create_fiscal_identity(
    data: FiscalIdentityCreate, db: SessionDep, user: CurrentUserDep
) -> FiscalIdentity:
    try:
        fiscal_identity = fiscal_identity_crud.create(db, data, user.id)
    except DuplicateFiscalIdentityNameError:
        raise HTTPException(status_code=409, detail="Nombre duplicado")
    except DuplicateFiscalIdentityTaxIdError:
        raise HTTPException(status_code=409, detail="CUIT duplicado")
    except DuplicateError:
        raise HTTPException(status_code=409, detail="Duplicado")
    return fiscal_identity


@router.patch("/{fiscal_identity_id}", response_model=FiscalIdentityRead)
def update_fiscal_identity(
    data: FiscalIdentityUpdate, fiscal_identity: FiscalIdentityDep, db: SessionDep
) -> FiscalIdentity:
    try:
        fiscal_identity = fiscal_identity_crud.update(db, fiscal_identity, data)
    except DuplicateFiscalIdentityNameError:
        raise HTTPException(status_code=409, detail="Nombre duplicado")
    except DuplicateFiscalIdentityTaxIdError:
        raise HTTPException(status_code=409, detail="CUIT duplicado")
    except DuplicateError:
        raise HTTPException(status_code=409, detail="Duplicado")
    return fiscal_identity


@router.delete("/{fiscal_identity_id}", status_code=204)
def delete_fiscal_identity(
    fiscal_identity: FiscalIdentityDep,
    db: SessionDep,
) -> None:
    try:
        fiscal_identity_crud.delete(db, fiscal_identity)
    except FiscalIdentityInUseError:
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar una identidad fiscal con modelos asociados",
        )
    except InUseError:
        raise HTTPException(status_code=409, detail="No se puede eliminar, existen asociaciones")


# Cuán viejo puede ser el ticket con el que se le pregunta a ARCA por este click. Mucho más
# exigente que el del barrido, y por una razón de uso: acá hay alguien que acaba de terminar el
# trámite y aprieta el botón para saber si quedó. Contestarle que no con la foto de las
# relaciones de hace una hora sería mentirle en el único momento en que está mirando.
#
# Cinco minutos y no cero: apretar el botón dos veces seguidas, o dos identidades verificadas
# una atrás de la otra, no tienen por qué costar dos logins a WSAA. El techo de gasto real lo
# pone el rate limiter de acá arriba, que ya cuenta por usuario justamente porque la cuota de
# ARCA es del certificado y es de todos.
VERIFY_TICKET_MAX_AGE = timedelta(minutes=5)


def _ask_arca(
    fiscal_identity: FiscalIdentity,
    db: SessionDep,
    user_id: str,
    limiter: RateLimiter = _VERIFY_DELEGATION_LIMITER,
) -> DelegationCheck:
    """Le pregunta a ARCA si FactuMov puede emitir por este CUIT, y traduce el fallo a un 502.

    El commit cierra la transacción del request *antes* de la llamada SOAP, que puede tardar
    decenas de segundos. Sin esto, la conexión a Postgres se queda tomada y con una transacción
    abierta todo ese rato — el mismo problema, y la misma solución, que el commit explícito del
    registro antes de mandar el mail. `rollback()` no sirve: bajo el
    `join_transaction_mode="create_savepoint"` del fixture de tests revertiría al savepoint y se
    llevaría puestas las filas que el test armó.
    """
    enforce_rate_limit(limiter, user_id)

    tax_id = fiscal_identity.tax_id
    db.commit()

    try:
        return wsfe.check_delegation(tax_id, ticket_max_age=VERIFY_TICKET_MAX_AGE)
    except ArcaError:
        # El `logger.exception` no es decorativo: es la **única** forma de saber por qué falló.
        # El detalle no puede ir en la respuesta —no le dice nada al usuario y filtra cómo
        # estamos armados—, así que sin esta línea un 502 es indistinguible de otro y el
        # síntoma que ve el usuario ("no me verifica") no tiene ningún rastro atrás.
        logger.exception("Falló la verificación de delegación del CUIT %s", tax_id)
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar ARCA. No es que falte la delegación: ARCA no "
            "contestó. Probá de nuevo en un momento.",
        )


def _apply(
    db: SessionDep, fiscal_identity: FiscalIdentity, check: DelegationCheck, *, claim: bool
) -> DelegationStatus:
    """Escribe lo que la respuesta de ARCA implica y arma el cuerpo de la respuesta.

    Tres transiciones, y las tres son sobre el par de columnas que la pantalla lee:

    - **Que sí**: se sella `delegation_verified_at` y se borra el aviso del usuario, que ya
      cumplió su función.
    - **Que no, sobre una identidad que estaba verificada**: se limpia la verificación. Es lo
      que le da consecuencias a que `delegation_verified_at` haya significado siempre "esto era
      verdad en esta fecha": la delegación se revoca del lado de ARCA sin avisarnos, y sin esto
      la app se enteraría recién con un rechazo al emitir.
    - **Que no, con `claim`**: se registra que el usuario dice haber delegado, que es lo único
      que distingue "no delegó" de "delegó y falta que aceptemos la designación".

    `claim` es un flag y no dos funciones porque es exactamente la única diferencia entre los
    dos endpoints: los dos preguntan lo mismo y difieren en qué escriben cuando la respuesta es
    que no.
    """
    if check.granted:
        fiscal_identity_crud.mark_delegation_verified(db, fiscal_identity)
    else:
        if fiscal_identity.delegation_verified_at is not None:
            fiscal_identity_crud.clear_delegation_verified(db, fiscal_identity)
        if claim:
            fiscal_identity_crud.mark_delegation_claimed(db, fiscal_identity)

    # Refresca los `func.now()` que quedaron como expresiones SQL sin evaluar, para poder
    # devolver timestamps reales y no objetos de SQLAlchemy.
    db.commit()
    db.refresh(fiscal_identity)
    return DelegationStatus(
        granted=check.granted,
        message=None if check.granted else check.message,
        delegation_verified_at=fiscal_identity.delegation_verified_at,
        delegation_claimed_at=fiscal_identity.delegation_claimed_at,
        # Va solo en la respuesta negativa, que es la única donde hay una instrucción que dar.
        delegate_tax_id=None if check.granted else arca.get_delegate_tax_id(),
    )


@router.post("/{fiscal_identity_id}/verify-delegation", response_model=DelegationStatus)
def verify_delegation(
    fiscal_identity: FiscalIdentityDep, db: SessionDep, user: CurrentUserDep
) -> DelegationStatus:
    """Le pregunta a ARCA si FactuMov ya puede emitir por este CUIT. **No afirma nada.**

    Es el que dispara la pantalla sola al abrir una identidad sin verificar, y también el que
    dispara el link del mail que le avisa al operador que aceptó una designación. Los dos son
    "andá a fijarte", no "ya está": la única fuente de verdad es ARCA, y cualquier otra cosa
    sería alguien afirmando algo que después se descubre al emitir.

    **200 con `granted=False`** cuando la delegación no está: el request estaba bien hecho y la
    respuesta es simplemente que no. Un 4xx haría que la UI tuviera que distinguir "te
    equivocaste" de "todavía no autorizaste", que son cosas distintas.

    **502** cuando no se pudo preguntar —ARCA caído, certificado mal configurado, respuesta
    ilegible—. El detalle no se propaga: "WSAA rechazó el TRA" no le dice nada al usuario y sí
    filtra cómo está armado nuestro lado. El traceback queda en el log.

    Es POST y no GET aunque parezca una consulta: sale a la red, tarda segundos y **escribe**
    `delegation_verified_at`. Un GET con esos tres atributos es algo que un proxy o un prefetch
    del navegador pueden repetir solos.
    """
    check = _ask_arca(fiscal_identity, db, str(user.id))
    return _apply(db, fiscal_identity, check, claim=False)


@router.post("/{fiscal_identity_id}/claim-delegation", response_model=DelegationStatus)
def claim_delegation(
    fiscal_identity: FiscalIdentityDep,
    background: BackgroundTasks,
    db: SessionDep,
    user: CurrentUserDep,
) -> DelegationStatus:
    """El usuario dice que ya delegó. Se verifica igual, y recién si ARCA dice que no se anota.

    **Verifica antes de anotar, y ese orden es la decisión.** Entre que la pantalla cargó y que
    el usuario apretó el botón pudo haber ido a ARCA en otra pestaña y otorgado la delegación:
    en ese caso lo que corresponde es verificarla y terminar, no registrar un aviso que
    dispararía trabajo manual del lado del operador para algo que ya funciona.

    Cuando ARCA sigue diciendo que no, el aviso queda guardado y es lo único que separa los dos
    estados que WSFE colapsa en el código 600: "todavía no delegó" y "delegó, y falta que
    FactuMov acepte la designación en `adminrel/pending.aspx`". Esa aceptación es un click con
    Clave Fiscal y no existe ningún web service que la haga ni que la anuncie, así que la
    información tiene que venir del usuario.

    **El aviso al operador sale de acá, y es la mitad que importa.** Aceptar la designación es
    un click con Clave Fiscal que ARCA no expone por ningún web service, así que la app no
    puede enterarse sola de que alguien la está esperando. Este es el único momento en que
    existe evidencia de que hay una persona del otro lado, y desperdiciarlo dejaría al usuario
    esperando a que el operador mire la lista de pendientes de ARCA por casualidad.

    Sale **una sola vez por identidad**, con el primer aviso: `mark_delegation_claimed` no pisa
    la fecha, así que un usuario impaciente apretando el botón no se convierte en veinte mails.
    Y va en `BackgroundTasks` porque acompaña a algo que ya quedó guardado — el aviso está
    commiteado antes de que el mail se intente, así que un SMTP caído no puede hacer que el
    usuario reintente un click que ya surtió efecto.

    Mismos status que `verify-delegation`, y por los mismos motivos.
    """
    check = _ask_arca(fiscal_identity, db, str(user.id))
    # Antes de escribir: lo que decide si hay que avisar es que este aviso sea nuevo, y después
    # del `_apply` ya no se puede distinguir del que estaba.
    already_claimed = fiscal_identity.delegation_claimed_at is not None
    status = _apply(db, fiscal_identity, check, claim=True)

    if not already_claimed and status.delegation_claimed_at is not None:
        background.add_task(
            notifications.send_delegation_pending_email,
            fiscal_identity.tax_id,
            fiscal_identity.name,
            user.email,
        )
    return status


@router.get("/{fiscal_identity_id}/points-of-sale", response_model=PointsOfSale)
def list_points_of_sale(
    fiscal_identity: FiscalIdentityDep, db: SessionDep, user: CurrentUserDep
) -> PointsOfSale:
    """Los puntos de venta que ARCA tiene dados de alta para este CUIT.

    Existe por una sola razón: **el usuario no puede saber qué número poner**. El punto de
    venta lo da de alta él en ARCA, no en FactuMov, y hasta ahora el editor de modelos se lo
    pedía escrito con un `1` de default — o sea, el default estaba mal para todo el mundo menos
    para quien tuviera justo el punto de venta 1. Con esto el campo se elige de una lista que
    dice la verdad.

    **Es la misma llamada que la verificación de delegación** (`FEParamGetPtosVenta`, ver
    `services/wsfe.py`), leída entera en vez de solo mirarle los errores.

    **GET y no POST**, al revés que `verify-delegation`: acá no se escribe nada. La tentación
    de sellar `delegation_verified_at` de paso —la información está, sale gratis— se descarta
    por lo mismo que se documenta allá: un GET que escribe es algo que un proxy o el prefetch
    del navegador pueden repetir solos.

    **200 con `granted=False`** cuando falta la delegación, y **200 con `points` vacío** cuando
    la delegación está pero el CUIT no tiene ningún punto de venta. Las dos son respuestas, no
    errores, y la pantalla las explica distinto. **502** cuando no se pudo preguntar.
    """
    check = _ask_arca(fiscal_identity, db, str(user.id), limiter=_POINTS_OF_SALE_LIMITER)
    return PointsOfSale(
        granted=check.granted,
        points=[
            PointOfSaleRead(number=point.number, emission_type=point.emission_type)
            for point in check.points_of_sale
        ],
    )
