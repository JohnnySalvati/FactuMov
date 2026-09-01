from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from factumov.enums import Concepto, VoucherType
from factumov.schemas.invoice_template_line import (
    InvoiceTemplateLineCreate,
    InvoiceTemplateLineRead,
)


def _blank_to_none(value: object) -> object:
    """Un texto en blanco es `None`, o sea "usá el mail por default".

    Existe porque los dos valores que el frontend puede mandar para "no personalicé nada" son
    distintos y significan lo mismo: el campo que nunca se tocó llega `null`, y el que se
    escribió y después se borró llega `""` — un `<textarea>` vacío no manda `null`. Guardar el
    segundo dejaría modelos mandando facturas sin asunto y sin cuerpo, que no es lo que quiso
    nadie: quien vacía el campo está pidiendo volver al texto de la app, no mandar un mail en
    blanco.

    `BeforeValidator` y no `AfterValidator` porque además recorta, y el recorte tiene que
    ocurrir **antes** del `max_length`: un texto de 200 caracteres con un enter al final no
    puede ser un 422 sobre algo que se va a descartar igual.
    """
    if not isinstance(value, str):
        return value
    return value.strip() or None


# El asunto y el cuerpo comparten la normalización y se diferencian solo en el largo. Los dos
# topes son de la columna: el asunto es una línea y el cuerpo, un mail corto de acompañamiento
# —el comprobante va adjunto—. Sin tope, un `<textarea>` es la forma más fácil que tiene esta
# API de comerse un megabyte por request.
EmailSubject = Annotated[
    Annotated[str, Field(max_length=200)] | None, BeforeValidator(_blank_to_none)
]
EmailBody = Annotated[
    Annotated[str, Field(max_length=2000)] | None, BeforeValidator(_blank_to_none)
]


class InvoiceTemplateCreate(BaseModel):
    name: str = Field(max_length=200)
    fiscal_identity_id: UUID
    customer_id: UUID
    pos: int = Field(gt=0)
    concepto: Concepto = Concepto.products

    # El mail con el que se manda la factura. Opcionales y con `None` por default: el modelo
    # que no dice nada manda el texto de la app, que es lo que hacían todos hasta ahora.
    # Escribirlos es del plan Pro, y eso lo chequea el router — no el schema: es una condición
    # de la cuenta y no del body, igual que el cupo mensual de comprobantes.
    email_subject: EmailSubject = None
    email_body: EmailBody = None

    lines: list[InvoiceTemplateLineCreate] = Field(min_length=1)


class InvoiceTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    fiscal_identity_id: UUID
    customer_id: UUID
    # No entra por ningún schema de escritura: se deduce de las condiciones frente al IVA del
    # emisor y del receptor. Sale en el Read porque la pantalla la muestra y porque el cliente
    # no debería tener que rehacer la cuenta para saber qué se va a emitir.
    voucher_type: VoucherType
    pos: int
    concepto: Concepto
    # `None` = "el mail por default". La pantalla lo dibuja como el campo vacío con el texto de
    # la app de placeholder, que es la forma de que se vea qué se manda sin fingir que es algo
    # que el usuario escribió.
    email_subject: str | None
    email_body: str | None
    created_at: datetime
    updated_at: datetime

    lines: list[InvoiceTemplateLineRead]


class InvoiceTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    fiscal_identity_id: UUID | None = None
    customer_id: UUID | None = None
    pos: int | None = Field(default=None, gt=0)
    concepto: Concepto | None = None
    # Acá `None` es ambiguo a propósito y el CRUD la deshace con `exclude_unset`: el PATCH que
    # no trae el campo lo deja como estaba, y el que lo trae en `null` —o en blanco— lo borra,
    # o sea vuelve al texto por default. Borrarlo **no** pide ser Pro: es la única forma que
    # tiene un ex-Pro de sacarse de encima un texto que ya no puede editar.
    email_subject: EmailSubject = None
    email_body: EmailBody = None

    lines: list[InvoiceTemplateLineCreate] | None = Field(default=None, min_length=1)
