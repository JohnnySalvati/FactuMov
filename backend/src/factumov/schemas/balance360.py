"""Entrada y salida de la conexión con Balance360.

Entran las credenciales del usuario en Balance360 y **no sale ninguna**. La contraseña se usa
para pedir el token y no se guarda en ningún lado; el token se guarda cifrado y tampoco vuelve:
lo que sale es `token_hint`, los últimos caracteres, que alcanzan para que el usuario reconozca
cuál está puesto. Un endpoint que devolviera la credencial completa convierte cualquier XSS en
la SPA en un robo de acceso a la contabilidad, y no compra nada: quien la quiera cambiar
vuelve a conectar.
"""

import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Balance360ConnectionUpsert(BaseModel):
    """Conectar, o reemplazar lo que ya estaba.

    Es un PUT y no un POST + PATCH porque hay a lo sumo una conexión por usuario: el recurso
    es "mi conexión", siempre está en la misma dirección, y guardar es idempotente. Con POST
    habría que contestar 409 la segunda vez, que es exactamente lo que el usuario hace cuando
    vuelve a conectar porque le revocaron el token del otro lado.
    """

    base_url: str = Field(min_length=1, max_length=200)
    # Las credenciales del usuario **en Balance360**, que no tienen nada que ver con las de
    # acá: son dos aplicaciones y dos cuentas, aunque la persona sea la misma y muchas veces
    # el mail coincida.
    email: str = Field(min_length=1, max_length=255)
    # Viaja una vez y no se guarda. El backend la cambia por un token en el momento y se
    # olvida de ella; no hay ninguna columna donde pudiera terminar. Ver `fetch_token`.
    password: str = Field(min_length=1, max_length=200)
    auto_register: bool = True

    @field_validator("base_url")
    @classmethod
    def _clean_base_url(cls, value: str) -> str:
        """Sin barra final y con esquema explícito.

        La barra se saca acá y no al armar cada URL: si la normalización vive en el cliente
        HTTP, la base guardada puede tener dos formas para la misma cosa y cualquier
        comparación posterior miente. El esquema se exige porque `requests` sin `http://`
        no interpreta un host, tira `MissingSchema` y el usuario vería un 500 en vez de un
        422 que dice qué le falta a lo que pegó.
        """
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("La dirección tiene que empezar con http:// o https://")
        return value

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: str) -> str:
        """Sin espacios alrededor.

        Un mail se copia y se pega tanto como se tipea, y un espacio invisible del otro lado no
        encuentra al usuario: la respuesta sería "mail o contraseña incorrectos" —la misma que
        da una contraseña mal escrita— y el usuario se pondría a cambiar la que está bien.
        """
        return value.strip()


class Balance360ConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    base_url: str
    # Los últimos caracteres del token guardado, para poder distinguirlo de otro.
    token_hint: str
    # Cuándo Balance360 lo aceptó por última vez. `null` = nunca se pudo probar. No dice que
    # siga siendo válido: lo pueden haber revocado del otro lado sin avisarnos.
    verified_at: datetime.datetime | None
    auto_register: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class Balance360Settings(BaseModel):
    """El estado de la integración para este usuario, en un solo objeto.

    Junta dos cosas de naturalezas distintas a propósito: si el **servidor** puede guardar
    secretos (`available`, que depende del `.env` y es igual para todos) y si **este usuario**
    conectó su cuenta. La pantalla las necesita juntas para decidir qué mostrar, y separarlas
    en dos endpoints serían dos requests para pintar un formulario.
    """

    # `False` cuando falta `SECRET_ENCRYPTION_KEY`: la app anda igual, pero esta pantalla no
    # puede guardar nada y lo dice antes de que el usuario pegue el token.
    available: bool
    # `None` = no conectado. Es un estado normal, no un error.
    connection: Balance360ConnectionRead | None


class Balance360RegisterPendingResult(BaseModel):
    """Cómo salió el reintento en lote. Tres números porque la respuesta útil es "cuántas".

    El detalle de por qué falló cada una no viaja acá: ya quedó escrito en cada factura, que
    es donde la pantalla lo va a mostrar al lado del comprobante que lo tuvo. Repetirlo en
    esta respuesta sería la misma información en dos formas que se pueden desincronizar.
    """

    attempted: int
    registered: int
    failed: int
