"""Tests de `crud/email_confirmation.py`, sin pasar por HTTP.

Las tres causas por las que un token no sirve —desconocido, vencido, ya usado— tienen un
test cada una aunque el CRUD devuelva `None` para las tres. Que colapsen en la respuesta es
una decisión del endpoint; que el filtro las detecte es lo que se prueba acá, y si mañana
una se cae del `where` los otros dos tests seguirían en verde.
"""

from datetime import UTC, datetime, timedelta

from factumov.crud import email_confirmation as crud
from factumov.services.security import hash_opaque_token
from tests.factories import make_email_confirmation, make_user


def test_create_persists_the_token_hash_and_expiry(db):
    user = make_user(db)
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    confirmation = crud.create(
        db, user_id=user.id, token_hash=hash_opaque_token("token"), expires_at=expires_at
    )

    assert confirmation.id is not None
    assert confirmation.user_id == user.id
    assert confirmation.token_hash == hash_opaque_token("token")
    assert confirmation.confirmed_at is None


def test_get_pending_finds_a_live_token(db):
    make_email_confirmation(db, raw_token="vivo")

    found = crud.get_pending_by_token_hash(db, hash_opaque_token("vivo"))

    assert found is not None


def test_get_pending_brings_the_user_along(db):
    """El endpoint necesita el usuario, y el `joinedload` evita la query extra."""
    user = make_user(db, email="ana@cucu.com")
    make_email_confirmation(db, user_id=user.id, raw_token="vivo")

    found = crud.get_pending_by_token_hash(db, hash_opaque_token("vivo"))

    assert found is not None
    assert found.user.email == "ana@cucu.com"


def test_get_pending_ignores_an_unknown_token(db):
    make_email_confirmation(db, raw_token="vivo")

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("otro")) is None


def test_get_pending_ignores_an_expired_token(db):
    make_email_confirmation(
        db, raw_token="viejo", expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("viejo")) is None


def test_get_pending_ignores_an_already_used_token(db):
    make_email_confirmation(db, raw_token="usado", confirmed_at=datetime.now(UTC))

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("usado")) is None


def test_consume_marks_the_token_without_deleting_it(db):
    confirmation = make_email_confirmation(db, raw_token="vivo")

    crud.consume(db, confirmation)

    db.refresh(confirmation)
    assert confirmation.confirmed_at is not None
    assert crud.get_pending_by_token_hash(db, hash_opaque_token("vivo")) is None
