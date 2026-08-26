import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from factumov.crud import customer as customer_crud
from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.crud import invoice_template as invoice_template_crud
from factumov.dependencies import CurrentUserDep, SessionDep, get_current_user
from factumov.exceptions import (
    DuplicateError,
    DuplicateInvoiceTemplateNameError,
    UnknownCustomerError,
    UnknownFiscalIdentityError,
    UnknownReferenceError,
)
from factumov.models.invoice_template import InvoiceTemplate
from factumov.schemas.invoice_template import (
    InvoiceTemplateCreate,
    InvoiceTemplateRead,
    InvoiceTemplateUpdate,
)
from factumov.schemas.invoice_template_draft import InvoiceTemplateDraft
from factumov.services.invoice_draft import build_draft
from factumov.services.invoice_parser import parse_invoice_pdf

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

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


@router.get("", response_model=list[InvoiceTemplateRead])
def list_invoice_templates(db: SessionDep, user: CurrentUserDep) -> list[InvoiceTemplate]:
    return invoice_template_crud.get_all(db, user.id)


@router.post("", response_model=InvoiceTemplateRead, status_code=201)
def create_invoice_template(
    data: InvoiceTemplateCreate, db: SessionDep, user: CurrentUserDep
) -> InvoiceTemplate:
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
