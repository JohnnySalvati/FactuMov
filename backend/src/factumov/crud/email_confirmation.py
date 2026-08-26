"""Acceso a datos de `email_confirmations`.

Calcado de `crud/user_session.py`: el vencimiento se compara en SQL (`func.now()`) y no
trayendo la fila a Python, para no mezclar un `datetime` naive con uno aware y para tener
una sola fuente de verdad de "ahora". El detalle está en CLAUDE.md → *Autenticación →
Sesiones*.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from factumov.models.email_confirmation import EmailConfirmation


def create(db: Session, user_id: UUID, token_hash: str, expires_at: datetime) -> EmailConfirmation:
    confirmation = EmailConfirmation(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(confirmation)
    db.flush()
    return confirmation


def get_pending_by_token_hash(db: Session, token_hash: str) -> EmailConfirmation | None:
    """El token vivo y sin usar, con su usuario ya cargado.

    Las tres causas de `None` —hash desconocido, vencido, ya consumido— se colapsan acá a
    propósito: el endpoint contesta lo mismo para las tres y no tiene forma de
    distinguirlas por descuido.
    """
    return (
        db.execute(
            select(EmailConfirmation)
            .where(
                EmailConfirmation.token_hash == token_hash,
                EmailConfirmation.expires_at > func.now(),
                EmailConfirmation.confirmed_at.is_(None),
            )
            .options(joinedload(EmailConfirmation.user))
        )
        .scalars()
        .first()
    )


def consume(db: Session, confirmation: EmailConfirmation) -> None:
    """Marca el token como usado, sin borrar la fila.

    Mismo criterio que `revoked_at` en las sesiones: deja rastro y hace que reusar el link
    sea inofensivo en vez de un 500 por fila faltante.
    """
    confirmation.confirmed_at = func.now()
    db.flush()
