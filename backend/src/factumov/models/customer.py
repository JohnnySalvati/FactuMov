import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import CondicionIva, DocType
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.invoice_template import InvoiceTemplate


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        # El documento identifica al cliente dentro de la cartera de un usuario, no en
        # todo el sistema: dos usuarios le facturan al mismo cliente todo el tiempo.
        UniqueConstraint(
            "user_id",
            "doc_type",
            "doc_number",
            name="uq_customers_user_id_doc_type_doc_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    condicion_iva: Mapped[CondicionIva] = mapped_column(Enum(CondicionIva))
    doc_type: Mapped[DocType] = mapped_column(Enum(DocType))
    doc_number: Mapped[str] = mapped_column(String(11))
    address: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    # Direcciones que reciben una copia (CC) cada vez que se le manda una factura a este
    # cliente. `email` sigue siendo el destinatario principal —el To—; esto es solo el CC, y
    # el caso que lo motiva es "mandale también al contador y al gestor".
    #
    # Se leen en vivo al enviar, igual que `email` y por el mismo motivo: a quién copiar es
    # una pregunta sobre el envío que se está por hacer, no un hecho de la emisión. Ver la
    # propiedad `Invoice.customer_cc_emails` y *Mandar la factura por email* en
    # docs/emision-y-envio.md.
    #
    # Un array de Postgres y no una tabla aparte: es una lista corta que se edita entera desde
    # la ficha del cliente, no tiene historia que guardar y nadie la consulta al revés. El
    # `server_default` deja en `{}` a las filas que existían antes de la columna, que es la
    # verdad: no tenían CC.
    cc_emails: Mapped[list[str]] = mapped_column(
        ARRAY(String(254)), nullable=False, server_default="{}", default=list
    )

    invoice_templates: Mapped[list["InvoiceTemplate"]] = relationship(
        back_populates="customer", passive_deletes="all"
    )
