"""Cifrado de los secretos que la app tiene que poder **volver a leer**.

Es la excepción a `services/security.py`, y la diferencia es qué se hace después con el
secreto. La contraseña, el token de sesión y el de confirmación de mail se guardan hasheados
porque nunca hay que recuperarlos: llega uno, se hashea y se compara. El token de Balance360
es al revés — hay que mandarlo en cada request, así que hashearlo lo volvería inservible.

Guardarlo en texto plano tampoco: en Balance360 el token vive hasheado, o sea que esta base
es el **único** lugar del mundo donde existe en forma usable. Un dump —un backup que se
filtra, una consulta de más— entregaría acceso de escritura a la contabilidad de cada usuario
conectado. Cifrarlo mueve el secreto de la base al entorno del proceso, que es una superficie
distinta y mucho más chica.

Fernet y no algo armado a mano: viene en `cryptography`, que ya es dependencia por el
certificado de ARCA, y trae AES-CBC con HMAC ya combinados. La parte que se suele hacer mal
—el modo, el IV, la autenticación— no queda de nuestro lado.

**La clave vive en `SECRET_ENCRYPTION_KEY` y perderla no es una catástrofe.** Sin ella los
tokens guardados no se pueden descifrar, pero el remedio es que cada usuario vuelva a pegar
el suyo: es un secreto que se puede reemitir del otro lado, no un dato que se pierde. Por eso
la app arranca igual sin la variable —como con el mail— y lo que falla es solo la
integración, no FactuMov.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from factumov.exceptions import SecretDecryptionError, SecretsNotConfiguredError


class SecretsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Una clave Fernet: 32 bytes en base64 urlsafe. Se genera con
    #     uv run python -c "from cryptography.fernet import Fernet;
    #                       print(Fernet.generate_key().decode())"
    secret_encryption_key: SecretStr | None = None


@lru_cache
def get_secrets_settings() -> SecretsSettings:
    return SecretsSettings()


@lru_cache
def _cipher() -> Fernet:
    key = get_secrets_settings().secret_encryption_key
    if key is None:
        raise SecretsNotConfiguredError(
            "Falta SECRET_ENCRYPTION_KEY: sin esa variable no se pueden guardar ni leer los "
            "tokens de integración."
        )
    try:
        return Fernet(key.get_secret_value())
    except (ValueError, TypeError) as error:
        raise SecretsNotConfiguredError(
            "SECRET_ENCRYPTION_KEY no es una clave Fernet válida (32 bytes en base64 urlsafe)."
        ) from error


def is_configured() -> bool:
    """Si la app puede cifrar y descifrar secretos.

    Existe para que las pantallas de la integración digan "esto no está configurado en el
    servidor" en vez de reventar con un 500 cuando el usuario intenta conectar.
    """
    try:
        _cipher()
    except SecretsNotConfiguredError:
        return False
    return True


def encrypt(value: str) -> str:
    """Cifra un secreto para guardarlo. Devuelve texto, para que entre en una columna común."""
    return _cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Recupera un secreto guardado.

    `InvalidToken` se traduce a una excepción del proyecto porque la causa que importa no es
    criptográfica: es que la clave del entorno ya no es la que cifró ese dato. El remedio —que
    el usuario vuelva a pegar su token— es lo que tiene que terminar diciendo la pantalla.
    """
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken as error:
        raise SecretDecryptionError(
            "El token guardado no se puede descifrar con la clave actual del servidor."
        ) from error
