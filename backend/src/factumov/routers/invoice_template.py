import logging
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from factumov.crud import balance360_connection as balance360_connection_crud
from factumov.crud import customer as customer_crud
from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.crud import invoice as invoice_crud
from factumov.crud import invoice_template as invoice_template_crud
from factumov.dependencies import (
    CurrentUserDep,
    SessionDep,
    enforce_rate_limit,
    get_current_user,
)
from factumov.exceptions import (
    ArcaError,
    DelegationNotVerifiedError,
    DuplicateError,
    DuplicateInvoiceNumberError,
    DuplicateInvoiceTemplateNameError,
    InvalidEmissionDateError,
    PlanLimitReachedError,
    UnknownCustomerError,
    UnknownFiscalIdentityError,
    UnknownReferenceError,
)
from factumov.models.invoice import Invoice
from factumov.models.invoice_template import InvoiceTemplate
from factumov.schemas.invoice import EmitRequest, InvoicePreview, InvoiceRead
from factumov.schemas.invoice_template import (
    InvoiceTemplateCreate,
    InvoiceTemplateRead,
    InvoiceTemplateUpdate,
)
from factumov.schemas.invoice_template_draft import InvoiceTemplateDraft
from factumov.services import balance360
from factumov.services import subscription as subscription_service
from factumov.services.emission import EmissionRequest, emission_date_bounds, emit
from factumov.services.invoice_draft import build_draft
from factumov.services.invoice_parser import parse_invoice_pdf
from factumov.services.invoice_totals import LineAmounts, compute_totals
from factumov.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Emitir sale a WSAA y dos veces a WSFE, y esa cuota la fija ARCA contra el certificado de
# FactuMov, que es uno solo para todos los usuarios: un usuario en loop se la gasta a todos.
# Treinta por hora es holgado para el que factura de verdad —nadie emite treinta facturas
# seguidas a mano— y acota el daño de una pantalla que se quedó reintentando sola.
_EMIT_LIMITER = RateLimiter(limit=30, window_seconds=60 * 60)

_DELEGATION_MISSING_DETAIL = (
    "Esta identidad fiscal todavía no tiene la delegación verificada en ARCA. Entrá a "
    "Identidades, verificala, y volvé a emitir."
)

router = APIRouter(
    prefix="/invoice-templates",
    tags=["invoice_templates"],
    dependencies=[Depends(get_current_user)],
)


def get_invoice_template_or_404(
    invoice_template_id: uuid.UUID, db: SessionDep, user: CurrentUserDep
) -> InvoiceTemplate:
    """404 sobre el modelo de otro usuario — ver `routers/customer.py`."""
    invoice_template = invoice_template_crud.get_by_id(db, invoice_template_id, user.id)
    if invoice_template is None:
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    return invoice_template


InvoiceTemplateDep = Annotated[InvoiceTemplate, Depends(get_invoice_template_or_404)]


def _check_email_text_allowed(
    db: Session,
    user_id: uuid.UUID,
    data: InvoiceTemplateCreate | InvoiceTemplateUpdate,
) -> None:
    """402 si el body trae un texto de mail y el plan no lo permite.

    **Solo mira los textos que llegan con contenido.** Un body que no los trae, o que los trae
    en `null` —lo que manda la pantalla cuando el campo quedó vacío— no pide nada: el primero
    no toca el mail y el segundo lo devuelve al texto por default, que es justamente lo que un
    Free puede tener. Sin esa distinción, un ex-Pro no podría guardar **ningún** cambio en un
    modelo cuyo mail personalizó, porque el PATCH del formulario manda el objeto entero y el
    texto vacío contaría como un intento de personalizar.

    Va en el router y no en el schema por lo mismo que `check_can_emit`: es una condición de la
    cuenta y no del body. El mismo JSON es válido o no según quién lo mande, y eso no es algo
    que un schema pueda decidir.
    """
    if data.email_subject is None and data.email_body is None:
        return
    try:
        subscription_service.check_can_customize_email(db, user_id)
    except PlanLimitReachedError as error:
        raise HTTPException(status_code=402, detail=str(error))


