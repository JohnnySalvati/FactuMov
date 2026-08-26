from datetime import UTC, datetime

import pytest

from factumov.crud.user import confirm_email, create, get_by_email
from factumov.exceptions import DuplicateUserEmailError
from tests.factories import make_user


def test_known(db):
    email = "mail1@lo.com"
    user = make_user(db, email=email, email_confirmed_at=datetime.now(UTC))
    assert get_by_email(db, email) == user


def test_unknown(db):
    make_user(db, email="mail1@lo.com", email_confirmed_at=datetime.now(UTC))
    assert get_by_email(db, "mail2@lo.com") is None


def test_inactive(db):
    email = "mail1@lo.com"
    user = make_user(db, email=email, is_active=False, email_confirmed_at=datetime.now(UTC))
    assert get_by_email(db, email) == user


def test_unconfirmed(db):
    email = "mail1@lo.com"
    user = make_user(db, email=email, email_confirmed_at=None)
    assert get_by_email(db, email) == user


def test_create_leaves_the_email_unconfirmed(db):
    """Es lo que hace que crear la fila no le dé acceso a nadie: el login exige confirmado."""
    user = create(db, email="nueva@lo.com", hashed_password="hash")

    assert user.id is not None
    assert user.email_confirmed_at is None
    assert user.is_active is True


def test_create_rejects_a_duplicate_email(db):
    make_user(db, email="repetida@lo.com")

    with pytest.raises(DuplicateUserEmailError):
        create(db, email="repetida@lo.com", hashed_password="hash")


def test_confirm_email_stamps_the_moment(db):
    user = make_user(db, email_confirmed_at=None)

    confirm_email(db, user)

    assert user.email_confirmed_at is not None


def test_confirm_email_does_not_move_an_existing_timestamp(db):
    """Idempotente sin pisar el alta real, que es el dato que quiere soporte."""
    original = datetime(2026, 1, 1, tzinfo=UTC)
    user = make_user(db, email_confirmed_at=original)

    confirm_email(db, user)

    assert user.email_confirmed_at == original
