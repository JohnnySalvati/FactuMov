import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import CondicionIva
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.invoice_template import InvoiceTemplate


class FiscalIdentity(Base, TimestampMixin):
    __tablename__ = "fiscal_identities"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    condicion_iva: Mapped[CondicionIva] = mapped_column(Enum(CondicionIva))
    tax_id: Mapped[str] = mapped_column(String(11), unique=True)
    address: Mapped[str | None] = mapped_column(String(200))
    iibb: Mapped[str | None] = mapped_column(String(50))
    start_date: Mapped[date | None] = mapped_column(Date)

    invoice_templates: Mapped[list["InvoiceTemplate"]] = relationship(
        back_populates="fiscal_identity"
    )
