import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.user_session import UserSession


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)

    sessions: Mapped[list['UserSession']] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True)
