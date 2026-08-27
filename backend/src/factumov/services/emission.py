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

import datetime
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from factumov.crud import invoice as invoice_crud
from factumov.enums import Concepto
from factumov.exceptions import DelegationNotVerifiedError, InvalidEmissionDateError
from factumov.models.invoice import Invoice
from factumov.models.invoice_line import InvoiceLine
from factumov.models.invoice_template import InvoiceTemplate
from factumov.services import wsfe
from factumov.services.invoice_totals import InvoiceTotals, LineAmounts, compute_totals

logger = logging.getLogger(__name__)


# Cuántos días corridos hacia atrás y hacia adelante de hoy acepta ARCA como fecha del
# comprobante. Son dos números y no uno porque la ventana la fija el concepto: 5 días para
# productos y 10 para servicios (y para "productos y servicios", que ARCA cuenta como
# servicios). Emitir fuera de esa ventana es un rechazo de WSFE, no una advertencia.
_PRODUCTS_WINDOW_DAYS = 5
_SERVICES_WINDOW_DAYS = 10


def emission_date_bounds(
    concepto: Concepto, today: datetime.date
) -> tuple[datetime.date, datetime.date]:
    """La primera y la última fecha que ARCA aceptaría hoy para un comprobante de ese concepto.

    Vive acá y no en `wsfe.py` porque no es traducción a SOAP sino una regla sobre qué se
    puede emitir, y porque la necesitan dos lugares que no se hablan: la vista previa —para
    ponerle `min` y `max` al campo de fecha, o sea para que la pantalla no ofrezca una fecha
    que va a fallar— y `emit`, que es donde la regla se hace cumplir. Que la pantalla y el
    servidor la calculen con la misma función es lo que evita que discrepen justo en el borde.

    Es la mitad de la validación de fecha, no toda: el otro límite es la fecha del último
    comprobante autorizado de la serie, que solo ARCA conoce y que chequea `wsfe.py`.
    """
    days = _SERVICES_WINDOW_DAYS if concepto.needs_service_dates else _PRODUCTS_WINDOW_DAYS
    return today - datetime.timedelta(days=days), today + datetime.timedelta(days=days)


@dataclass(frozen=True)
class EmissionRequest:
    """Lo poco que el usuario decide en el momento de emitir.

    **La fecha es opcional y su default es hoy**, que es lo que se emite casi siempre: la
    factura se hace el día que se hace. Poder correrla existe para los pocos casos en los que
    el papel tiene que decir otra cosa —se facturó el viernes y se cargó el lunes, o el
    cliente pide la factura fechada el último día del mes— y ARCA lo admite dentro de una
    ventana de pocos días alrededor de hoy: ver `emission_date_bounds`.

    No cubre el caso de facturar en marzo un servicio de febrero, y no tiene que cubrirlo:
    eso es `from_date`/`to_date`, el período del servicio, que no tiene ventana ninguna.

    Las tres fechas de servicio son obligatorias cuando el concepto no es "productos", y eso
    lo garantiza el schema del endpoint antes de llegar acá.
    """

    date: datetime.date | None = None
    from_date: datetime.date | None = None
    to_date: datetime.date | None = None
    due_date: datetime.date | None = None


def _snapshot(
    template: InvoiceTemplate,
    request: EmissionRequest,
    today: datetime.date,
    totals: InvoiceTotals,
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
        # El mail del cliente **no** se copia: no se imprime, no viaja a ARCA y no es parte de
        # nada autorizado. `Invoice.customer_email` lo lee de la ficha, y lo que esta tabla
        # guarda es `sent_to`, la dirección a la que salió el envío — ver `models/invoice.py`.
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

    **La fecha se resuelve y se valida antes de salir a la red**, junto con la delegación y
    por el mismo motivo: son las dos cosas que hacen fallar la emisión y que se pueden saber
    sin preguntarle nada a ARCA. Un rechazo de WSFE por una fecha fuera de ventana llega como
    un código que el usuario no puede leer, y llega después de haber pedido un CAE.
    """
    if template.fiscal_identity.delegation_verified_at is None:
        raise DelegationNotVerifiedError(str(template.fiscal_identity_id))

    emission_date = request.date or datetime.date.today()
    first, last = emission_date_bounds(template.concepto, datetime.date.today())
    if not first <= emission_date <= last:
        raise InvalidEmissionDateError(
            "ARCA solo acepta la fecha del comprobante entre el "
            f"{first.strftime('%d/%m/%Y')} y el {last.strftime('%d/%m/%Y')}."
        )

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
    invoice = _snapshot(template, request, today=emission_date, totals=totals)

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
