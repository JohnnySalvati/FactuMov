import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.customer import Customer
    from factumov.models.fiscal_identity import FiscalIdentity
    from factumov.models.invoice_template_line import InvoiceTemplateLine
from factumov.enums import Concepto, VoucherType
from factumov.services.voucher import voucher_type_for


class InvoiceTemplate(Base, TimestampMixin):
    __tablename__ = "invoice_templates"
    __table_args__ = (
        UniqueConstraint(
            "fiscal_identity_id", "name", name="uq_invoice_templates_fiscal_identity_id_name"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    fiscal_identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_identities.id"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
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

    @property
    def voucher_type(self) -> VoucherType:
        """La letra del comprobante. **Se deduce, no se guarda.**

        Sale de las dos condiciones frente al IVA — ver `services/voucher.py`, que explica por
        qué sin notas de crédito la respuesta es siempre una sola. Fue una columna hasta el
        2026-08-26: guardarla es una tercera fuente de verdad capaz de contradecir a sus dos
        padres, y el día que un cliente pasa de monotributista a inscripto el modelo guardado
        seguiría diciendo B cuando ARCA ya espera A.

        Toca las dos relaciones, así que el CRUD las trae con `joinedload`: sin eso, listar N
        modelos son 2N queries.
        """
        return voucher_type_for(self.fiscal_identity.condicion_iva, self.customer.condicion_iva)
