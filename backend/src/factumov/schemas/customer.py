import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from factumov.enums import CondicionIva, DocType


class CustomerCreate(BaseModel):
    name: str = Field(max_length=150)
    condicion_iva: CondicionIva
    doc_type: DocType
    doc_number: str | None = Field(default=None, max_length=11)
    address: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = Field(default=None, max_length=254)

    @model_validator(mode="after")
    def check_doc_number(self) -> "CustomerCreate":
        if not self.doc_number and not self.doc_type == DocType.FINAL:
            raise ValueError("Se requiere numero de documento/CUIT")
        return self

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr | None) -> EmailStr | None:
        return value.strip().lower() if value else None


class CustomerRead(BaseModel):
    id: uuid.UUID
    model_config = ConfigDict(from_attributes=True)
    name: str
    condicion_iva: CondicionIva
    doc_type: DocType
    doc_number: str | None = None
    address: str | None = None
    email: str | None = None
    created_at: datetime
    updated_at: datetime


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    condicion_iva: CondicionIva | None = None
    doc_type: DocType | None = None
    doc_number: str | None = Field(default=None, max_length=11)
    address: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = Field(default=None, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr | None) -> EmailStr | None:
        return value.strip().lower() if value else None

    @model_validator(mode="after")
    def check_doc_number(self) -> "CustomerUpdate":
        doc_type_given = "doc_type" in self.model_fields_set
        doc_number_given = "doc_number" in self.model_fields_set
        if doc_type_given and doc_number_given:
            if self.doc_type != DocType.FINAL and self.doc_number is None:
                raise ValueError("Se requiere numero de documento/CUIT")
        return self
