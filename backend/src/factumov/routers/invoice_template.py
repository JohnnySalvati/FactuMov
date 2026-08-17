import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from factumov.crud import customer as customer_crud
from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.crud import invoice_template as invoice_template_crud
from factumov.database import get_db
from factumov.enums import DocType
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

router = APIRouter(prefix="/invoice-templates", tags=["invoice_templates"])

SessionDep = Annotated[Session, Depends(get_db)]


def get_invoice_template_or_404(invoice_template_id: uuid.UUID, db: SessionDep) -> InvoiceTemplate:
    invoice_template = invoice_template_crud.get_by_id(db, invoice_template_id)
    if invoice_template is None:
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    return invoice_template


InvoiceTemplateDep = Annotated[InvoiceTemplate, Depends(get_invoice_template_or_404)]


@router.get("", response_model=list[InvoiceTemplateRead])
def list_invoice_templates(db: SessionDep) -> list[InvoiceTemplate]:
    return invoice_template_crud.get_all(db)


@router.post("", response_model=InvoiceTemplateRead, status_code=201)
def create_invoice_template(data: InvoiceTemplateCreate, db: SessionDep) -> InvoiceTemplate:
    try:
        invoice_template = invoice_template_crud.create(db, data)
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
) -> InvoiceTemplateDraft:
    customer = None
    parsed_invoice = parse_invoice_pdf(file.file.read())
    if parsed_invoice.customer_doc_type and parsed_invoice.customer_doc_number:
        if parsed_invoice.customer_doc_type is not DocType.FINAL:
            customer = customer_crud.get_by_doc(
                db, parsed_invoice.customer_doc_type, parsed_invoice.customer_doc_number
            )
    fiscal_identity = (
        fiscal_identity_crud.get_by_tax_id(db, parsed_invoice.issuer_cuit)
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
    data: InvoiceTemplateUpdate, invoice_template: InvoiceTemplateDep, db: SessionDep
) -> InvoiceTemplate:
    try:
        invoice_template = invoice_template_crud.update(db, invoice_template, data)
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
