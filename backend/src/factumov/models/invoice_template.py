import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.customer import Customer
    from factumov.models.fiscal_identity import FiscalIdentity
    from factumov.models.invoice_template_line import InvoiceTemplateLine
from factumov.enums import Concepto, VoucherType


class InvoiceTemplate(Base, TimestampMixin):
    __tablename__ = "invoice_templates"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    fiscal_identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_identities.id"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    voucher_type: Mapped[VoucherType] = mapped_column(Enum(VoucherType))
    pos: Mapped[int] = mapped_column(Integer)
    concepto: Mapped[Concepto] = mapped_column(
        Enum(Concepto), default=Concepto.products, server_default=Concepto.products.name
    )

    fiscal_identity: Mapped["FiscalIdentity"] = relationship(back_populates="invoice_templates")
    customer: Mapped["Customer"] = relationship(back_populates="invoice_templates")
    lines: Mapped[list["InvoiceTemplateLine"]] = relationship(
        back_populates="invoice_template",
        cascade="all, delete-orphan",
        order_by="InvoiceTemplateLine.position",
    )
