"""El rechequeo periódico de las delegaciones que están esperando una aceptación nuestra.

Existe por la asimetría que define toda esta parte del proyecto: **el usuario nos avisa que
delegó, pero nadie nos avisa cuando la delegación empieza a funcionar.** Los dos pasos que
faltan —aceptar la designación y pasarle el servicio a nuestro certificado— los hace una
persona con Clave Fiscal en dos páginas que ningún web service expone, así que no hay evento,
no hay webhook y no hay nada que escuchar. Lo único que se puede hacer es volver a preguntar.

Y volver a preguntar **con un ticket reciente**, que no es lo mismo: un TA lleva la lista de
relaciones congelada en el momento en que se emitió, así que repreguntar con el mismo ticket es
repetir la pregunta anterior. Ver `RECHECK_TICKET_MAX_AGE`.

Sin esto, el usuario que avisó queda apretando el botón a ciegas: hizo su parte, le dijimos que
espere, y no tiene forma de saber cuándo terminó la espera salvo reintentar. Con esto se entera
por mail, que es donde ya recibe todo lo demás.

**Solo mira las que están esperando** —con aviso, sin verificar, y con el aviso reciente— y no
todas las identidades fiscales. Barrer las verificadas sería buscar revocaciones sobre filas que
nadie está mirando y multiplicar por N la cuota de ARCA, que es del certificado y por lo tanto
compartida por todos los usuarios. La revocación la detecta la pantalla al abrir una identidad
con la verificación vencida, que es cuando a alguien le importa — ver `FiscalIdentityPage.tsx`.
"""

import datetime
import hashlib
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factumov import database
from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.exceptions import ArcaError
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.models.user import User
from factumov.services import notifications, wsfe

logger = logging.getLogger(__name__)

# Cada cuánto se barre. Lo que se está esperando es que una persona lea un mail y haga un click
# en ARCA, o sea tiempo humano: medido en minutos u horas, no en segundos. Quince minutos deja
# la espera del usuario en unos siete de promedio y cuesta cuatro llamadas por hora **por
# identidad pendiente**, que en el caso normal son cero.
RECHECK_INTERVAL_SECONDS = 15 * 60

# Cuán viejo puede ser el ticket con el que se repregunta. No es una constante de ARCA sino el
# techo de cuánto puede durar una respuesta desactualizada: el TA lleva la lista de relaciones
# tal como estaba al emitirse, así que sin esto el barrido pasa hasta doce horas repreguntando
# cuatro veces por hora con la garantía de recibir siempre lo mismo. Justo el caso que se está
# esperando —el contribuyente ya delegó, o nosotros ya completamos nuestra parte— es el que un
# ticket viejo no puede ver.
#
# **Cuesta un login a WSAA por barrido, no uno por identidad**: el TA es del certificado y lo
# comparten todas. Sea una pendiente o cincuenta, el techo son veinticuatro pedidos por día.
# Una hora, y no los quince minutos del barrido, porque la espera que importa no es la del
# reintento sino la de la persona: una hora de más en un trámite que ya viene de días es
# invisible, y veinticuatro logins diarios contra noventa y seis no lo son.
RECHECK_TICKET_MAX_AGE = datetime.timedelta(hours=1)

# Después de este tiempo se deja de repreguntar sola. Un aviso de hace un mes que sigue sin
# verificar no se va a arreglar preguntando cuatro veces por hora para siempre: o el usuario se
# confundió de trámite, o hay algo mal del lado nuestro, y las dos cosas necesitan una persona.
# El rechequeo al abrir la pantalla sigue funcionando igual, así que nadie queda sin salida.
CLAIM_MAX_AGE_DAYS = 30


