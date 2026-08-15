from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from factumov.enums import IvaAliquot


class InvoiceTemplateLineCreate(BaseModel):
    description: str = Field(max_length=200)
    quantity: Decimal = Field(max_digits=18, decimal_places=4, gt=0)
    unit_price: Decimal = Field(max_digits=18, decimal_places=2, ge=0)
    iva_aliquot: IvaAliquot


class InvoiceTemplateLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    iva_aliquot: IvaAliquot
    created_at: datetime
    updated_at: datetime
