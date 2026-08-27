import datetime
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import Concepto, CondicionIva, DocType, VoucherType
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.customer import Customer
    from factumov.models.fiscal_identity import FiscalIdentity
    from factumov.models.invoice_line import InvoiceLine
    from factumov.models.invoice_template import InvoiceTemplate


class Invoice(Base, TimestampMixin):
    """Una factura **emitida**: un hecho pasado con CAE, no un documento editable.

    Es el reverso exacto de `InvoiceTemplate`, y casi todas las decisiones de esta tabla
    salen de esa diferencia. El modelo es una intención que se ajusta cada mes; la factura es
    lo que ARCA autorizó un día determinado, y no puede cambiar nunca más — anularla es una
    nota de crédito, que FactuMov no emite.

    De ahí las tres cosas que más llaman la atención acá:

    **`voucher_type` es una columna, al revés que en el modelo.** Allá se deduce de las dos
    condiciones frente al IVA justamente para que no quede vieja: el día que un cliente se
    inscribe en IVA, sus modelos tienen que pasar de B a A solos. Acá deducirla sería el bug:
    la letra la fijó ARCA en el momento de emitir, y recalcularla mañana reescribiría una
    factura ya emitida. La misma regla ("no guardes lo que podés deducir") da resultados
    opuestos según si el dato describe una intención o un hecho.

    **Los importes se guardan.** Son derivables de las líneas, pero lo que vale no es lo que
    la fórmula dé mañana sino lo que ARCA autorizó: el CAE cubre estos números. Si algún día
    cambia un redondeo en `invoice_totals`, una factura vieja tiene que seguir diciendo lo
    mismo.

    **El emisor y el receptor están copiados.** Las FK quedan para navegar y para el scoping,
    pero el nombre, el domicilio, el documento y la condición frente al IVA se guardan acá.
    Sin la copia, que el cliente corrija su domicilio reescribiría el PDF de todas las
    facturas que ya le mandamos — y el documento y la condición frente al IVA son además
    parte de lo que ARCA autorizó, así que dejarlos apuntando a una fila editable es guardar
    algo distinto de lo que se declaró.

    **El mail del cliente es la excepción, y por el mismo criterio.** No se imprime, no viaja
    a ARCA y no es parte de nada autorizado: es a dónde entregar el PDF. Eso es una pregunta
    sobre hoy, así que se lee de la ficha del cliente (`customer_email`, una propiedad) y lo
    que se guarda acá es otra cosa: `sent_to`, la dirección a la que salió el último envío.

    No lleva `user_id`, igual que `invoice_templates` y por el mismo motivo: cuelga de
    `fiscal_identity_id`, que ya está indexado, y el scoping sale de un join.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        # El invariante que ARCA también sostiene de su lado: no hay dos comprobantes con el
        # mismo número para un CUIT, punto de venta y letra. Es el backstop del candado de
        # `crud/invoice.py`; si los dos fallaran, esto convierte una factura duplicada en un
        # error en vez de en una fila.
        UniqueConstraint(
            "fiscal_identity_id",
            "pos",
            "voucher_type",
            "number",
            name="uq_invoices_fiscal_identity_id_pos_voucher_type_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    fiscal_identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_identities.id"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    # De qué modelo salió. Nullable y `SET NULL` porque el modelo se puede borrar y la factura
    # no: es información de procedencia, no una dependencia. Sin el `SET NULL`, borrar un
    # modelo del año pasado sería imposible para siempre.
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoice_templates.id", ondelete="SET NULL"), index=True
    )

    # --- Lo que fijó la emisión ---
    voucher_type: Mapped[VoucherType] = mapped_column(Enum(VoucherType))
    pos: Mapped[int] = mapped_column(Integer)
    number: Mapped[int] = mapped_column(Integer)
    date: Mapped[datetime.date] = mapped_column(Date)
    concepto: Mapped[Concepto] = mapped_column(Enum(Concepto))
    from_date: Mapped[datetime.date | None] = mapped_column(Date)
    to_date: Mapped[datetime.date | None] = mapped_column(Date)
    due_date: Mapped[datetime.date | None] = mapped_column(Date)

    # --- Lo que devolvió ARCA ---
    # `String(14)` porque el CAE son 14 dígitos. Es texto y no entero: son ceros a la
    # izquierda que hay que imprimir tal cual, y ningún cálculo lo usa como número.
    cae: Mapped[str] = mapped_column(String(14))
    cae_expiry: Mapped[datetime.date] = mapped_column(Date)

    # --- Importes autorizados ---
    net_total: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=2))
    iva_total: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=2))
    total: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=2))

    # --- Copia del emisor, tal como salió impreso ---
    issuer_name: Mapped[str] = mapped_column(String(150))
    issuer_tax_id: Mapped[str] = mapped_column(String(11))
    issuer_condicion_iva: Mapped[CondicionIva] = mapped_column(Enum(CondicionIva))
    issuer_address: Mapped[str | None] = mapped_column(String(200))
    issuer_iibb: Mapped[str | None] = mapped_column(String(50))
    issuer_start_date: Mapped[datetime.date | None] = mapped_column(Date)

    # --- Copia del receptor ---
    customer_name: Mapped[str] = mapped_column(String(150))
    customer_doc_type: Mapped[DocType] = mapped_column(Enum(DocType))
    customer_doc_number: Mapped[str] = mapped_column(String(11))
    customer_condicion_iva: Mapped[CondicionIva] = mapped_column(Enum(CondicionIva))
    customer_address: Mapped[str | None] = mapped_column(String(200))

    # A qué dirección salió el mail la **última** vez. `None` = todavía no se mandó.
    #
    # No es una copia del mail del cliente, y ahí está la diferencia con las cuatro columnas de
    # arriba. Esas congelan un **hecho fiscal**: son lo que ARCA autorizó y lo que salió
    # impreso, así que tienen que seguir diciendo lo mismo aunque el cliente se mude. El mail
    # no se imprime, no viaja a ARCA y no es parte de nada autorizado: es a dónde entregar el
    # PDF, y "a dónde entregarlo" es una pregunta sobre hoy, no sobre el día de la emisión.
    #
    # Copiarlo al emitir producía el bug que motivó la columna: una factura emitida cuando el
    # cliente todavía no tenía mail se quedaba sin mail para siempre. El usuario cargaba la
    # dirección en la ficha, volvía a la factura y seguía viendo "este cliente no tiene email"
    # — un callejón sin salida, porque una factura emitida tampoco se puede editar.
    sent_to: Mapped[str | None] = mapped_column(String(254))

    # Cuándo salió el mail con el PDF, la **última** vez. Reenviar lo pisa: lo que la pantalla
    # necesita contestar es "¿esto ya se mandó?", y para eso la fecha más reciente es la que
    # sirve. Timestamp y no booleano, mismo criterio que `email_confirmed_at` y
    # `delegation_verified_at`: el "cuándo" es justo lo que se quiere saber.
    #
    # No es acuse de recibo. Dice que el servidor de mail lo aceptó, no que el cliente lo haya
    # recibido ni abierto — eso necesitaría un proveedor con webhooks, que es otra unidad.
    sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    fiscal_identity: Mapped["FiscalIdentity"] = relationship()
    customer: Mapped["Customer"] = relationship()
    template: Mapped["InvoiceTemplate | None"] = relationship()
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLine.position",
    )

    @property
    def customer_email(self) -> str | None:
        """A qué dirección hay que mandarle el PDF: la que el cliente tiene **ahora**.

        Deducida y no guardada, al revés que el resto de los `customer_*`. La regla del
        proyecto —"no guardes lo que podés deducir"— da resultados opuestos según si el dato
        describe un hecho pasado o algo que se va a hacer ahora, y el mail es lo segundo: el
        destinatario de un envío que todavía no ocurrió.

        Propiedad y no un campo calculado en el schema porque también la necesita el endpoint
        de envío, que trabaja con el modelo. Toca la relación, así que `crud/invoice.py` la
        trae con `joinedload`.
        """
        return self.customer.email

    @property
    def label(self) -> str:
        """Cómo se nombra el comprobante en pantalla y en el nombre del archivo.

        `B-00001-00000042`, que es la forma en que ARCA los imprime y la que el destinatario
        reconoce. Vive acá y no en la pantalla porque lo van a usar la grilla, el PDF y el
        asunto del mail, y tres copias del mismo `f-string` se desincronizan.
        """
        return f"{self.voucher_type.value}-{self.pos:05d}-{self.number:08d}"
