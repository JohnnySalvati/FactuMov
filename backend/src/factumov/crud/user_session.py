from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from factumov.models.user_session import UserSession


def create(db: Session, user_id: UUID, token_hash: str, expires_at: datetime) -> UserSession:
    user_session = UserSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(user_session)
    db.flush()
    return user_session


def get_active_by_token_hash(db: Session, token_hash: str) -> UserSession | None:
    return (
        db.execute(
            select(UserSession)
            .where(
                UserSession.token_hash == token_hash,
                UserSession.expires_at > func.now(),
                UserSession.revoked_at.is_(None),
            )
            .options(joinedload(UserSession.user))
        )
        .scalars()
        .first()
    )


def revoke(db: Session, user_session: UserSession) -> None:
    user_session.revoked_at = func.now()
    db.flush()


def revoke_all_for_user(db: Session, user_id: UUID) -> None:
    """Cierra todas las sesiones vivas de un usuario.

    La usa el reset de contraseña. Cambiar la contraseña sin esto deja adentro a quien ya
    estaba adentro, que es justo lo contrario de lo que quiere el que resetea porque
    sospecha que alguien le entró: la sesión ajena dura una semana y no se entera de nada.

    `UPDATE` masivo y no un `for` sobre las filas, mismo criterio que
    `password_reset.invalidate_all_for_user`. El filtro por `revoked_at` es para no pisar la
    marca de una que ya se cerró, que es cuándo se cerró.
    """
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    db.flush()
