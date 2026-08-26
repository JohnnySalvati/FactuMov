import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from factumov.enums import CondicionIva, DocType


class CustomerCreate(BaseModel):
    name: str = Field(max_length=150)
    condicion_iva: CondicionIva
    doc_type: DocType
    doc_number: str = Field(max_length=11)
    address: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = Field(default=None, max_length=254)

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
    doc_number: str
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
    def normalize_email(cls, value: EmailStr | None) -> EmailStr | None:
        return value.strip().lower() if value is not None else None

    @model_validator(mode="after")
    def check_doc_number(self) -> "CustomerUpdate":
        doc_number_given = "doc_number" in self.model_fields_set
        if doc_number_given and self.doc_number is None:
            raise ValueError("Se requiere numero de documento/CUIT")
        return self


class TaxpayerLookup(BaseModel):
    """Los datos que el padrón de ARCA tiene sobre un CUIT.

    Es una **propuesta**, no un recurso: el endpoint que la devuelve no escribe nada. Mismo
    criterio que el `InvoiceTemplateDraft` de la importación de PDF — dar de alta el cliente
    sin que el usuario confirme convertiría una consulta en un efecto secundario, y consultar
    dos veces el mismo CUIT le forkearía la historia.

    Los campos coinciden con `CustomerCreate` a propósito: la UI usa esto para prellenar el
    formulario de alta, y cualquier renombre obligaría a un mapeo en el medio.
    """

    # Sin `from_attributes`: el `Taxpayer` del servicio llama `tax_id` a lo que acá es
    # `doc_number`, y el vocabulario correcto de cada lado es distinto —"contribuyente" en
    # ARCA, "cliente" en FactuMov—. El router hace la traducción, que son cuatro líneas.
    #
    # `doc_type` no viene del padrón: el padrón se consulta por CUIT y solo devuelve CUIT.
    # Va fijo para que el formulario quede completo sin que la UI tenga que saberlo.
    doc_type: DocType = DocType.CUIT
    doc_number: str
    name: str
    condicion_iva: CondicionIva
    address: str | None = None
    # "ACTIVO" en el padrón. Un CUIT inactivo se puede consultar igual, y la UI decide si
    # avisa: no es motivo para negarse a cargar el cliente, pero sí para mostrarlo.
    active: bool
