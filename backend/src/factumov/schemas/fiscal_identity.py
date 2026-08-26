import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from factumov.enums import CondicionIva


class FiscalIdentityCreate(BaseModel):
    name: str = Field(max_length=150)
    condicion_iva: CondicionIva
    tax_id: str = Field(max_length=11)
    address: str | None = Field(default=None, max_length=200)
    iibb: str | None = Field(default=None, max_length=50)
    start_date: date | None = None

    @field_validator("tax_id")
    @classmethod
    def check_tax_id(cls, value: str) -> str:
        if not (value.isdigit() and len(value) == 11):
            raise ValueError("El CUIT debe tener 11 digitos")
        return value

    @field_validator("condicion_iva")
    @classmethod
    def check_condicion_iva(cls, value: CondicionIva) -> CondicionIva:
        if value == CondicionIva.FINAL:
            raise ValueError("Condicion IVA final no puede emitir comprobantes")
        return value


class FiscalIdentityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    condicion_iva: CondicionIva
    tax_id: str
    address: str | None
    iibb: str | None
    start_date: date | None
    # Sale en el Read porque la UI tiene que poder decidir si muestra el botón "emitir" o el
    # cartel de "todavía falta delegar". No entra por ningún schema de escritura: lo escribe
    # la verificación contra ARCA, no el cliente.
    delegation_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FiscalIdentityUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    condicion_iva: CondicionIva | None = None
    tax_id: str | None = Field(default=None, max_length=11)
    address: str | None = Field(default=None, max_length=200)
    iibb: str | None = Field(default=None, max_length=50)
    start_date: date | None = None

    @field_validator("tax_id")
    @classmethod
    def check_tax_id(cls, value: str | None) -> str | None:
        if value is not None:
            if not (value.isdigit() and len(value) == 11):
                raise ValueError("El CUIT debe tener 11 digitos")
        return value

    @field_validator("condicion_iva")
    @classmethod
    def check_condicion_iva(cls, value: CondicionIva | None) -> CondicionIva | None:
        if value is not None:
            if value == CondicionIva.FINAL:
                raise ValueError("Condicion IVA final no puede emitir comprobantes")
        return value


class DelegationStatus(BaseModel):
    """La respuesta de `POST /fiscal-identities/{id}/verify-delegation`.

    Sale con 200 tanto si la delegación está como si no: preguntar y que te contesten "no
    todavía" no es un error del cliente. El 4xx quedaría reservado para un pedido mal hecho,
    y esto está bien hecho — la respuesta simplemente es negativa.
    """

    granted: bool
    # `None` cuando `granted`. Cuando no, es el texto con el que ARCA lo explicó, que sirve
    # de guía al usuario y de pista al soporte.
    message: str | None = None
    # El mismo valor que quedó en la fila. Ahorra un GET para refrescar la pantalla.
    delegation_verified_at: datetime | None = None
    # El CUIT al que hay que autorizar en ARCA — el del certificado de FactuMov. Va solo en la
    # respuesta negativa, que es la única donde hay una instrucción que dar: cuando la
    # delegación ya está, repetir a quién había que autorizar no le sirve a la pantalla.
    delegate_tax_id: str | None = None
