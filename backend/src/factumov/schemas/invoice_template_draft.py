from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from factumov.enums import Concepto, CondicionIva, DocType, IvaAliquot, VoucherType


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
    # La letra que traía el PDF. No se guarda en ningún lado —el modelo la deduce de las dos
    # condiciones frente al IVA— pero el editor la necesita para saber **cómo leer el precio
    # que viene acá**: en A es neto y en B y C trae el IVA adentro. Sin esto, un draft de una A
    # cuyo receptor todavía no está en la cartera se sembraría como si el precio tuviera el IVA
    # adentro, y al guardar quedaría un 21% más barato. `None` cuando el PDF no dijo la letra.
    voucher_type: VoucherType | None = None

    lines: list[InvoiceTemplateLineDraft] = []
