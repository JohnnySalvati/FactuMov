import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from factumov.crud import invoice_template as invoice_template_crud
from factumov.exceptions import (
    DuplicateInvoiceTemplateNameError,
    UnknownCustomerError,
    UnknownFiscalIdentityError,
)
from factumov.models.invoice_template_line import InvoiceTemplateLine
from factumov.schemas.invoice_template import InvoiceTemplateUpdate
from tests import factories


def count_lines(db):
    """Row count straight from the database.

    `len(template.lines)` would answer from the in-memory collection, which can look right
    even when no DELETE was ever emitted.
    """
    return db.execute(select(func.count()).select_from(InvoiceTemplateLine)).scalar()


def test_create_assigns_position_in_array_order(db, fiscal_identity, customer):
    template = invoice_template_crud.create(
        db,
        factories.make_template_create(
            fiscal_identity.id, customer.id, descriptions=("First", "Second", "Third")
        ),
    )

    assert [(line.position, line.description) for line in template.lines] == [
        (0, "First"),
        (1, "Second"),
        (2, "Third"),
    ]


def test_get_by_id_returns_lines_ordered_by_position(db, fiscal_identity, customer):
    template = factories.make_invoice_template(
        db, fiscal_identity, customer, lines=((2, "Third"), (0, "First"), (1, "Second"))
    )
    # Without expiring, `get_by_id` hands back the same identity-mapped instance whose
    # collection is still in insertion order, and the assertion would prove nothing.
    db.expire(template)

    loaded = invoice_template_crud.get_by_id(db, template.id)

    assert loaded is not None
    assert [line.description for line in loaded.lines] == ["First", "Second", "Third"]


def test_get_all_returns_templates_with_their_lines(db, fiscal_identity, customer):
    factories.make_invoice_template(db, fiscal_identity, customer, name="One")
    factories.make_invoice_template(db, fiscal_identity, customer, name="Two")
    db.expire_all()

    templates = invoice_template_crud.get_all(db)

    assert len(templates) == 2
    assert all(len(template.lines) == 2 for template in templates)


def test_update_without_lines_leaves_lines_untouched(db, fiscal_identity, customer):
    template = invoice_template_crud.create(
        db, factories.make_template_create(fiscal_identity.id, customer.id)
    )
    line_ids = {line.id for line in template.lines}

    invoice_template_crud.update(db, template, InvoiceTemplateUpdate(name="Renamed"))

    assert template.name == "Renamed"
    assert {line.id for line in template.lines} == line_ids
    assert count_lines(db) == 2


def test_update_with_shorter_list_deletes_the_orphans(db, fiscal_identity, customer):
    template = invoice_template_crud.create(
        db,
        factories.make_template_create(
            fiscal_identity.id, customer.id, descriptions=("First", "Second", "Third")
        ),
    )
    assert count_lines(db) == 3

    invoice_template_crud.update(
        db,
        template,
        InvoiceTemplateUpdate(lines=[factories.make_line_create(description="Only")]),
    )

    assert count_lines(db) == 1
    assert [(line.position, line.description) for line in template.lines] == [(0, "Only")]


def test_update_with_empty_lines_is_rejected_by_the_schema():
    with pytest.raises(ValidationError):
        InvoiceTemplateUpdate(lines=[])


def test_delete_cascades_to_lines(db, fiscal_identity, customer):
    template = invoice_template_crud.create(
        db, factories.make_template_create(fiscal_identity.id, customer.id)
    )
    assert count_lines(db) == 2

    invoice_template_crud.delete(db, template)

    assert invoice_template_crud.get_all(db) == []
    assert count_lines(db) == 0


def test_create_with_unknown_customer(db, fiscal_identity):
    with pytest.raises(UnknownCustomerError):
        invoice_template_crud.create(
            db, factories.make_template_create(fiscal_identity.id, uuid.uuid4())
        )


def test_create_with_unknown_fiscal_identity(db, customer):
    with pytest.raises(UnknownFiscalIdentityError):
        invoice_template_crud.create(db, factories.make_template_create(uuid.uuid4(), customer.id))


def test_name_is_unique_per_fiscal_identity(db, fiscal_identity, customer):
    invoice_template_crud.create(
        db, factories.make_template_create(fiscal_identity.id, customer.id, name="Alquiler")
    )

    with pytest.raises(DuplicateInvoiceTemplateNameError):
        invoice_template_crud.create(
            db, factories.make_template_create(fiscal_identity.id, customer.id, name="Alquiler")
        )


def test_same_name_under_another_fiscal_identity_is_allowed(db, fiscal_identity, customer):
    other_identity = factories.make_fiscal_identity(db)
    invoice_template_crud.create(
        db, factories.make_template_create(fiscal_identity.id, customer.id, name="Alquiler")
    )
    invoice_template_crud.create(
        db, factories.make_template_create(other_identity.id, customer.id, name="Alquiler")
    )

    assert len(invoice_template_crud.get_all(db)) == 2
