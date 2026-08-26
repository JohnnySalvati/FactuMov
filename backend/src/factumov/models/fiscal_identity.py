import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import CondicionIva
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.invoice_template import InvoiceTemplate


class FiscalIdentity(Base, TimestampMixin):
    __tablename__ = "fiscal_identities"
    __table_args__ = (
        # Unique por usuario, no global. Global rompe el caso del contador que carga el
        # CUIT de su cliente mientras el titular tiene su propia cuenta, y sobre todo
        # convierte el 409 en el oráculo de existencia que el 404 de esta unidad evita.
        UniqueConstraint("user_id", "name", name="uq_fiscal_identities_user_id_name"),
        UniqueConstraint("user_id", "tax_id", name="uq_fiscal_identities_user_id_tax_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Sin ondelete: el NO ACTION por defecto hace fallar el borrado de un usuario que
    # todavía tiene datos. Es lo correcto mientras no exista el endpoint de baja de
    # cuenta, que es la unidad que va a decidir si se borra en cascada o se anonimiza.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    condicion_iva: Mapped[CondicionIva] = mapped_column(Enum(CondicionIva))
    tax_id: Mapped[str] = mapped_column(String(11))
    address: Mapped[str | None] = mapped_column(String(200))
    iibb: Mapped[str | None] = mapped_column(String(50))
    start_date: Mapped[date | None] = mapped_column(Date)
    # Cuándo ARCA confirmó por última vez que FactuMov puede emitir por este CUIT.
    # Timestamp y no booleano, por lo mismo que `User.email_confirmed_at`: el "cuándo" es lo
    # que quiere la UI ("verificada hace 3 meses") y cualquier consulta de soporte. La
    # delegación se puede revocar del lado de ARCA sin avisarnos, así que este campo dice
    # "esto era verdad en esta fecha" y no "esto es verdad".
    #
    # Vive acá y no en `User` porque un usuario puede tener varios CUIT y cada uno se delega
    # por separado.
    delegation_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    invoice_templates: Mapped[list["InvoiceTemplate"]] = relationship(
        back_populates="fiscal_identity", passive_deletes="all"
    )
