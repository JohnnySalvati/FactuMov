import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.user import User


class PasswordReset(Base, TimestampMixin):
    """Token para elegir una contraseña nueva, de un solo uso.

    Tercera tabla con la misma forma que `UserSession` y `EmailConfirmation` —token opaco de
    `secrets` guardado como SHA-256 en `String(64)` con `unique=True`, vencimiento absoluto
    en la columna, y una marca de consumo en vez del borrado de la fila—. Que se repita es a
    propósito: son tres cosas con el mismo mecanismo y distinta vida, y una tabla genérica
    de "tokens" con una columna `kind` obligaría a que las tres compartan vencimiento,
    índices y reglas de limpieza, que es justo lo que no comparten.

    Es tabla propia y no dos columnas en `users` por el mismo motivo que
    `email_confirmations`: pedir el reset dos veces tiene que dejar los dos links vivos. El
    usuario que no encuentra el primer mail pide otro, y romperle el primero sería castigarlo
    por buscar mal.

    `used_at` y no `confirmed_at`: acá no se confirma nada, se consume el permiso de cambiar
    la contraseña.
    """

    __tablename__ = "password_resets"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Relación en un solo sentido, igual que en `EmailConfirmation`: el endpoint va del token
    # al usuario y nada necesita el camino inverso. El borrado en cascada lo hace el
    # `ON DELETE CASCADE` de la FK, sin que el ORM tenga que cargar las filas.
    user: Mapped["User"] = relationship()
