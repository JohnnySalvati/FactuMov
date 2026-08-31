import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from factumov.enums import Balance360Status, Concepto, CondicionIva, DocType, VoucherType
from factumov.schemas.invoice_line import InvoiceLineRead


class EmitRequest(BaseModel):
    """Lo que el usuario decide al emitir, que es muy poco y a propósito.

    Todo lo demás —a quién, desde qué CUIT, qué líneas, qué punto de venta— sale del modelo
    tal como está guardado. Emitir no es otro formulario: es apretar el botón sobre un modelo
    que ya se revisó. Quien quiera cambiar un importe lo cambia en el modelo y lo guarda, que
    es justamente lo que un modelo existe para permitir.

    **`date` es lo único que se agrega al modelo y es opcional.** Su default es hoy, que es
    lo que se emite casi siempre; poder correrla existe para el papel que tiene que decir otra
    cosa —se facturó el viernes y se cargó el lunes— y ARCA la acepta dentro de una ventana de
    pocos días alrededor de hoy. Qué días son lo decide el concepto del modelo, que este
    schema no ve: lo valida `services/emission.py`, igual que pasa con las fechas de servicio.
    """

    date: datetime.date | None = None
    from_date: datetime.date | None = None
    to_date: datetime.date | None = None
    due_date: datetime.date | None = None

    @model_validator(mode="after")
    def _service_dates_go_together(self) -> "EmitRequest":
        """Las tres fechas de servicio van juntas o no va ninguna.

        Que hagan falta lo decide el concepto del modelo, que este schema no ve; lo chequea
        el router, que sí lo tiene. Lo que se puede validar acá es que no llegue un
        subconjunto: mandar solo `from_date` es un formulario a medio llenar, y dejarlo pasar
        termina en un rechazo de ARCA en vez de en un 422 que dice qué falta.
        """
        present = [self.from_date, self.to_date, self.due_date]
        if any(value is not None for value in present) and not all(
            value is not None for value in present
        ):
            raise ValueError(
                "El período del servicio necesita las tres fechas: desde, hasta y "
                "vencimiento del pago"
            )
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.to_date < self.from_date
        ):
            raise ValueError("El período del servicio termina antes de empezar")
        return self


class InvoiceRead(BaseModel):
    """Una factura emitida.

    Sale con el emisor y el receptor **copiados** y no como ids a resolver: es lo que la
    pantalla y el PDF tienen que mostrar, y es lo que se emitió aunque el cliente haya
    cambiado de domicilio después. Los ids también van, para poder navegar.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fiscal_identity_id: UUID
    customer_id: UUID
    template_id: UUID | None

    voucher_type: VoucherType
    pos: int
    number: int
    # `B-00001-00000042`. Es una propiedad del modelo y no una cuenta del cliente para que la
    # grilla, el PDF y el asunto del mail no tengan tres versiones del mismo formato.
    label: str
    date: datetime.date
    concepto: Concepto
    from_date: datetime.date | None
    to_date: datetime.date | None
    due_date: datetime.date | None

    cae: str
    cae_expiry: datetime.date

    net_total: Decimal
    iva_total: Decimal
    total: Decimal

    issuer_name: str
    issuer_tax_id: str
    issuer_condicion_iva: CondicionIva
    issuer_address: str | None
    issuer_iibb: str | None
    issuer_start_date: datetime.date | None

    customer_name: str
    customer_doc_type: DocType
    customer_doc_number: str
    customer_condicion_iva: CondicionIva
    customer_address: str | None
    # El mail **actual** del cliente, no una copia hecha al emitir: es a dónde se le mandaría
    # el PDF ahora. Cargarlo en la ficha después de emitir alcanza para poder mandar la
    # factura — ver `models/invoice.py`.
    customer_email: str | None
    # Las direcciones que reciben copia (CC) del envío, leídas de la ficha del cliente hoy —
    # como `customer_email`. La pantalla las muestra al lado del botón de mandar para que se
    # sepa a quién más le va a llegar.
    customer_cc_emails: list[str]
    # Cuándo salió el mail con el PDF por última vez, y a qué dirección. `null` = todavía no
    # se mandó.
    sent_at: datetime.datetime | None
    sent_to: str | None

    # El estado de la copia en Balance360. `null` es el caso normal de casi todas las
    # facturas —se emitieron sin la integración conectada— y la pantalla no muestra nada.
    # Solo con un estado hay indicador, y solo con `failed` hay algo que reintentar.
    balance360_status: Balance360Status | None
    balance360_invoice_id: UUID | None
    balance360_error: str | None
    balance360_synced_at: datetime.datetime | None

    created_at: datetime.datetime
    updated_at: datetime.datetime

    lines: list[InvoiceLineRead]


class InvoicePreview(BaseModel):
    """Lo que se va a emitir, calculado sin emitir nada.

    Existe para que la pantalla de confirmación diga números y no adjetivos. Emitir es
    irreversible, así que el paso previo tiene que mostrar exactamente qué comprobante sale,
    a nombre de quién y por cuánto — y esos importes los tiene que calcular el backend, que
    es el mismo que después se los va a mandar a ARCA. Que los calcule el frontend deja dos
    cuentas que pueden discrepar justo en la pantalla donde eso importa.
    """

    voucher_type: VoucherType
    pos: int
    issuer_name: str
    issuer_tax_id: str
    customer_name: str
    customer_doc_number: str
    customer_email: str | None
    net_total: Decimal
    iva_total: Decimal
    total: Decimal
    needs_service_dates: bool
    # La fecha propuesta para el comprobante —hoy— y los dos extremos que ARCA aceptaría. Van
    # calculados por el backend con la misma función que después valida la emisión: si los
    # calculara la pantalla, el campo podría ofrecer una fecha que el servidor rechaza, y el
    # borde de la ventana es exactamente donde eso pasaría.
    date: datetime.date
    min_date: datetime.date
    max_date: datetime.date
    # `None` cuando la delegación está verificada. Cuando no, el motivo por el que el botón de
    # emitir va a fallar, dicho antes de apretarlo.
    blocked_reason: str | None = Field(default=None)
