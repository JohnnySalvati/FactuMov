"""Tests de `crud/password_reset.py`, sin pasar por HTTP.

Casi calcados de los de `email_confirmation`, porque el filtro es el mismo. Lo que no tiene
gemelo es `invalidate_all_for_user`, que es justo donde las dos tablas dejan de parecerse.
"""

from datetime import UTC, datetime, timedelta

from factumov.crud import password_reset as crud
from factumov.services.security import hash_opaque_token
from tests.factories import make_password_reset, make_user


def test_create_persists_the_token_hash_and_expiry(db):
    user = make_user(db)
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    reset = crud.create(
        db, user_id=user.id, token_hash=hash_opaque_token("token"), expires_at=expires_at
    )

    assert reset.id is not None
    assert reset.user_id == user.id
    assert reset.token_hash == hash_opaque_token("token")
    assert reset.used_at is None


def test_get_pending_finds_a_live_token(db):
    make_password_reset(db, raw_token="vivo")

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("vivo")) is not None


def test_get_pending_brings_the_user_along(db):
    """El endpoint necesita el usuario para cambiarle la contraseña, sin una query extra."""
    user = make_user(db, email="ana@cucu.com")
    make_password_reset(db, user_id=user.id, raw_token="vivo")

    found = crud.get_pending_by_token_hash(db, hash_opaque_token("vivo"))

    assert found is not None
    assert found.user.email == "ana@cucu.com"


def test_get_pending_ignores_an_unknown_token(db):
    make_password_reset(db, raw_token="vivo")

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("otro")) is None


def test_get_pending_ignores_an_expired_token(db):
    make_password_reset(db, raw_token="viejo", expires_at=datetime.now(UTC) - timedelta(seconds=1))

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("viejo")) is None


def test_get_pending_ignores_an_already_used_token(db):
    make_password_reset(db, raw_token="usado", used_at=datetime.now(UTC))

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("usado")) is None


def test_consume_marks_the_token_without_deleting_it(db):
    reset = make_password_reset(db, raw_token="vivo")

    crud.consume(db, reset)

    db.refresh(reset)
    assert reset.used_at is not None
    assert crud.get_pending_by_token_hash(db, hash_opaque_token("vivo")) is None


def test_invalidate_all_kills_every_live_token_of_that_user(db):
    user = make_user(db)
    make_password_reset(db, user_id=user.id, raw_token="uno")
    make_password_reset(db, user_id=user.id, raw_token="dos")

    crud.invalidate_all_for_user(db, user.id)

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("uno")) is None
    assert crud.get_pending_by_token_hash(db, hash_opaque_token("dos")) is None


def test_invalidate_all_leaves_other_users_alone(db):
    mine = make_user(db)
    theirs = make_user(db)
    make_password_reset(db, user_id=mine.id, raw_token="mio")
    make_password_reset(db, user_id=theirs.id, raw_token="ajeno")

    crud.invalidate_all_for_user(db, mine.id)

    assert crud.get_pending_by_token_hash(db, hash_opaque_token("ajeno")) is not None


def test_invalidate_all_does_not_overwrite_an_earlier_use(db):
    """`used_at` de un token consumido es un dato de auditoría: cuándo se usó, no cuándo se
    invalidó el resto."""
    user = make_user(db)
    used_at = datetime.now(UTC) - timedelta(minutes=30)
    old = make_password_reset(db, user_id=user.id, raw_token="viejo", used_at=used_at)

    crud.invalidate_all_for_user(db, user.id)

    db.refresh(old)
    assert abs(old.used_at - used_at) < timedelta(seconds=1)
