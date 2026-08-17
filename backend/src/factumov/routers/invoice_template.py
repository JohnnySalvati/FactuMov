import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from factumov.crud import invoice_template as invoice_template_crud
from factumov.database import get_db
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


@router.get("/{invoice_template_id}", response_model=InvoiceTemplateRead)
def get_invoice_template(invoice_template: InvoiceTemplateDep) -> InvoiceTemplate:
    return invoice_template


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
