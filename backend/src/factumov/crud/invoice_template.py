import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from factumov.crud.base import db_flush
from factumov.exceptions import (
    DuplicateInvoiceTemplateNameError,
    UnknownCustomerError,
    UnknownFiscalIdentityError,
)
from factumov.models.invoice_template import InvoiceTemplate
from factumov.models.invoice_template_line import InvoiceTemplateLine
from factumov.schemas.invoice_template import InvoiceTemplateCreate, InvoiceTemplateUpdate
from factumov.schemas.invoice_template_line import InvoiceTemplateLineCreate

exception_map = {
    "uq_invoice_templates_fiscal_identity_id_name": DuplicateInvoiceTemplateNameError,
    "invoice_templates_customer_id_fkey": UnknownCustomerError,
    "invoice_templates_fiscal_identity_id_fkey": UnknownFiscalIdentityError,
}


def build_invoice_template_lines(
    lines: list[InvoiceTemplateLineCreate],
) -> list[InvoiceTemplateLine]:
    return [
        InvoiceTemplateLine(**line.model_dump(), position=position)
        for position, line in enumerate(lines)
    ]


def get_all(db: Session) -> list[InvoiceTemplate]:
    invoice_templates = (
        db.execute(select(InvoiceTemplate).options(selectinload(InvoiceTemplate.lines)))
        .scalars()
        .all()
    )
    return list(invoice_templates)


def get_by_id(db: Session, invoice_template_id: uuid.UUID) -> InvoiceTemplate | None:
    return db.get(InvoiceTemplate, invoice_template_id)


def create(db: Session, data: InvoiceTemplateCreate) -> InvoiceTemplate:
    invoice_template = InvoiceTemplate(**data.model_dump(exclude={"lines"}))
    db.add(invoice_template)
    invoice_template.lines = build_invoice_template_lines(data.lines)
    db_flush(db, exception_map)
    return invoice_template


def update(
    db: Session, invoice_template: InvoiceTemplate, data: InvoiceTemplateUpdate
) -> InvoiceTemplate:
    for field, value in data.model_dump(exclude_unset=True, exclude={"lines"}).items():
        setattr(invoice_template, field, value)
    if data.lines is not None:
        invoice_template.lines = build_invoice_template_lines(data.lines)
    db_flush(db, exception_map)
    return invoice_template


def delete(db: Session, invoice_template: InvoiceTemplate) -> None:
    db.delete(invoice_template)
    db_flush(db, exception_map)
