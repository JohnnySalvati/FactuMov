import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.user import User


class EmailConfirmation(Base, TimestampMixin):
    """Token de confirmación de la dirección de email, de un solo uso.

    Es casi el gemelo de `UserSession`, y a propósito: token opaco de `secrets`, guardado
    como SHA-256 en `String(64)` con `unique=True` —que es además el índice por el que se
    busca—, vencimiento absoluto en la columna, y una marca de consumo en vez del borrado
    de la fila. Las razones son las mismas y están en CLAUDE.md → *Autenticación →
    Sesiones*; lo que cambia es la vida útil y que este token se usa una sola vez.

    Es tabla y no dos columnas en `users` porque el reenvío emite un token nuevo sin
    invalidar el anterior: con columnas, cada reenvío pisaría el token del mail que el
    usuario quizás ya tiene abierto, y el link viejo dejaría de funcionar sin que nada lo
    explique. Con filas, los dos links andan hasta que vencen.
    """

    __tablename__ = "email_confirmations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Relación en un solo sentido: el endpoint de confirmación va del token al usuario y
    # nada necesita el camino inverso. No declarar `User.email_confirmations` sigue el mismo
    # criterio que `User.customers` (ver CLAUDE.md → *Ownership scoping*); el borrado en
    # cascada de las filas lo hace el `ON DELETE CASCADE` de la FK, sin pasar por el ORM.
    user: Mapped["User"] = relationship()
