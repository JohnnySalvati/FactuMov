import logging
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.dependencies import (
    CurrentUserDep,
    SessionDep,
    client_key,
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
from factumov.models.user import User
from factumov.schemas.fiscal_identity import (
    DelegationAcceptance,
    DelegationAcceptanceRequest,
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
from factumov.services.security import generate_opaque_token, hash_opaque_token
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
    rate_limit_key: str,
    limiter: RateLimiter = _VERIFY_DELEGATION_LIMITER,
) -> DelegationCheck:
    """Le pregunta a ARCA si FactuMov puede emitir por este CUIT, y traduce el fallo a un 502.

    El commit cierra la transacción del request *antes* de la llamada SOAP, que puede tardar
    decenas de segundos. Sin esto, la conexión a Postgres se queda tomada y con una transacción
    abierta todo ese rato — el mismo problema, y la misma solución, que el commit explícito del
    registro antes de mandar el mail. `rollback()` no sirve: bajo el
    `join_transaction_mode="create_savepoint"` del fixture de tests revertiría al savepoint y se
    llevaría puestas las filas que el test armó.

    La clave del limitador se llama `rate_limit_key` y no `user_id` porque no siempre lo es: los
    tres endpoints del usuario cuentan por usuario, y el del operador —que llega desde un link
    de mail, sin sesión— cuenta por IP. Lo único que esta función necesita saber de esa clave es
    contra qué presupuesto descontar.
    """
    enforce_rate_limit(limiter, rate_limit_key)

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
    db: SessionDep,
    fiscal_identity: FiscalIdentity,
    check: DelegationCheck,
    *,
    claim_token_hash: str | None,
) -> DelegationStatus:
    """Escribe lo que la respuesta de ARCA implica y arma el cuerpo de la respuesta.

    Tres transiciones, y las tres son sobre el par de columnas que la pantalla lee:

    - **Que sí**: se sella `delegation_verified_at` y se borra el aviso del usuario, que ya
      cumplió su función.
    - **Que no, sobre una identidad que estaba verificada**: se limpia la verificación. Es lo
      que le da consecuencias a que `delegation_verified_at` haya significado siempre "esto era
      verdad en esta fecha": la delegación se revoca del lado de ARCA sin avisarnos, y sin esto
      la app se enteraría recién con un rechazo al emitir.
    - **Que no, con `claim_token_hash`**: se registra que el usuario dice haber delegado, que es
      lo único que distingue "no delegó" de "delegó y falta que aceptemos la designación", y con
      el aviso se guarda el token del link que el mail al operador lleva adentro.

    Un parámetro y no dos funciones porque es exactamente la única diferencia entre los
    endpoints: todos preguntan lo mismo y difieren en qué escriben cuando la respuesta es que
    no. Y un `str | None` en vez de un `bool` más un hash aparte, porque los dos serían el mismo
    dato dicho dos veces y podrían contradecirse: no hay aviso sin link.
    """
    if check.granted:
        fiscal_identity_crud.mark_delegation_verified(db, fiscal_identity)
    else:
        if fiscal_identity.delegation_verified_at is not None:
            fiscal_identity_crud.clear_delegation_verified(db, fiscal_identity)
        if claim_token_hash is not None:
            fiscal_identity_crud.mark_delegation_claimed(db, fiscal_identity, claim_token_hash)

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
    return _apply(db, fiscal_identity, check, claim_token_hash=None)


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
    Ese mail lleva adentro el link con el que el operador avisa que ya hizo los dos pasos en
    ARCA, y el token de ese link se emite acá — ver `confirm_delegation_accepted`.
    Y va en `BackgroundTasks` porque acompaña a algo que ya quedó guardado — el aviso está
    commiteado antes de que el mail se intente, así que un SMTP caído no puede hacer que el
    usuario reintente un click que ya surtió efecto.

    Mismos status que `verify-delegation`, y por los mismos motivos.
    """
    check = _ask_arca(fiscal_identity, db, str(user.id))
    # Antes de escribir: lo que decide si hay que avisar es que este aviso sea nuevo, y después
    # del `_apply` ya no se puede distinguir del que estaba.
    already_claimed = fiscal_identity.delegation_claimed_at is not None
    # El token se emite siempre y se guarda solo si el aviso resulta nuevo — de eso se encarga
    # `mark_delegation_claimed`. Generar uno que no se use cuesta 32 bytes de `secrets` y evita
    # la alternativa fea: emitirlo adentro del `if` de más abajo, o sea *después* de escribir,
    # cuando la fila ya se guardó sin él.
    raw_token = generate_opaque_token()
    status = _apply(db, fiscal_identity, check, claim_token_hash=hash_opaque_token(raw_token))

    if not already_claimed and status.delegation_claimed_at is not None:
        background.add_task(
            notifications.send_delegation_pending_email,
            fiscal_identity.tax_id,
            fiscal_identity.name,
            user.email,
            raw_token,
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


# --- El link del mail al operador --------------------------------------------------------
#
# Todo lo de abajo vive afuera de `router`, que exige sesión en todas sus rutas. Acá no puede
# haberla: quien llega es el operador, desde un link de mail, y encima sobre una identidad
# fiscal que **no es suya** — `get_fiscal_identity_or_404` le contestaría 404 aunque tuviera
# cuenta. Lo que autoriza el pedido es el token, igual que en la confirmación de mail.

delegation_router = APIRouter(prefix="/delegations", tags=["fiscal_identities"])

# Token desconocido y token ya gastado comparten respuesta, porque el remedio es el mismo:
# esperar el aviso que llega solo, o mirar la identidad en la app. El texto nombra el caso
# habitual —la delegación ya quedó verificada, y con eso el link se apagó— para que el operador
# no salga a buscar un problema que no existe.
_SPENT_ACCEPTANCE_DETAIL = (
    "Este link ya no vale. Lo más probable es que esa delegación ya haya quedado verificada; "
    "si no, el aviso del usuario se dio de baja y hay que pedirle que vuelva a avisar."
)

# Sin sesión de la cual colgar el presupuesto, se cuenta por IP. Diez por hora alcanza de sobra
# para el uso real —el operador entra, ve que sí, y no vuelve— y le pone un techo a lo único que
# este endpoint puede gastar de más: la cuota de ARCA, que es del certificado y por lo tanto de
# todos los usuarios. Es el mismo motivo por el que el botón del usuario tiene el suyo.
_ACCEPTANCE_LIMITER = RateLimiter(limit=10, window_seconds=60 * 60)


@delegation_router.post("/accepted", response_model=DelegationAcceptance)
def confirm_delegation_accepted(
    data: DelegationAcceptanceRequest,
    request: Request,
    background: BackgroundTasks,
    db: SessionDep,
) -> DelegationAcceptance:
    """El operador dice que ya aceptó la designación en ARCA. **Se le pregunta a ARCA igual.**

    Es el otro extremo de `claim_delegation`. Allá el usuario avisa que hizo su parte y sale un
    mail al operador; acá el operador avisa que hizo la suya y se cierra la espera. Sin esto la
    única forma de cerrarla es el barrido de `services/delegation_watch.py`, que corre cada
    quince minutos: el operador termina el trámite en ARCA y no tiene forma de saber si quedó
    bien —ni el usuario de enterarse— hasta que al barrido le toque. Con el link, el que acaba
    de hacer el trámite obtiene la respuesta en el momento, que es cuando todavía tiene las
    pestañas de ARCA abiertas para corregir lo que falte.

    **No se le cree.** Lo que escribe la verificación es la respuesta de ARCA y nada más, igual
    que en los otros dos endpoints: el link es un "andá a fijarte ahora", no un "dalo por
    hecho". Es exactamente la lección de los dos pasos —una designación aceptada sigue
    contestando 600 si falta la relación con el computador— y el que más se equivoca ahí es
    justamente el operador, que ya vio la pantalla de ARCA decir "Aceptada: SI".

    Por eso el `granted=False` no es un fracaso del link sino su otra mitad útil: le dice al
    operador, con el texto de ARCA, que todavía falta algo. Y como el token sobrevive a la
    respuesta negativa, puede completar el paso que falte y volver a apretar sin pedir un mail
    nuevo.

    **El mail al usuario sale de acá cuando ARCA dice que sí**, y es el motivo entero de que
    esto exista: el que estaba esperando se entera al toque en vez de en el próximo barrido. Es
    el mismo mail, `send_delegation_ready_email`, para que las dos formas de cerrar la espera se
    vean idénticas del lado del usuario.

    **400** para un token desconocido o ya gastado —el link se apaga al verificar—, **429** por
    IP, y **502** cuando no se pudo preguntar, los tres con los mismos motivos que en el resto
    del módulo.
    """
    fiscal_identity = fiscal_identity_crud.get_by_claim_token_hash(
        db, hash_opaque_token(data.token)
    )
    if fiscal_identity is None:
        raise HTTPException(status_code=400, detail=_SPENT_ACCEPTANCE_DETAIL)

    # Los cuatro se leen antes de `_ask_arca`, que commitea y con eso expira los atributos de
    # las filas: después de la llamada a ARCA cada uno costaría un SELECT de más. El dueño se
    # busca a mano porque no hay relación declarada entre las dos tablas — ver CLAUDE.md →
    # *Ownership scoping*, y `delegation_watch._pending`, que hace el join por lo mismo.
    tax_id = fiscal_identity.tax_id
    identity_name = fiscal_identity.name
    owner = db.get(User, fiscal_identity.user_id)
    # `is_active` por lo mismo que lo filtra el barrido: mandarle un mail a alguien cuya cuenta
    # ya no existe es gastar en molestar a nadie. Lo que no cambia es la verificación, que se
    # guarda igual — es un hecho sobre ARCA y no sobre la cuenta.
    notify: str | None = owner.email if owner is not None and owner.is_active else None

    check = _ask_arca(fiscal_identity, db, client_key(request), limiter=_ACCEPTANCE_LIMITER)
    status = _apply(db, fiscal_identity, check, claim_token_hash=None)

    if status.granted:
        logger.info(
            "El operador cerró la espera del CUIT %s desde el link del mail; ARCA ya nos "
            "habilita.",
            tax_id,
        )
        if notify is not None:
            background.add_task(
                notifications.send_delegation_ready_email, notify, identity_name, tax_id
            )

    return DelegationAcceptance(
        granted=status.granted,
        tax_id=tax_id,
        identity_name=identity_name,
        message=status.message,
    )
