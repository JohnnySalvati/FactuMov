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

    # --- El mail con el que se manda la factura emitida de este modelo ---
    #
    # Dos columnas y no una: el asunto es lo que el destinatario ve en la lista de su casilla y
    # el cuerpo es lo que lee al abrir, así que se escriben por separado y se pueden
    # personalizar por separado. Cada una cae en el texto por default de forma independiente —
    # el que solo quiso cambiar el cuerpo conserva el asunto que arma la app, con el número del
    # comprobante y la razón social adentro.
    #
    # **`None` significa "el texto de la app", no "sin texto".** Es lo que tienen todos los
    # modelos que existían antes de esta columna y lo que sigue siendo el default de los
    # nuevos: el mail que ya se venía mandando. Un string vacío sería otra cosa —un mail sin
    # asunto— y por eso el schema lo convierte a `None` en vez de guardarlo.
    #
    # **Van acá y no en `invoices`.** El texto del mail es una pregunta sobre el envío que se
    # está por hacer, no un hecho de la emisión: es la misma razón por la que el mail del
    # cliente se lee en vivo y no se copia al emitir. Ver *La factura emitida es lo contrario
    # del modelo* en `docs/emision-y-envio.md`. La consecuencia es que corregirle una falta de
    # ortografía al texto arregla también los reenvíos de las facturas viejas, que es lo que
    # uno espera; y que borrar el modelo (`template_id` es SET NULL) devuelve sus facturas al
    # texto por default, que es el único comportamiento posible cuando el texto se fue con él.
    email_subject: Mapped[str | None] = mapped_column(String(200))
    email_body: Mapped[str | None] = mapped_column(String(2000))

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
