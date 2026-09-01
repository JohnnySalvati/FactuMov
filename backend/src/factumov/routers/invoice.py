import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from factumov.crud import balance360_connection as balance360_connection_crud
from factumov.crud import invoice as invoice_crud
from factumov.dependencies import (
    CurrentUserDep,
    SessionDep,
    enforce_rate_limit,
    get_current_user,
)
from factumov.models.invoice import Invoice
from factumov.schemas.invoice import InvoiceRead

# Importados como módulo y no por nombre, para que un test pueda parchearlos en un solo lugar
# — el mismo criterio que `MAX_UPLOAD_BYTES` y `notifications.py`.
from factumov.services import balance360, invoice_pdf, notifications
from factumov.services import subscription as subscription_service
from factumov.services.email import EmailDeliveryError
from factumov.services.invoice_pdf import format_amount
from factumov.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/invoices",
    tags=["invoices"],
    dependencies=[Depends(get_current_user)],
)

# Por usuario y no por IP: el endpoint está autenticado, así que hay una clave mejor que la
# dirección. Lo que acota es el reenvío repetido a la casilla de un cliente, que es la única
# forma que tiene esta app de molestar a un tercero.
_SEND_LIMITER = RateLimiter(limit=60, window_seconds=60 * 60)

_NO_EMAIL_DETAIL = "Este cliente no tiene email cargado. Agregáselo en su ficha y volvé a intentar."

# Un reintento por factura pega una vez a Balance360. Es más generoso que el envío de mail
# porque no molesta a ningún tercero: lo único que gasta es una conexión contra una app propia.
_REGISTER_LIMITER = RateLimiter(limit=120, window_seconds=60 * 60)

_MAIL_UNAVAILABLE_DETAIL = (
    "No pudimos mandar el mail. La factura está emitida igual: reintentá en unos minutos."
)


def _custom_email_text(
    db: SessionDep, invoice: Invoice, user_id: uuid.UUID
) -> tuple[str | None, str | None]:
    """El asunto y el cuerpo que el usuario le escribió al modelo del que salió esta factura.

    `(None, None)` es la respuesta normal y significa "mandá el texto de FactuMov". Hay tres
    caminos que llegan ahí y ninguno es un error:

    - **El modelo no tiene texto propio**, que es el caso de casi todos.
    - **El modelo no está**: `invoices.template_id` es `SET NULL`, así que borrar el modelo del
      año pasado deja a sus facturas sin procedencia. El texto se fue con él y no hay dónde
      buscarlo — es el precio de leerlo en vivo en vez de copiarlo al emitir, y es el mismo
      precio que ya se paga con el mail del cliente.
    - **La cuenta ya no es Pro.** El texto sigue guardado y vuelve solo si vuelve el plan; lo
      que sale mientras tanto es el default, que dice lo mismo con otras palabras. Ver
      `Entitlements.custom_email_enabled`.

    El orden de los dos chequeos importa por lo que cuesta el segundo: `entitlements` son dos
    `COUNT`, y preguntarlos antes de mirar el modelo se los cobraría a todos los envíos para
    contestar sobre un texto que en la enorme mayoría no existe.

    Se llama **antes del commit** por lo mismo que el PDF y los importes: después, la sesión
    expira los objetos y tocar `invoice.template` sería una query nueva sobre una transacción
    que se cerró a propósito.
    """
    template = invoice.template
    if template is None or (template.email_subject is None and template.email_body is None):
        return None, None
    if not subscription_service.entitlements(db, user_id).custom_email_enabled:
        return None, None
    return template.email_subject, template.email_body


def get_invoice_or_404(invoice_id: uuid.UUID, db: SessionDep, user: CurrentUserDep) -> Invoice:
    """404 sobre la factura de otro usuario — ver `routers/customer.py`."""
    invoice = invoice_crud.get_by_id(db, invoice_id, user.id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return invoice


InvoiceDep = Annotated[Invoice, Depends(get_invoice_or_404)]


@router.get("", response_model=list[InvoiceRead])
def list_invoices(db: SessionDep, user: CurrentUserDep) -> list[Invoice]:
    return invoice_crud.get_all(db, user.id)


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice: InvoiceDep) -> Invoice:
    return invoice


@router.get("/{invoice_id}/pdf")
def get_invoice_pdf(invoice: InvoiceDep) -> Response:
    """La representación impresa del comprobante.

    Se genera al vuelo en cada pedido en vez de guardarse al emitir. Es determinístico —sale
    de columnas que no cambian nunca— así que guardarlo sería una copia más de un dato que ya
    está, con su propio almacenamiento y su propia forma de quedar desactualizada frente a una
    corrección del template. Cuesta unas décimas de segundo y se pide pocas veces.

    `inline` y no `attachment`: en el celular abre el visor del navegador, que es lo que el
    usuario quiere para mirarlo antes de mandarlo. Bajarlo sigue estando a un toque.
    """
    pdf = invoice_pdf.render_pdf(invoice)
    filename = invoice_pdf.pdf_filename(invoice)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{invoice_id}/send", response_model=InvoiceRead)