def _lock_key() -> int:
    """El bigint del advisory lock del barrido. Uno solo: el barrido es global, no por fila.

    `blake2b` y no `hash()`, por lo mismo que en `services/arca.py` y en `crud/invoice.py`:
    Python aleatoriza `hash` por proceso, así que dos workers tomarían candados distintos para
    la misma clave y el candado no serializaría nada.
    """
    digest = hashlib.blake2b(b"delegation-recheck", digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def _pending(db: Session) -> list[tuple[FiscalIdentity, str]]:
    """Las identidades que avisaron, siguen sin verificar y avisaron hace poco, con su dueño.

    El join a `users` es explícito porque no hay relación declarada en ninguna de las dos
    direcciones — ver CLAUDE.md → *Ownership scoping*. Se filtran los usuarios dados de baja:
    mandarle un mail a alguien cuya cuenta ya no existe es gastar ARCA para molestar a nadie.
    """
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=CLAIM_MAX_AGE_DAYS)
    rows = db.execute(
        select(FiscalIdentity, User.email)
        .join(User, User.id == FiscalIdentity.user_id)
        .where(
            FiscalIdentity.delegation_claimed_at.is_not(None),
            FiscalIdentity.delegation_verified_at.is_(None),
            FiscalIdentity.delegation_claimed_at > cutoff,
            User.is_active.is_(True),
        )
    ).all()
    return [(identity, email) for identity, email in rows]


def recheck_pending() -> int:
    """Repregunta por cada delegación pendiente y avisa al usuario de las que ya andan.

    Devuelve cuántas pasaron a verificada, que es lo único que un llamador podría querer saber.

    **Sesión propia y commit propio**, desacoplada de cualquier request — igual que
    `arca.get_access_ticket`, y por el mismo motivo: esto no corre adentro de un request. Se
    pide como `database.SessionLocal()` —el módulo, no el nombre importado— para que un test la
    pueda parchear, mismo criterio que `MAX_UPLOAD_BYTES`.

    **Un `pg_try_advisory_xact_lock` y no el `pg_advisory_xact_lock` bloqueante** de las otras
    dos veces que el proyecto usa este mecanismo. Acá no hay nada que esperar: si otro worker ya
    está barriendo, este tick no tiene ningún trabajo que hacer, y quedarse bloqueado solo
    acumularía barridos para dispararlos todos juntos cuando el candado se libere.

    **Un solo commit, al final.** No es una optimización: el candado es de transacción, así que
    commitear adentro del loop lo soltaría en la primera identidad verificada y dejaría al resto
    del barrido sin protección.

    **Los mails salen después del commit y fuera del candado.** Lo primero porque el mail dice
    que ya puede emitir y eso tiene que ser verdad cuando llega — el mismo orden que el registro
    exige para el token de confirmación. Lo segundo porque una conexión SMTP colgada no puede
    quedarse con el candado que le impide barrer al resto.

    **El fallo de una identidad no se lleva puestas a las demás.** ARCA homologación corta
    conexiones cada tanto, y un `ArcaError` en la tercera de cinco no puede dejar sin
    reverificar a las dos que siguen: la próxima vuelta es en quince minutos.
    """
    ready: list[tuple[str, str, str]] = []

    with database.SessionLocal() as db:
        if not db.execute(select(func.pg_try_advisory_xact_lock(_lock_key()))).scalar():
            logger.debug("Otro worker está barriendo las delegaciones pendientes; salteo.")
            return 0

        for identity, user_email in _pending(db):
            try:
                check = wsfe.check_delegation(
                    identity.tax_id, ticket_max_age=RECHECK_TICKET_MAX_AGE
                )
            except ArcaError:
                # `exception` y no un log a secas: sin el traceback, un barrido que no verifica
                # nada es indistinguible de uno donde no había nada que verificar.
                logger.exception(
                    "No se pudo reverificar la delegación del CUIT %s", identity.tax_id
                )
                continue

            if not check.granted:
                continue

            fiscal_identity_crud.mark_delegation_verified(db, identity)
            ready.append((user_email, identity.name, identity.tax_id))

        db.commit()

    for user_email, identity_name, tax_id in ready:
        logger.info(
            "La delegación del CUIT %s quedó verificada; le aviso a %s.", tax_id, user_email
        )
        notifications.send_delegation_ready_email(
            to=user_email, identity_name=identity_name, tax_id=tax_id
        )
    return len(ready)
