from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
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
