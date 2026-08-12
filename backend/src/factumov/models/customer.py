import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import CondicionIva, DocType
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.invoice_template import InvoiceTemplate


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        Index(
            "uq_customers_doc_type_doc_number",
            "doc_type",
            "doc_number",
            unique=True,
            postgresql_where=text("doc_type <> 'FINAL'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150))
    condicion_iva: Mapped[CondicionIva] = mapped_column(Enum(CondicionIva))
    doc_type: Mapped[DocType] = mapped_column(Enum(DocType))
    doc_number: Mapped[str | None] = mapped_column(String(11))
    address: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))

    invoice_templates: Mapped[list["InvoiceTemplate"]] = relationship(
        back_populates="customer", passive_deletes="all"
    )