def send_invoice(invoice: InvoiceDep, db: SessionDep, user: CurrentUserDep) -> Invoice:
    """Le manda la factura al cliente, con el PDF adjunto.

    **Se puede repetir.** Reenviar es una operación legítima y frecuente —el cliente dice que
    no le llegó— así que no hay guarda contra el segundo envío: `sent_at` se pisa y ya. Es lo
    contrario de `/emit`, donde repetir crea un comprobante nuevo, y por eso aquella pantalla
    tiene una confirmación y esta no.

    **503 si el mail no sale**, con un texto que aclara que la factura está emitida igual: el
    error es del envío y no de la emisión, y confundirlos haría que alguien vuelva a emitir.
    Es la misma política que el registro — el mail que es el producto del request falla
    ruidosamente. Ver CLAUDE.md → *El fallo de SMTP se ve*.

    **409 si el cliente no tiene email.** Es un dato que falta y que el usuario puede cargar,
    no un error del servidor; el mensaje dice exactamente dónde. Y cargarlo alcanza: la
    dirección se lee de la ficha del cliente en cada envío, así que volver a esta factura
    después de completarla la deja mandable.

    **El texto del mail también sale del modelo en vivo**, y es Pro. Si el modelo del que
    salió esta factura tiene asunto o cuerpo propios y la cuenta es Pro, se manda ese texto; si
    no, el de FactuMov. Se lee al enviar y no se copia al emitir por el mismo motivo que el
    mail del cliente: qué decirle al destinatario es una pregunta sobre el envío que se está
    por hacer, no un hecho que ARCA haya autorizado. La consecuencia es la que uno espera —
    corregirle una falta de ortografía al modelo arregla también los reenvíos de lo ya emitido.

    **El CC sale de la ficha del cliente**, también en vivo: las direcciones que cargó para
    que reciban copia (el contador, el gestor). No hay 409 si están vacías —el CC es
    opcional— y `sent_to` sigue registrando solo el destinatario principal: a quién se copió
    es una pregunta sobre hoy, no un hecho del envío que valga la pena congelar.

    El `commit` antes del envío es el de siempre: no dejar la transacción abierta durante la
    conexión SMTP.
    """
    enforce_rate_limit(_SEND_LIMITER, str(user.id))

    # La dirección sale de la ficha **actual** del cliente y no de una copia hecha al emitir.
    # Con la copia, una factura emitida antes de que el cliente tuviera mail se quedaba sin
    # mail para siempre: cargarlo en la ficha no cambiaba nada y la factura tampoco se puede
    # editar. Ver `models/invoice.py`.
    address = invoice.customer_email
    if not address:
        raise HTTPException(status_code=409, detail=_NO_EMAIL_DETAIL)

    # El schema del cliente ya saca del CC al destinatario principal, pero el mail pudo
    # cambiar después de cargar el CC: filtrar acá también deja al To fuera de las copias en
    # ese caso, sin que a nadie le llegue el mail dos veces.
    cc = [other for other in invoice.customer_cc_emails if other != address]

    # El PDF se arma antes del commit porque no toca la base y porque, si fallara, no tiene
    # sentido haber cerrado la transacción para nada.
    pdf = invoice_pdf.render_pdf(invoice)
    filename = invoice_pdf.pdf_filename(invoice)
    label = invoice.label
    issuer_name = invoice.issuer_name
    total = format_amount(invoice.total)
    subject, body = _custom_email_text(db, invoice, user.id)
    db.commit()

    try:
        notifications.send_invoice_email(
            to=address,
            label=label,
            issuer_name=issuer_name,
            total=total,
            pdf=pdf,
            filename=filename,
            cc=cc,
            subject=subject,
            body=body,
        )
    except EmailDeliveryError as error:
        logger.exception("No se pudo mandar la factura %s a %s", label, address)
        raise HTTPException(status_code=503, detail=_MAIL_UNAVAILABLE_DETAIL) from error

    invoice_crud.mark_sent(db, invoice, address)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/register", response_model=InvoiceRead)
def register_invoice(invoice: InvoiceDep, db: SessionDep, user: CurrentUserDep) -> Invoice:
    """Reintenta copiar **esta** factura a Balance360.

    Es el botón que aparece al lado del error: el usuario cargó el CUIT que faltaba del otro
    lado, o le reemitieron el token, y lo que quiere es probar esa factura y ver si ahora sí.

    **Se puede repetir sin miedo**, y eso no lo garantiza este endpoint sino la idempotencia
    del otro lado: el id de esta factura viaja como clave, así que un segundo registro devuelve
    el comprobante que ya estaba en vez de duplicarlo. Es lo que permite que el reintento no
    tenga confirmación, al revés de `/emit`.

    **Siempre 200**, ande o no ande. El resultado del intento no es el resultado del request:
    la factura vuelve con su estado y su mensaje de error adentro, que es lo que la pantalla
    tiene que mostrar igual. Un 502 obligaría a la SPA a leer el motivo de dos lugares
    distintos según cómo haya salido.

    Sincrónico y no en background, al revés que el disparo de la emisión: acá el registro *es*
    lo que se pidió, y hay alguien esperando para verlo.
    """
    enforce_rate_limit(_REGISTER_LIMITER, str(user.id))

    if balance360_connection_crud.get_for_user(db, user.id) is None:
        raise HTTPException(
            status_code=409,
            detail="No hay ninguna cuenta de Balance360 conectada. Conectala desde Ajustes.",
        )

    balance360.register(db, invoice)
    db.refresh(invoice)
    return invoice


# No hay PATCH ni DELETE, y la ausencia es la decisión: una factura emitida no se corrige ni
# se borra. Lo que la deja sin efecto es una nota de crédito, que FactuMov no emite y que
# tampoco sería una edición de esta fila. Ver `crud/invoice.py`.
