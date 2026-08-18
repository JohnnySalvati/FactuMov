"""Arrangement helpers for the test suite.

These build rows directly through the ORM instead of going through `crud/`, so a bug in
one module's CRUD fails only that module's tests. The CRUD is the *act* under test; these
functions only set up the *arrangement*.

Unique columns (`fiscal_identities.name`, `fiscal_identities.tax_id`,
`customers.doc_number`) get their defaults from a module-level counter, so calling the same
factory twice inside one test does not collide.
"""

import itertools
from decimal import Decimal

from factumov.enums import Concepto, CondicionIva, DocType, IvaAliquot, VoucherType
from factumov.models.customer import Customer
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.models.invoice_template import InvoiceTemplate
from factumov.models.invoice_template_line import InvoiceTemplateLine
from factumov.schemas.invoice_template import InvoiceTemplateCreate
from factumov.schemas.invoice_template_line import InvoiceTemplateLineCreate

_sequence = itertools.count(1)


def make_fiscal_identity(db, name=None, tax_id=None, condicion_iva=CondicionIva.INSCRIPTO):
    n = next(_sequence)
    fiscal_identity = FiscalIdentity(
        name=f"Fiscal Identity {n}" if name is None else name,
        tax_id=f"20{n:09d}" if tax_id is None else tax_id,
        condicion_iva=condicion_iva,
    )
    db.add(fiscal_identity)
    db.flush()
    return fiscal_identity


def make_customer(
    db,
    name=None,
    doc_number: str = "",
    doc_type=DocType.CUIT,
    condicion_iva=CondicionIva.INSCRIPTO,
):
    n = next(_sequence)
    customer = Customer(
        name=f"Customer {n}" if name is None else name,
        doc_number=f"27{n:09d}" if doc_number == "" else doc_number,
        doc_type=doc_type,
        condicion_iva=condicion_iva,
    )
    db.add(customer)
    db.flush()
    return customer


def make_line_create(
    description="Line",
    quantity=Decimal("1"),
    unit_price=Decimal("100"),
    iva_aliquot=IvaAliquot.standard,
):
    """Build one `InvoiceTemplateLineCreate` — the schema, not the ORM row."""
    return InvoiceTemplateLineCreate(
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        iva_aliquot=iva_aliquot,
    )


def make_template_create(
    fiscal_identity_id,
    customer_id,
    name="Template",
    descriptions=("First", "Second"),
    voucher_type=VoucherType.B,
    pos=1,
    concepto=Concepto.products,
):
    """Build an `InvoiceTemplateCreate` payload.

    Takes ids rather than objects so a test can pass a `uuid4()` that matches no row and
    exercise the foreign-key branches of `exception_map`.
    """
    return InvoiceTemplateCreate(
        name=name,
        fiscal_identity_id=fiscal_identity_id,
        customer_id=customer_id,
        voucher_type=voucher_type,
        pos=pos,
        concepto=concepto,
        lines=[make_line_create(description=description) for description in descriptions],
    )


def make_invoice_template(
    db,
    fiscal_identity,
    customer,
    name="Template",
    lines=((0, "First"), (1, "Second")),
    voucher_type=VoucherType.B,
    pos=1,
    concepto=Concepto.products,
):
    """Insert a template straight through the ORM.

    `lines` is a sequence of `(position, description)` pairs, so a test can write rows whose
    insertion order differs from their `position` — the only way to prove the relationship's
    `order_by` is doing the sorting rather than the insertion order.
    """
    invoice_template = InvoiceTemplate(
        name=name,
        fiscal_identity_id=fiscal_identity.id,
        customer_id=customer.id,
        voucher_type=voucher_type,
        pos=pos,
        concepto=concepto,
        lines=[
            InvoiceTemplateLine(
                position=position,
                description=description,
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                iva_aliquot=IvaAliquot.standard,
            )
            for position, description in lines
        ],
    )
    db.add(invoice_template)
    db.flush()
    return invoice_template
