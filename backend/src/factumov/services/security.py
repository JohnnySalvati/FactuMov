import hashlib
import secrets

from pwdlib import PasswordHash

_password_hasher = PasswordHash.recommended()
_DUMMY_PASSWORD = "dummyargon2password"
_DUMMY_HASH = _password_hasher.hash(_DUMMY_PASSWORD)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    if hashed_password is None:
        valid = False
        _password_hasher.verify(password, _DUMMY_HASH) # This line simulates verify to waste time 
    else:
        valid = _password_hasher.verify(password, hashed_password)
    return valid


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
