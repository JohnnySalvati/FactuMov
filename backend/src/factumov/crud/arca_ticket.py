"""Acceso a `arca_tickets`: el TA compartido que WSAA emite para el certificado de FactuMov.

Es el único CRUD del proyecto que **no** está scopeado por usuario, y a propósito: el ticket
es del certificado, no del contribuyente. Ver el docstring de `models/arca_ticket.py`.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factumov.models.arca_ticket import ArcaTicket

# Un TA que vence en treinta segundos es inservible: la llamada a WSFE que lo use va a tardar
# más que eso. Se lo trata como vencido con cinco minutos de anticipación, igual que
# Balance360, así la renovación ocurre antes de que algo falle y no después.
EXPIRY_MARGIN = timedelta(minutes=5)


def get_valid(
    db: Session, env: str, service: str, max_age: timedelta | None = None
) -> ArcaTicket | None:
    """El ticket vigente, o None si no hay, si está por vencer o si es más viejo que `max_age`.

    La comparación de vencimiento se hace en SQL, igual que en `user_session`: una sola fuente
    de verdad para "ahora", y sin el `TypeError` de comparar un datetime naive con uno aware
    que `DateTime(timezone=True)` deja servido.

    **`max_age` es una edad y no una fecha de corte**, por lo mismo: calcular "hace una hora"
    en Python metería el reloj de la app en una comparación que hasta ahora resolvía sola la
    base. Con `func.now() - max_age` los dos lados de las dos condiciones se leen del mismo
    reloj.

    Un ticket puede estar vigente y ser viejo al mismo tiempo, y esa es toda la razón por la
    que este parámetro existe: la vigencia dice si ARCA lo va a aceptar, la edad dice si lo
    que lleva adentro sigue siendo cierto. Ver `services/arca.get_access_ticket`.
    """
    conditions = [
        ArcaTicket.env == env,
        ArcaTicket.service == service,
        ArcaTicket.expires_at > func.now() + EXPIRY_MARGIN,
    ]
    if max_age is not None:
        conditions.append(ArcaTicket.issued_at > func.now() - max_age)
    return db.execute(select(ArcaTicket).where(*conditions)).scalars().first()


def lock(db: Session, key: int) -> None:
    """Toma el advisory lock de la clave, hasta el fin de la transacción.

    `pg_advisory_xact_lock` y no `SELECT ... FOR UPDATE`: la primera vez no hay fila que
    trabar, así que el FOR UPDATE no bloquearía a nadie. El advisory lock traba el número,
    exista o no la fila, y se suelta solo en el commit — no hay forma de olvidarse de liberarlo.
    """
    db.execute(select(func.pg_advisory_xact_lock(key)))


def upsert(
    db: Session,
    env: str,
    service: str,
    token: str,
    sign: str,
    expires_at: datetime,
) -> ArcaTicket:
    """Guarda el ticket recién emitido, pisando el anterior de ese (env, service).

    Es un UPDATE-o-INSERT a mano y no un `ON CONFLICT`: quien llama ya viene con el advisory
    lock tomado, así que la carrera que el upsert nativo resuelve acá no puede ocurrir. Y una
    fila por entorno y servicio es lo que se quiere guardar: el TA viejo no le sirve a nadie.
    """
    ticket = (
        db.execute(select(ArcaTicket).where(ArcaTicket.env == env, ArcaTicket.service == service))
        .scalars()
        .first()
    )
    if ticket is None:
        ticket = ArcaTicket(env=env, service=service)
        db.add(ticket)
    ticket.token = token
    ticket.sign = sign
    ticket.expires_at = expires_at
    # `func.now()` y no `datetime.now()`: es el mismo reloj contra el que `get_valid` compara
    # la edad después. Con el de la app, un contenedor corrido unos segundos alcanzaría para
    # que un ticket recién emitido se lea como viejo, o al revés.
    ticket.issued_at = func.now()
    db.flush()
    return ticket
