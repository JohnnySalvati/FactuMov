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
        # Se verifica contra un hash dummy y se descarta el resultado: sin esto, el email
        # desconocido volvería antes que la contraseña incorrecta y el tiempo de respuesta
        # delataría cuáles direcciones están registradas.
        _password_hasher.verify(password, _DUMMY_HASH)
    else:
        valid = _password_hasher.verify(password, hashed_password)
    return valid


# Un solo par de funciones para los dos tokens opacos del sistema: el de sesión y el de
# confirmación de email. La mecánica es idéntica —256 bits de `secrets`, guardados como
# SHA-256— y el nombre no dice "session" porque no tiene nada de la sesión adentro. SHA-256
# y no argon2: con esa entropía no hay diccionario que atacar, y un KDF lento costaría ~100
# ms en cada request autenticado sin comprar nada.
def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
