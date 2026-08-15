from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from factumov.enums import Concepto, VoucherType
from factumov.schemas.invoice_template_line import (
    InvoiceTemplateLineCreate,
    InvoiceTemplateLineRead,
)


class InvoiceTemplateCreate(BaseModel):
    name: str = Field(max_length=200)
    fiscal_identity_id: UUID
    customer_id: UUID
    voucher_type: VoucherType
    pos: int = Field(gt=0)
    concepto: Concepto = Concepto.products

    lines: list[InvoiceTemplateLineCreate] = Field(min_length=1)


class InvoiceTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    fiscal_identity_id: UUID
    customer_id: UUID
    voucher_type: VoucherType
    pos: int
    concepto: Concepto
    created_at: datetime
    updated_at: datetime

    lines: list[InvoiceTemplateLineRead]


class InvoiceTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    fiscal_identity_id: UUID | None = None
    customer_id: UUID | None = None
    voucher_type: VoucherType | None = None
    pos: int | None = Field(default=None, gt=0)
    concepto: Concepto | None = None

    lines: list[InvoiceTemplateLineCreate] | None = Field(default=None, min_length=1)
