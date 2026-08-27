import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

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
from factumov.services import invoice_pdf, notifications
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

_MAIL_UNAVAILABLE_DETAIL = (
    "No pudimos mandar el mail. La factura está emitida igual: reintentá en unos minutos."
)


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
    no un error del servidor; el mensaje dice exactamente dónde.

    El `commit` antes del envío es el de siempre: no dejar la transacción abierta durante la
    conexión SMTP.
    """
    enforce_rate_limit(_SEND_LIMITER, str(user.id))

    if not invoice.customer_email:
        raise HTTPException(status_code=409, detail=_NO_EMAIL_DETAIL)

    # El PDF se arma antes del commit porque no toca la base y porque, si fallara, no tiene
    # sentido haber cerrado la transacción para nada.
    pdf = invoice_pdf.render_pdf(invoice)
    filename = invoice_pdf.pdf_filename(invoice)
    address = invoice.customer_email
    label = invoice.label
    issuer_name = invoice.issuer_name
    total = format_amount(invoice.total)
    db.commit()

    try:
        notifications.send_invoice_email(
            to=address,
            label=label,
            issuer_name=issuer_name,
            total=total,
            pdf=pdf,
            filename=filename,
        )
    except EmailDeliveryError as error:
        logger.exception("No se pudo mandar la factura %s a %s", label, address)
        raise HTTPException(status_code=503, detail=_MAIL_UNAVAILABLE_DETAIL) from error

    invoice_crud.mark_sent(db, invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


# No hay PATCH ni DELETE, y la ausencia es la decisión: una factura emitida no se corrige ni
# se borra. Lo que la deja sin efecto es una nota de crédito, que FactuMov no emite y que
# tampoco sería una edición de esta fila. Ver `crud/invoice.py`.
