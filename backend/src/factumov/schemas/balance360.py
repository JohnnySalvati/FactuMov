"""Entrada y salida de la conexión con Balance360.

El token entra pero **no sale nunca**: lo que vuelve es `token_hint`, los últimos caracteres,
que alcanzan para que el usuario reconozca cuál guardó. Un endpoint que devuelva la
credencial completa convierte cualquier XSS en la SPA en un robo de acceso a la contabilidad,
y no compra nada: quien la quiera cambiar pega una nueva.
"""

import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Balance360ConnectionUpsert(BaseModel):
    """Conectar, o reemplazar lo que ya estaba.

    Es un PUT y no un POST + PATCH porque hay a lo sumo una conexión por usuario: el recurso
    es "mi conexión", siempre está en la misma dirección, y guardar es idempotente. Con POST
    habría que contestar 409 la segunda vez, que es exactamente lo que el usuario hace cuando
    le reemitieron el token.
    """

    base_url: str = Field(min_length=1, max_length=200)
    api_token: str = Field(min_length=8, max_length=200)
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
