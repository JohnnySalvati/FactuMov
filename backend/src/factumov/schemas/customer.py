import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from factumov.enums import CondicionIva, DocType


class CustomerCreate(BaseModel):
    name: str = Field(max_length=150)
    condicion_iva: CondicionIva
    doc_type: DocType
    doc_number: str | None = Field(default=None, max_length=11)
    address: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)

    @model_validator(mode="after")
    def check_doc_number(self) -> "CustomerCreate":
        if not self.doc_number and not self.doc_type == DocType.FINAL:
            raise ValueError("Se requiere numero de documento/CUIT")
        return self


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    condicion_iva: CondicionIva
    doc_type: DocType
    doc_number: str | None = None
    address: str | None = None
    email: str | None = None
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    condicion_iva: CondicionIva | None = None
    doc_type: DocType | None = None
    doc_number: str | None = Field(default=None, max_length=11)
    address: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
