"""Emitir: tomar un modelo, pedirle el CAE a ARCA y guardar la factura que salió.

Es el único lugar del proyecto que hace algo **irreversible hacia afuera**. Contra
`ARCA_ENV=prod`, cuando esta función vuelve hay un comprobante con validez legal registrado a
nombre de un CUIT real, y no existe ningún camino de vuelta: se deja sin efecto con una nota
de crédito, que FactuMov no emite. Todo lo que sigue está ordenado alrededor de eso.

Vive en `services/` y no en el router porque junta tres cosas que ninguna capa tiene solas
—el modelo guardado, el cálculo de importes y la respuesta de ARCA— y porque necesita la
sesión para el candado. Que un servicio importe `crud/` ya está establecido: lo hace
`services/arca.py` con `arca_tickets`.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from factumov.crud import invoice as invoice_crud
from factumov.exceptions import DelegationNotVerifiedError
from factumov.models.invoice import Invoice
from factumov.models.invoice_line import InvoiceLine
from factumov.models.invoice_template import InvoiceTemplate
from factumov.services import wsfe
from factumov.services.invoice_totals import InvoiceTotals, LineAmounts, compute_totals

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmissionRequest:
    """Lo poco que el usuario decide en el momento de emitir.

    **No incluye la fecha del comprobante.** Emitir es un acto de hoy: la fecha es el día en
    que se aprieta el botón. Dejarla elegir agrega un campo a la pantalla que se usa cien
    veces por semana y una forma nueva de que ARCA rechace el comprobante —acepta la fecha
    dentro de una ventana de pocos días alrededor de hoy—, a cambio de un caso que el período
    del servicio ya cubre mejor: facturar el 3 el mes que pasó es `from_date`/`to_date`, no
    una fecha de emisión retroactiva.

    Las tres fechas de servicio son obligatorias cuando el concepto no es "productos", y eso
    lo garantiza el schema del endpoint antes de llegar acá.
    """

    from_date: date | None = None
    to_date: date | None = None
    due_date: date | None = None


def _snapshot(
    template: InvoiceTemplate, request: EmissionRequest, today: date, totals: InvoiceTotals
) -> Invoice:
    """La factura con todo lo que se sabe **antes** de hablar con ARCA.

    Se arma entera acá, sin número ni CAE, por una razón práctica: así el objeto que se
    guarda después es el mismo que se declaró, y no hay forma de que lo que se le mandó a
    ARCA y lo que quedó en la base diverjan por un campo que alguien se olvidó de copiar.

    Los totales llegan **calculados de afuera** y no se recalculan acá, que es la otra mitad
    de lo mismo: los importes guardados tienen que ser bit por bit los que viajaron en el
    request del CAE. Calcularlos dos veces daría hoy el mismo número y dejaría abierta la
    puerta a que un cambio de redondeo los separe.

    Los datos del emisor y del receptor se **copian**, no se referencian — ver el docstring de
    `models/invoice.py`.
    """
    issuer = template.fiscal_identity
    customer = template.customer
    voucher_type = template.voucher_type

    return Invoice(
        fiscal_identity_id=issuer.id,
        customer_id=customer.id,
        template_id=template.id,
        voucher_type=voucher_type,
        pos=template.pos,
        date=today,
        concepto=template.concepto,
        from_date=request.from_date,
        to_date=request.to_date,
        due_date=request.due_date,
        net_total=totals.net,
        iva_total=totals.iva,
        total=totals.total,
        issuer_name=issuer.name,
        issuer_tax_id=issuer.tax_id,
        issuer_condicion_iva=issuer.condicion_iva,
        issuer_address=issuer.address,
        issuer_iibb=issuer.iibb,
        issuer_start_date=issuer.start_date,
        customer_name=customer.name,
        customer_doc_type=customer.doc_type,
        customer_doc_number=customer.doc_number,
        customer_condicion_iva=customer.condicion_iva,
        customer_address=customer.address,
        customer_email=customer.email,
        lines=[
            InvoiceLine(
                position=line.position,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                iva_aliquot=line.iva_aliquot,
            )
            for line in template.lines
        ],
    )


def emit(db: Session, template: InvoiceTemplate, request: EmissionRequest) -> Invoice:
    """Emite el modelo y devuelve la factura guardada.

    **La transacción queda abierta durante la llamada a ARCA**, contra lo que hace el resto
    del proyecto —el registro commitea antes de mandar el mail, la verificación de delegación
    commitea antes de la llamada SOAP— y acá es al revés a propósito. Lo que hay que proteger
    es la secuencia entera: preguntar el último número, pedir el CAE para el siguiente y
    guardar el resultado. Un candado que se suelte en el medio no protege nada, y dos
    emisiones simultáneas del mismo punto de venta tomarían el mismo número. El precio es una
    conexión y una transacción tomadas por unos segundos, y se paga en una operación que un
    usuario hace unas pocas veces por mes.

    **El CAE se loguea apenas ARCA contesta, antes de tocar la base.** Es la red de seguridad
    del único momento verdaderamente peligroso de la app: entre que ARCA autoriza y que el
    commit termina, la factura existe para el fisco y no existe para nosotros. Si el insert o
    el commit fallaran, ese renglón de log es lo único que permite reconstruir a mano un
    comprobante que ya tiene validez legal.
    """
    if template.fiscal_identity.delegation_verified_at is None:
        raise DelegationNotVerifiedError(str(template.fiscal_identity_id))

    totals = compute_totals(
        template.voucher_type,
        [
            LineAmounts(
                quantity=line.quantity,
                unit_price=line.unit_price,
                iva_aliquot=line.iva_aliquot,
            )
            for line in template.lines
        ],
    )
    invoice = _snapshot(template, request, today=date.today(), totals=totals)

    # El candado se toma antes de preguntarle el número a ARCA y se suelta recién en el
    # commit del router. Ver `crud/invoice.lock_numbering`.
    invoice_crud.lock_numbering(
        db,
        invoice_crud.numbering_lock_key(
            invoice.fiscal_identity_id, invoice.pos, invoice.voucher_type.value
        ),
    )

    authorization = wsfe.authorize_invoice(
        wsfe.VoucherRequest(
            issuer_tax_id=invoice.issuer_tax_id,
            pos=invoice.pos,
            voucher_type=invoice.voucher_type,
            date=invoice.date,
            concepto=invoice.concepto,
            customer_doc_type=invoice.customer_doc_type,
            customer_doc_number=invoice.customer_doc_number,
            customer_condicion_iva=invoice.customer_condicion_iva.value,
            totals=totals,
            from_date=invoice.from_date,
            to_date=invoice.to_date,
            due_date=invoice.due_date,
        )
    )

    logger.info(
        "ARCA autorizó %s-%05d-%08d del CUIT %s por %s — CAE %s (vence %s). "
        "Si lo que sigue falla, este comprobante existe igual y hay que cargarlo a mano.",
        invoice.voucher_type.value,
        invoice.pos,
        authorization.number,
        invoice.issuer_tax_id,
        invoice.total,
        authorization.cae,
        authorization.cae_expiry,
    )

    invoice.number = authorization.number
    invoice.cae = authorization.cae
    invoice.cae_expiry = authorization.cae_expiry
    return invoice_crud.create(db, invoice)