@router.get("", response_model=list[InvoiceTemplateRead])
def list_invoice_templates(db: SessionDep, user: CurrentUserDep) -> list[InvoiceTemplate]:
    return invoice_template_crud.get_all(db, user.id)


@router.post("", response_model=InvoiceTemplateRead, status_code=201)
def create_invoice_template(
    data: InvoiceTemplateCreate, db: SessionDep, user: CurrentUserDep
) -> InvoiceTemplate:
    _check_email_text_allowed(db, user.id, data)
    try:
        invoice_template = invoice_template_crud.create(db, data, user.id)
    except UnknownCustomerError:
        raise HTTPException(status_code=422, detail="Cliente desconocido")
    except UnknownFiscalIdentityError:
        raise HTTPException(status_code=422, detail="Identidad fiscal desconocida")
    except UnknownReferenceError:
        raise HTTPException(status_code=422, detail="Referencia desconocida")
    except DuplicateInvoiceTemplateNameError:
        raise HTTPException(status_code=409, detail="Nombre duplicado")
    except DuplicateError:
        raise HTTPException(status_code=409, detail="Duplicado")
    return invoice_template


@router.post("/import", response_model=InvoiceTemplateDraft)
def import_invoice_template(
    file: UploadFile,
    db: SessionDep,
    user: CurrentUserDep,
) -> InvoiceTemplateDraft:
    file_bytes = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo excede el límite de 10 MB")
    if file_bytes[:5] != b"%PDF-":
        raise HTTPException(status_code=415, detail="El formato no coincide con PDF")
    parsed_invoice = parse_invoice_pdf(file_bytes)

    customer = None
    if (
        parsed_invoice.customer_doc_type is not None
        and parsed_invoice.customer_doc_number is not None
    ):
        # Los dos lookups van scopeados. Sin eso, importar un PDF devolvía el
        # `customer_id` del cliente de otro usuario cuando el documento coincidía, y
        # confirmarlo hubiera creado un modelo apuntando a una fila ajena — además de
        # delatar que ese cliente ya estaba cargado por alguien.
        customer = customer_crud.get_by_doc(
            db, parsed_invoice.customer_doc_type, parsed_invoice.customer_doc_number, user.id
        )
    fiscal_identity = (
        fiscal_identity_crud.get_by_tax_id(db, parsed_invoice.issuer_cuit, user.id)
        if parsed_invoice.issuer_cuit
        else None
    )
    return build_draft(
        parsed_invoice=parsed_invoice,
        customer_id=customer.id if customer else None,
        fiscal_identity_id=fiscal_identity.id if fiscal_identity else None,
    )


@router.get("/{invoice_template_id}", response_model=InvoiceTemplateRead)
def get_invoice_template(invoice_template: InvoiceTemplateDep) -> InvoiceTemplate:
    return invoice_template


@router.patch("/{invoice_template_id}", response_model=InvoiceTemplateRead)
def update_invoice_template(
    data: InvoiceTemplateUpdate,
    invoice_template: InvoiceTemplateDep,
    db: SessionDep,
    user: CurrentUserDep,
) -> InvoiceTemplate:
    _check_email_text_allowed(db, user.id, data)
    try:
        invoice_template = invoice_template_crud.update(db, invoice_template, data, user.id)
    except UnknownCustomerError:
        raise HTTPException(status_code=422, detail="Cliente desconocido")
    except UnknownFiscalIdentityError:
        raise HTTPException(status_code=422, detail="Identidad fiscal desconocida")
    except UnknownReferenceError:
        raise HTTPException(status_code=422, detail="Referencia desconocida")
    except DuplicateInvoiceTemplateNameError:
        raise HTTPException(status_code=409, detail="Nombre duplicado")
    except DuplicateError:
        raise HTTPException(status_code=409, detail="Duplicado")
    return invoice_template


@router.delete("/{invoice_template_id}", status_code=204)
def delete_invoice_template(invoice_template: InvoiceTemplateDep, db: SessionDep) -> None:
    invoice_template_crud.delete(db, invoice_template)


