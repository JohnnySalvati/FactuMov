from datetime import UTC, datetime, timedelta

from factumov.crud.user_session import create, get_active_by_token_hash, revoke
from factumov.services.security import hash_session_token
from tests.factories import make_user, make_user_session


def test_hash_no_match(db):
    make_user_session(db)
    hashed_token = hash_session_token("cualquier otro token")
    assert get_active_by_token_hash(db, hashed_token) is None


def test_find(db):
    user_session = make_user_session(db)
    assert get_active_by_token_hash(db, user_session.token_hash) == user_session


def test_find_expired(db):
    user_session = make_user_session(db, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    assert get_active_by_token_hash(db, user_session.token_hash) is None


def test_find_revoked(db):
    user_session = make_user_session(db, revoked_at=datetime.now(UTC) - timedelta(minutes=1))
    assert get_active_by_token_hash(db, user_session.token_hash) is None


def test_create(db):
    user = make_user(db)
    token_hash = hash_session_token("safdf")
    user_session = create(
        db,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert get_active_by_token_hash(db, token_hash) == user_session


def test_revoke(db):
    user = make_user(db)
    token_hash = hash_session_token("safdf")
    user_session = create(
        db,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert get_active_by_token_hash(db, token_hash) == user_session
    revoke(db, user_session)
    assert get_active_by_token_hash(db, token_hash) is None
