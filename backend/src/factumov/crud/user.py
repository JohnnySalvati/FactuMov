from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factumov.crud.base import db_flush
from factumov.exceptions import DuplicateUserEmailError
from factumov.models.user import User

# Anotado y no inferido: con una sola entrada mypy deduce
# `dict[str, type[DuplicateUserEmailError]]`, y `dict` es invariante, así que no
# encaja en el `dict[str, type[Exception]]` que pide `db_flush`. Los otros CRUD no lo
# necesitan solo porque tienen dos excepciones distintas y el tipo se ensancha solo.
exception_map: dict[str, type[Exception]] = {"users_email_key": DuplicateUserEmailError}


def get_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email)).scalars().first()


def create(db: Session, email: str, hashed_password: str) -> User:
    """Alta sin confirmar: `email_confirmed_at` queda en `None` por default del modelo.

    Un usuario recién creado no puede loguearse —el login exige `email_confirmed_at is not
    None`—, así que la fila existe pero no sirve para nada hasta que se confirma. Eso es
    justamente lo que hace que el registro no sea un vector: crear la fila no le da acceso
    a nadie.
    """
    user = User(email=email, hashed_password=hashed_password)
    db.add(user)
    db_flush(db, exception_map)
    return user


def set_password(db: Session, user: User, hashed_password: str) -> None:
    """Reemplaza el hash de la contraseña. Recibe el hash, no la contraseña.

    Hashear es trabajo del router, que es el que decide *cuándo* pagar los ~100 ms de argon2
    — en el reset, igual que en el registro, ese costo se paga aunque el token no sirva, para
    que el tiempo de respuesta no cuente qué pasó. Un CRUD que hasheara solo, sin saberlo,
    dejaría esa decisión escondida acá abajo.
    """
    user.hashed_password = hashed_password
    db.flush()


def confirm_email(db: Session, user: User) -> None:
    """Marca la dirección como confirmada, si no lo estaba ya.

    El guard hace la confirmación idempotente sin pisar el timestamp original, que es el
    dato que quieren tanto soporte como cualquier consulta sobre cuándo se dio de alta la
    cuenta de verdad.
    """
    if user.email_confirmed_at is None:
        user.email_confirmed_at = func.now()
        db.flush()
