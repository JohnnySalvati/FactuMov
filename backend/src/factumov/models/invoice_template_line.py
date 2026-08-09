import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from factumov.models.invoice_template import InvoiceTemplate
from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import IvaAliquot
from factumov.models.base import Base, TimestampMixin


class InvoiceTemplateLine(Base, TimestampMixin):
    __tablename__ = "invoice_template_lines"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoice_templates.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=2))
    iva_aliquot: Mapped[IvaAliquot] = mapped_column(
        Enum(IvaAliquot, values_callable=lambda obj: [e.name for e in obj])
    )

    invoice_template: Mapped["InvoiceTemplate"] = relationship(back_populates="lines")
