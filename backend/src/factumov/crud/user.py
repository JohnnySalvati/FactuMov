from sqlalchemy import select
from sqlalchemy.orm import Session

from factumov.models.user import User


def get_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email)).scalars().first()
