import pytest
from pydantic import ValidationError

from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.enums import Concepto, CondicionIva, DocType
from factumov.exceptions import (
    DuplicateFiscalIdentityNameError,
    DuplicateFiscalIdentityTaxIdError,
    FiscalIdentityInUseError,
)
from factumov.models.customer import Customer
from factumov.models.invoice_template import InvoiceTemplate
from factumov.schemas.fiscal_identity import FiscalIdentityCreate, FiscalIdentityUpdate


def test_get_by_tax(db, user):
    original_identity = fiscal_identity_crud.create(
        db,
        FiscalIdentityCreate(
            name="Test", condicion_iva=CondicionIva.INSCRIPTO, tax_id="20182810674"
        ),
        user.id,
    )
    assert fiscal_identity_crud.get_by_tax_id(db, "20182810674", user.id) == original_identity
    assert fiscal_identity_crud.get_by_tax_id(db, "11111111111", user.id) is None


def test_create_name(db, user):
    fiscal_identity_crud.create(
        db,
        FiscalIdentityCreate(
            name="Test", condicion_iva=CondicionIva.INSCRIPTO, tax_id="20182810674"
        ),
        user.id,
    )
    assert len(fiscal_identity_crud.get_all(db, user.id)) == 1
    fiscal = FiscalIdentityCreate(
        name="Test", condicion_iva=CondicionIva.MONOTRIBUTO, tax_id="11111111111"
    )
    with pytest.raises(DuplicateFiscalIdentityNameError):
        fiscal_identity_crud.create(db, fiscal, user.id)


def test_create_tax(db, user):
    fiscal1 = FiscalIdentityCreate(
        name="Test", condicion_iva=CondicionIva.INSCRIPTO, tax_id="11111111111"
    )
    fiscal_identity_crud.create(db, fiscal1, user.id)
    fiscal2 = FiscalIdentityCreate(
        name="Test1", condicion_iva=CondicionIva.MONOTRIBUTO, tax_id="11111111111"
    )

    with pytest.raises(DuplicateFiscalIdentityTaxIdError):
        fiscal_identity_crud.create(db, fiscal2, user.id)


def test_create_final(db):
    with pytest.raises(ValidationError):
        FiscalIdentityCreate(name="Test1", condicion_iva=CondicionIva.FINAL, tax_id="11111111111")


def test_update_name(db, user):
    fiscal_identity_crud.create(
        db,
        FiscalIdentityCreate(
            name="Test", condicion_iva=CondicionIva.INSCRIPTO, tax_id="20182810674"
        ),
        user.id,
    )
    identity = fiscal_identity_crud.create(
        db,
        FiscalIdentityCreate(
            name="Test2", condicion_iva=CondicionIva.MONOTRIBUTO, tax_id="11111111111"
        ),
        user.id,
    )
    fiscal = FiscalIdentityUpdate(name="Test")
    with pytest.raises(DuplicateFiscalIdentityNameError):
        fiscal_identity_crud.update(db, identity, fiscal)


def test_update_tax(db, user):
    fiscal_identity_crud.create(
        db,
        FiscalIdentityCreate(
            name="Test", condicion_iva=CondicionIva.INSCRIPTO, tax_id="20182810674"
        ),
        user.id,
    )
    identity = fiscal_identity_crud.create(
        db,
        FiscalIdentityCreate(
            name="Test2", condicion_iva=CondicionIva.MONOTRIBUTO, tax_id="11111111111"
        ),
        user.id,
    )
    fiscal = FiscalIdentityUpdate(tax_id="20182810674")
    with pytest.raises(DuplicateFiscalIdentityTaxIdError):
        fiscal_identity_crud.update(db, identity, fiscal)


def test_tax_schema():
    with pytest.raises(ValidationError):
        FiscalIdentityUpdate(tax_id="0182810674")


def test_condicion_iva_schema():
    with pytest.raises(ValidationError):
        FiscalIdentityUpdate(condicion_iva=CondicionIva.FINAL)


def test_delete(db, user):
    identity = fiscal_identity_crud.create(
        db,
        FiscalIdentityCreate(
            name="Identity", condicion_iva=CondicionIva.EXENTO, tax_id="11111111111"
        ),
        user.id,
    )
    customer = Customer(
        user_id=user.id,
        name="Customer",
        condicion_iva=CondicionIva.INSCRIPTO,
        doc_type=DocType.CUIT,
        doc_number="20182810674",
    )
    db.add(customer)
    db.flush()
    invoice = InvoiceTemplate(
        name="Template",
        fiscal_identity_id=identity.id,
        customer_id=customer.id,
        pos=5,
        concepto=Concepto.services,
    )
    db.add(invoice)
    db.flush()
    with pytest.raises(FiscalIdentityInUseError):
        fiscal_identity_crud.delete(db, identity)
