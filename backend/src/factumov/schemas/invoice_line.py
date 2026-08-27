from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from factumov.enums import IvaAliquot


class InvoiceLineRead(BaseModel):
    """Una línea de una factura emitida.

    Solo lectura: no hay `Create` ni `Update` porque las líneas de una factura no se escriben
    desde afuera. Salen de copiar las del modelo en el momento de emitir y no se tocan nunca
    más — ver `models/invoice.py`.
    """

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    iva_aliquot: IvaAliquot
    created_at: datetime
    updated_at: datetime
