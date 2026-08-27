import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import IvaAliquot
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.invoice import Invoice


class InvoiceLine(Base, TimestampMixin):
    """Una línea de una factura emitida. Copia de la línea del modelo en el momento de emitir.

    Misma forma que `InvoiceTemplateLine` y a propósito: son el mismo dato en dos estados, y
    darles columnas distintas obligaría a traducir en el único lugar donde importa que no se
    pierda nada.

    **No guarda el neto ni el IVA de la línea**, aunque la factura sí guarde sus totales. La
    diferencia es que el total es lo que ARCA autorizó —un hecho que hay que preservar— y el
    importe de la línea es una multiplicación exacta de dos números que están acá al lado:
    recalcularla no puede dar distinto. Lo que sí puede cambiar es el redondeo del reparto por
    alícuota, y eso es justamente lo que está guardado arriba.

    `position` explícita, igual que en el modelo: ordenar por `created_at` se rompe cuando dos
    líneas entran en el mismo flush, que es exactamente lo que pasa al emitir.
    """

    __tablename__ = "invoice_lines"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=2))
    iva_aliquot: Mapped[IvaAliquot] = mapped_column(
        Enum(IvaAliquot, values_callable=lambda obj: [e.name for e in obj])
    )

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")
