from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """Solo marcas de tiempo: sin `created_by` / `modified_by`.

    Los de Balance360 se difirieron hasta la unidad de ownership scoping, y ahí se decidió
    no traerlos. `user_id` ya responde de quién es la fila, y con un único dueño por fila
    —nadie más la puede leer ni tocar— `created_by` y `modified_by` valdrían siempre lo
    mismo que `user_id`. Balance360 los necesita porque varios usuarios operan sobre los
    mismos libros; acá no hay nada compartido.

    Se revisa si aparece acceso compartido (el contador con acceso a las identidades de su
    cliente). Ese es el cambio que vuelve real la pregunta "quién tocó esto", y es también
    el que va a decidir si la propiedad sigue siendo una columna o pasa a ser una tabla de
    asociación — o sea que agregar la autoría antes sería una migración a cuenta de una
    decisión que todavía no se puede tomar.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
