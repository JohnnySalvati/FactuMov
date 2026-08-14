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
