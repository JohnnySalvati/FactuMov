from datetime import UTC, datetime

from factumov.crud.user import get_by_email
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
