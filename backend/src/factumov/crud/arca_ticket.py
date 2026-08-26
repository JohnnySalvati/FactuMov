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


def get_valid(db: Session, env: str, service: str) -> ArcaTicket | None:
    """El ticket vigente, o None si no hay o si está por vencer.

    La comparación de vencimiento se hace en SQL, igual que en `user_session`: una sola fuente
    de verdad para "ahora", y sin el `TypeError` de comparar un datetime naive con uno aware
    que `DateTime(timezone=True)` deja servido.
    """
    return (
        db.execute(
            select(ArcaTicket).where(
                ArcaTicket.env == env,
                ArcaTicket.service == service,
                ArcaTicket.expires_at > func.now() + EXPIRY_MARGIN,
            )
        )
        .scalars()
        .first()
    )


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
    db.flush()
    return ticket
