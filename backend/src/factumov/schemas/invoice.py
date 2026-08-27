import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from factumov.enums import Concepto, CondicionIva, DocType, VoucherType
from factumov.schemas.invoice_line import InvoiceLineRead


class EmitRequest(BaseModel):
    """Lo que el usuario decide al emitir, que es muy poco y a propósito.

    Todo lo demás —a quién, desde qué CUIT, qué líneas, qué punto de venta— sale del modelo
    tal como está guardado. Emitir no es otro formulario: es apretar el botón sobre un modelo
    que ya se revisó. Quien quiera cambiar un importe lo cambia en el modelo y lo guarda, que
    es justamente lo que un modelo existe para permitir.

    **Sin `date`.** La fecha del comprobante es el día de la emisión — ver
    `services/emission.EmissionRequest`.
    """

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
    customer_email: str | None

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
    # `None` cuando la delegación está verificada. Cuando no, el motivo por el que el botón de
    # emitir va a fallar, dicho antes de apretarlo.
    blocked_reason: str | None = Field(default=None)
