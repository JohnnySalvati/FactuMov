from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

# Piso de largo de contraseña. No hay reglas de composición —mayúscula, dígito, símbolo—
# a propósito: empujan a la gente a "Password1!" y NIST las desaconseja desde 2017. El
# largo es lo que agrega entropía de verdad. El techo no es política sino defensa: sin él,
# una contraseña de megabytes le hace quemar CPU a argon2 gratis.
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128


class _EmailIn(BaseModel):
    """El campo email de entrada, normalizado.

    Está en una base y no copiado en los tres schemas que lo usan porque la normalización
    es justamente lo que no puede diferir entre ellos: si el registro guarda `miguel@x.com`
    y el login busca `Miguel@x.com`, el `unique=True` no lo impide y la cuenta queda
    inaccesible sin ningún error visible.
    """

    email: EmailStr = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> EmailStr:
        return value.lower()


class LoginRequest(_EmailIn):
    # Sin `min_length`: el login no valida la política de contraseñas. Un 422 por
    # "muy corta" le diría al atacante que su intento no llegó ni a compararse, y de paso
    # dejaría afuera a cualquier usuario viejo si el mínimo sube algún día.
    password: SecretStr


class RegisterRequest(_EmailIn):
    password: SecretStr = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class ResendConfirmationRequest(_EmailIn):
    pass


class ConfirmEmailRequest(BaseModel):
    # El token viaja en el body y no en el path: los tokens en la URL quedan en el historial
    # del browser, en los logs del server y en el `Referer` de cualquier recurso externo que
    # cargue esa página. La SPA lo lee del query string del link del mail y lo postea.
    token: str = Field(min_length=1, max_length=256)


class MessageResponse(BaseModel):
    detail: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
