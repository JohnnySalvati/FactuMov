import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.models.base import Base, TimestampMixin
from factumov.models.user import User


class Balance360Connection(Base, TimestampMixin):
    """Con qué credencial este usuario le habla a su Balance360.

    **Una por usuario**, no una por identidad fiscal, y eso decide la forma de toda la
    integración. Del otro lado el token *es* un usuario: Balance360 deduce a qué entidad
    corresponde el comprobante buscando el CUIT del emisor entre las entidades de las que ese
    usuario es miembro. O sea que un solo token ya cubre todos los CUIT de la persona, y
    tener uno por identidad fiscal sería pedirle N veces la misma credencial para que el
    ruteo lo siga haciendo el CUIT igual.

    Queda un caso sin resolver a propósito: el mismo CUIT ligado a dos entidades de Balance360
    en las que el usuario está. Ahí la otra app no puede elegir y contesta que se elija — el
    contrato acepta una entidad explícita, pero acá no hay dónde guardarla todavía. Una tabla
    de mapeo CUIT → entidad se agrega el día que ese caso exista de verdad; hoy sería una
    tabla, una pantalla y una migración a cuenta de una situación hipotética, y el error de
    Balance360 llega con el texto que explica qué hacer.

    **El token va cifrado, no hasheado.** Es el único secreto ajeno de la app que hay que
    poder volver a leer, porque viaja en cada request; el porqué del cifrado y qué pasa si se
    pierde la clave están en `services/secrets.py`.

    No lleva `fiscal_identity_id` ni `entity_id`: todo el ruteo lo hace el CUIT que ya viaja
    en el comprobante.
    """

    __tablename__ = "balance360_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # `unique` y no solo `index`: es la restricción que hace que "la conexión del usuario"
    # sea una expresión con sentido. Sin ella, dos conexiones del mismo usuario dejarían al
    # registro eligiendo una arbitrariamente, que es la clase de bug que aparece meses después.
    # Sin `ondelete`, igual que el resto: borrar un usuario con datos tiene que fallar
    # mientras no exista el endpoint de baja de cuenta.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)

    # No hay `base_url`: la dirección del Balance360 es config del servidor
    # (`BALANCE360_BASE_URL`) y no un dato de cada usuario. Era una columna, y era una copia
    # del mismo valor por cada cuenta conectada: quien puede saber en qué host corre la otra
    # app es quien deployó las dos, no la persona que aprieta "conectar".

    # El token de `/api`, cifrado con Fernet. 500 caracteres es holgado: el token son ~48 y
    # el sobre de Fernet lo lleva a ~180, pero el largo depende de la versión del formato y
    # apretar la columna al valor de hoy no compra nada.
    encrypted_token: Mapped[str] = mapped_column(String(500))

    # Los últimos caracteres del token, en claro, para que la pantalla pueda decir cuál está
    # guardado ("b360_…kX7q"). Sin esto la única forma de distinguir dos tokens es probarlos.
    # Cuatro caracteres de un secreto de 256 bits no acercan a nadie a adivinarlo.
    token_hint: Mapped[str] = mapped_column(String(8))

    # Cuándo Balance360 aceptó por última vez este token. Timestamp y no booleano, como
    # `delegation_verified_at` y por el mismo motivo: el token se puede revocar del otro lado
    # sin avisarnos, así que esto dice "esto era verdad en esta fecha", no "esto es verdad".
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Si el registro sale solo después de emitir. Apagarlo deja las facturas en `PENDING` y
    # el registro pasa a ser un botón. Existe porque conectar y registrar son dos decisiones
    # distintas: alguien puede querer conectar la cuenta y elegir qué copia y cuándo.
    auto_register: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True
    )

    user: Mapped["User"] = relationship()