@router.get("/{invoice_template_id}/preview", response_model=InvoicePreview)
def preview_emission(
    invoice_template: InvoiceTemplateDep, db: SessionDep, user: CurrentUserDep
) -> InvoicePreview:
    """Qué comprobante saldría si se emitiera este modelo ahora. **No emite nada.**

    Es el insumo de la pantalla de confirmación, y existe porque emitir es irreversible: el
    paso previo tiene que decir la letra, el destinatario y el importe exacto, no "¿confirmás?".

    Los importes los calcula el backend con la misma función que después se los manda a ARCA.
    El frontend ya sabe hacer esa cuenta —la muestra en el editor mientras se tipea— pero
    dejarla como única fuente en esta pantalla sería tener dos cuentas capaces de discrepar
    justo donde el número deja de ser una estimación y pasa a ser lo que se declara.

    Es GET porque de verdad no escribe nada: acá un prefetch o un reintento son inofensivos,
    que es exactamente lo contrario de lo que pasa con `/emit`.
    """
    totals = compute_totals(
        invoice_template.voucher_type,
        [
            LineAmounts(
                quantity=line.quantity,
                unit_price=line.unit_price,
                iva_aliquot=line.iva_aliquot,
            )
            for line in invoice_template.lines
        ],
    )
    # Dos motivos posibles de bloqueo y un solo campo, porque la pantalla muestra un aviso y
    # no una lista: el que gana es el de la delegación, que es condición para que ese CUIT
    # pueda emitir aunque el plan sobre. El del plan aparece cuando la delegación ya está —
    # o sea cuando es lo único que falta.
    if invoice_template.fiscal_identity.delegation_verified_at is None:
        blocked = _DELEGATION_MISSING_DETAIL
    elif not subscription_service.entitlements(db, user.id).can_emit:
        blocked = subscription_service.invoice_limit_detail()
    else:
        blocked = None
    # La ventana de fechas sale de la misma función que después valida la emisión, para que el
    # campo de la pantalla no pueda ofrecer una fecha que el servidor rechaza.
    today = date.today()
    min_date, max_date = emission_date_bounds(invoice_template.concepto, today)
    return InvoicePreview(
        voucher_type=invoice_template.voucher_type,
        pos=invoice_template.pos,
        issuer_name=invoice_template.fiscal_identity.name,
        issuer_tax_id=invoice_template.fiscal_identity.tax_id,
        customer_name=invoice_template.customer.name,
        customer_doc_number=invoice_template.customer.doc_number,
        customer_email=invoice_template.customer.email,
        net_total=totals.net,
        iva_total=totals.iva,
        total=totals.total,
        needs_service_dates=invoice_template.concepto.needs_service_dates,
        date=today,
        min_date=min_date,
        max_date=max_date,
        blocked_reason=blocked,
    )


