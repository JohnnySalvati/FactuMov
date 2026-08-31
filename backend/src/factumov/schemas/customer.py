import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from factumov.enums import CondicionIva, DocType

# Un tope al CC: "contador, gestor, socio" entra de sobra, y sin límite el endpoint de envío
# —que ya tiene su rate limit por usuario— se vuelve una forma de mandar un mail a 50
# direcciones por factura.
CC_EMAILS_MAX = 5


def _clean_cc_emails(cc_emails: list[str], primary: str | None) -> list[str]:
    """Normaliza el CC: minúsculas, sin espacios, sin repetidos y sin el destinatario principal.

    Copiar en CC a la misma dirección que va en el To no rompe nada, pero le llega el mail dos
    veces y en la ficha se ve redundante. Sacarlo acá deja una sola fuente de esa regla.
    """
    seen: set[str] = {primary.strip().lower()} if primary else set()
    cleaned: list[str] = []
    for raw in cc_emails:
        address = raw.strip().lower()
        if address and address not in seen:
            seen.add(address)
            cleaned.append(address)
    return cleaned


class CustomerCreate(BaseModel):
    name: str = Field(max_length=150)
    condicion_iva: CondicionIva
    doc_type: DocType
    doc_number: str = Field(max_length=11)
    address: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = Field(default=None, max_length=254)
    # El To es `email`; esto es solo el CC. Va como lista y no admite `None`: "sin copia" es
    # la lista vacía, que además es el default.
    cc_emails: list[EmailStr] = Field(default_factory=list, max_length=CC_EMAILS_MAX)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr | None) -> EmailStr | None:
        return value.strip().lower() if value else None

    @model_validator(mode="after")
    def normalize_cc_emails(self) -> "CustomerCreate":
        # Después del `field_validator` de `email`, así `_clean_cc_emails` ve el To ya
        # normalizado y puede descartarlo del CC.
        self.cc_emails = _clean_cc_emails(self.cc_emails, self.email)
        return self


class CustomerRead(BaseModel):
    id: uuid.UUID
    model_config = ConfigDict(from_attributes=True)
    name: str
    condicion_iva: CondicionIva
    doc_type: DocType
    doc_number: str
    address: str | None = None
    email: str | None = None
    cc_emails: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    condicion_iva: CondicionIva | None = None
    doc_type: DocType | None = None
    doc_number: str | None = Field(default=None, max_length=11)
    address: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = Field(default=None, max_length=254)
    # Sin `None`: mandar `[]` es "sacar todo el CC", y no mandar el campo es "no lo toques"
    # —eso lo resuelve `exclude_unset` en `crud.update`, igual que el resto de los campos—.
    cc_emails: list[EmailStr] = Field(default_factory=list, max_length=CC_EMAILS_MAX)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> EmailStr | None:
        return value.strip().lower() if value is not None else None

    @model_validator(mode="after")
    def normalize_cc_emails(self) -> "CustomerUpdate":
        # Solo si el campo vino en el request: tocarlo lo agrega a `model_fields_set`, y
        # `crud.update` usa `exclude_unset` para no pisar lo que no se mandó.
        if "cc_emails" in self.model_fields_set:
            self.cc_emails = _clean_cc_emails(self.cc_emails, self.email)
        return self

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
