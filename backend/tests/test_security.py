from factumov.services.security import (
    _DUMMY_PASSWORD,
    hash_opaque_token,
    hash_password,
    verify_password,
)


def test_password():
    password = "Esta es una clave de mentira"
    hashed_password = hash_password(password)
    assert verify_password(password, hashed_password)
    assert not verify_password("Esta clave no es ", hashed_password)


def test_password_none():
    assert not verify_password("Mypass", None)


def test_dummyargon():
    assert not verify_password(_DUMMY_PASSWORD, None)


def test_hash_password():
    password = "Esta es una clave de mentira"
    assert hash_password(password) != hash_password(password)


def test_hash_session():
    token = "tokenkjlkjasdljslfj dlkj"
    assert hash_opaque_token(token) == hash_opaque_token(token)