@router.post("/{invoice_template_id}/emit", response_model=InvoiceRead, status_code=201)
def emit_invoice(
    data: EmitRequest,
    invoice_template: InvoiceTemplateDep,
    background_tasks: BackgroundTasks,
    db: SessionDep,
    user: CurrentUserDep,
) -> Invoice:
    """Emite el modelo: le pide el CAE a ARCA y guarda la factura. **Es irreversible.**

    Con `ARCA_ENV=prod`, cuando este endpoint contesta 201 hay un comprobante con validez
    legal a nombre de un CUIT real, y no existe forma de deshacerlo desde acá: se anula con
    una nota de crédito, que FactuMov no emite. Todo lo demás de este endpoint sale de eso.

    **201 y no 200**, al revés que `/import`: acá sí se crea un recurso, y es el único de los
    dos que deja algo escrito. La factura sale entera en el body para que la pantalla muestre
    el número y el CAE sin un segundo request.

    **La transacción se sostiene abierta durante la llamada a ARCA** y el commit va al final,
    contra la convención del resto del proyecto. El motivo está en `services/emission.py`: lo
    que hay que serializar es la secuencia entera —último número, CAE, insert— y un candado
    que se suelte en el medio no serializa nada.

    Los errores que pueden llegar tienen remedios distintos y por eso status distintos:
    **402** si el plan Free ya gastó su cupo del mes (pasarse a Pro, o esperar al 1°),
    **409** si falta la delegación (el usuario tiene que ir a ARCA), **409** si el número ya
    estaba tomado (una carrera que perdió: reintentar sirve), **422** si la fecha del
    comprobante está fuera de lo que ARCA acepta (cambiarla), y **502** si ARCA no contestó o
    rechazó el comprobante. El detalle de ARCA no se propaga, por lo mismo que en
    `verify-delegation`: no le dice nada al usuario y filtra cómo estamos armados. Queda en
    el log, que acá importa más que en ningún otro lado.
    """
    enforce_rate_limit(_EMIT_LIMITER, str(user.id))

    # El cupo se chequea **antes** de mirar las fechas y mucho antes de salir a ARCA: es lo
    # único de este endpoint que puede decir que no sin gastar cuota del certificado, que es
    # una sola para todos los usuarios. El `preview` ya lo anunció en `blocked_reason`, así que
    # llegar acá con el cupo lleno significa que alguien se saltó la pantalla — o que la gastó
    # en otra pestaña mientras esta estaba abierta, que es el caso real que este chequeo ataja.
    try:
        subscription_service.check_can_emit(db, user.id)
    except PlanLimitReachedError as error:
        raise HTTPException(status_code=402, detail=str(error))

    if invoice_template.concepto.needs_service_dates and data.from_date is None:
        # El schema ya garantiza que las tres vengan juntas o ninguna; lo que falta chequear
        # es si hacían falta, y eso lo dice el concepto del modelo, que el schema no ve.
        raise HTTPException(
            status_code=422,
            detail="Un modelo de servicios necesita el período facturado y el vencimiento "
            "del pago.",
        )

    try:
        invoice = emit(
            db,
            invoice_template,
            EmissionRequest(
                date=data.date,
                from_date=data.from_date,
                to_date=data.to_date,
                due_date=data.due_date,
            ),
        )
    except DelegationNotVerifiedError:
        raise HTTPException(status_code=409, detail=_DELEGATION_MISSING_DETAIL)
    except InvalidEmissionDateError as error:
        # 422 y no 502: es un dato del request que el usuario puede corregir, y el mensaje ya
        # dice qué fechas sí entran. Es la única excepción de ARCA cuyo detalle sí se propaga,
        # porque es sobre lo que él eligió y no sobre cómo estamos armados.
        raise HTTPException(status_code=422, detail=str(error))
    except DuplicateInvoiceNumberError:
        # ARCA ya autorizó un comprobante con ese número y nosotros no lo teníamos guardado.
        # El log de `emission.emit` tiene el CAE: es la única forma de recuperarlo.
        logger.exception(
            "Número de comprobante duplicado al guardar una factura del modelo %s",
            invoice_template.id,
        )
        raise HTTPException(
            status_code=409,
            detail="Ese número de comprobante ya estaba tomado. Probá de nuevo.",
        )
    except ArcaError:
        # `logger.exception` y no un log a secas: el detalle no puede ir en la respuesta, así
        # que sin esta línea un 502 acá es indistinguible de otro — y este es el 502 más caro
        # de la app, porque puede haber quedado un comprobante autorizado del otro lado.
        logger.exception("Falló la emisión del modelo %s", invoice_template.id)
        raise HTTPException(
            status_code=502,
            detail="ARCA no pudo autorizar el comprobante. Si el problema sigue, revisá en "
            "el sitio de ARCA si la factura quedó emitida antes de volver a intentar.",
        )

    # El registro en Balance360 va **después** de la emisión y desacoplado de ella. Cuando
    # llegamos acá el CAE ya existe y es irreversible: hacer que la respuesta dependa de que
    # la otra app conteste convertiría un Balance360 caído en una emisión sin respuesta, con
    # un comprobante autorizado del que el usuario no se entera. La factura sale en `pending`
    # y la copia ocurre en un `BackgroundTask`, que corre después de mandar el 201.
    connection = balance360_connection_crud.get_for_user(db, user.id)
    should_register = connection is not None and connection.auto_register
    if should_register:
        invoice_crud.mark_balance360_pending(db, invoice)

    db.commit()
    db.refresh(invoice)

    if should_register:
        # Ids y no el objeto: la sesión de este request se cierra antes de que la tarea corra.
        background_tasks.add_task(balance360.register_in_background, invoice.id, user.id)

    return invoice
