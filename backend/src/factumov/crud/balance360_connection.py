"""Acceso a `balance360_connections`, siempre por usuario.

No hay `get_by_id`: el recurso es "la conexión del usuario" y su clave natural es el
`user_id`, que además es único. Un getter por id abriría la puerta a leer la de otro y no
haría falta para nada — la SPA nunca tiene un id de conexión ajeno para pedir.
"""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from factumov.crud.base import db_flush
from factumov.models.balance360_connection import Balance360Connection

exception_map: dict[str, type[Exception]] = {}


def get_for_user(db: Session, user_id: uuid.UUID) -> Balance360Connection | None:
    return (
        db.execute(
            select(Balance360Connection).where(Balance360Connection.user_id == user_id)
        )
        .scalars()
        .first()
    )


def upsert(
    db: Session,
    user_id: uuid.UUID,
    *,
    base_url: str,
    encrypted_token: str,
    token_hint: str,
    auto_register: bool,
) -> Balance360Connection:
    """Guarda la conexión del usuario, exista o no.

    Recibe el token **ya cifrado** y su pista: el cifrado es una decisión del servicio, y
    pasarlo en claro hasta acá dejaría el secreto a la vista en la capa que menos lo necesita.

    Reemplazar el token borra `verified_at`. Es el invariante que hace que la pantalla no
    mienta: el tilde de "verificada" era sobre el token viejo, y el nuevo puede estar mal
    pegado. Lo vuelve a poner `mark_verified` cuando Balance360 lo acepta.
    """
    connection = get_for_user(db, user_id)
    if connection is None:
        connection = Balance360Connection(user_id=user_id)
        db.add(connection)
    connection.base_url = base_url
    connection.encrypted_token = encrypted_token
    connection.token_hint = token_hint
    connection.auto_register = auto_register
    connection.verified_at = None
    db_flush(db, exception_map)
    return connection


def mark_verified(db: Session, connection: Balance360Connection) -> Balance360Connection:
    connection.verified_at = datetime.datetime.now(datetime.timezone.utc)
    db_flush(db, exception_map)
    return connection


def delete(db: Session, connection: Balance360Connection) -> None:
    """Desconecta. No toca las facturas ya registradas: lo que está copiado del otro lado
    sigue estando, y su `balance360_invoice_id` sigue siendo cierto."""
    db.delete(connection)
    db_flush(db, exception_map)
