from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from factumov.enums import Concepto, CondicionIva, DocType, IvaAliquot


class CustomerDraft(BaseModel):
    name: str | None = None
    condicion_iva: CondicionIva | None = None
    doc_type: DocType | None = None
    doc_number: str | None = None
    address: str | None = None


class InvoiceTemplateLineDraft(BaseModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    iva_aliquot: IvaAliquot | None = None


class InvoiceTemplateDraft(BaseModel):
    name: str | None = None
    fiscal_identity_id: UUID | None = None
    issuer_tax_id: str | None = None
    customer_id: UUID | None = None
    customer: CustomerDraft
    pos: int | None = None
    concepto: Concepto

    lines: list[InvoiceTemplateLineDraft] = []
