import pytest
from pydantic import ValidationError

from factumov.crud import customer as customer_crud
from factumov.enums import Concepto, CondicionIva, DocType, VoucherType
from factumov.exceptions import CustomerInUseError, DuplicateCustomerError
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.models.invoice_template import InvoiceTemplate
from factumov.schemas.customer import CustomerCreate, CustomerUpdate
from tests import factories


def customer_create(
    db,
    user,
    name: str = "test",
    condicion_iva: CondicionIva = CondicionIva.INSCRIPTO,
    doc_type: DocType = DocType.CUIT,
    doc_number: str = "22222222222",
    email: str | None = None,
):
    return customer_crud.create(
        db,
        CustomerCreate(
            name=name,
            condicion_iva=condicion_iva,
            doc_type=doc_type,
            doc_number=doc_number,
            email=email,
        ),
        user.id,
    )


def test_create(db, user):
    customer_create(
        db,
        user,
        doc_number="20182810674",
    )
    with pytest.raises(DuplicateCustomerError):
        customer_create(db, user, doc_number="20182810674")


def test_update_or_create_new(db, user):
    customer1 = customer_crud.update_or_create(
        db,
        CustomerCreate(
            name="test1",
            condicion_iva=CondicionIva.INSCRIPTO,
            doc_type=DocType.CUIT,
            doc_number="20182810674",
        ),
        user.id,
    )
    assert customer1.doc_type == DocType.CUIT
    assert len(customer_crud.get_all(db, user.id)) == 1

    customer2 = customer_crud.update_or_create(
        db,
        CustomerCreate(
            name="test2",
            condicion_iva=CondicionIva.INSCRIPTO,
            doc_type=DocType.CUIT,
            doc_number="20182810675",
        ),
        user.id,
    )
    assert len(customer_crud.get_all(db, user.id)) == 2
    assert customer1.name == "test1"
    assert customer2.name == "test2"


def test_update_or_create_update(db, user):
    customer = customer_crud.update_or_create(
        db,
        CustomerCreate(
            name="test1",
            condicion_iva=CondicionIva.INSCRIPTO,
            doc_type=DocType.CUIT,
            doc_number="20182810674",
            address="Aroma 2312",
            email="miguelsalvati@gmail.com",
        ),
        user.id,
    )
    assert len(customer_crud.get_all(db, user.id)) == 1

    customer = customer_crud.update_or_create(
        db,
        CustomerCreate(
            name="Updated",
            condicion_iva=CondicionIva.INSCRIPTO,
            doc_type=DocType.CUIT,
            doc_number="20182810674",
        ),
        user.id,
    )

    assert len(customer_crud.get_all(db, user.id)) == 1
    assert customer.name == "Updated"
    assert customer.doc_number == "20182810674"
    assert customer.address == "Aroma 2312"


def test_delete_single(db, user):
    customer = customer_crud.update_or_create(
        db,
        CustomerCreate(
            name="test1",
            condicion_iva=CondicionIva.INSCRIPTO,
            doc_type=DocType.CUIT,
            doc_number="20182810674",
        ),
        user.id,
    )

    assert len(customer_crud.get_all(db, user.id)) == 1
    customer_crud.delete(db, customer)
    assert len(customer_crud.get_all(db, user.id)) == 0


def test_delete_in_use(db, user):
    customer = customer_crud.update_or_create(
        db,
        CustomerCreate(
            name="test1",
            condicion_iva=CondicionIva.INSCRIPTO,
            doc_type=DocType.CUIT,
            doc_number="20182810674",
        ),
        user.id,
    )

    fiscal_identity = FiscalIdentity(
        user_id=user.id,
        name="Identity",
        condicion_iva=CondicionIva.INSCRIPTO,
        tax_id="18281067",
    )
    db.add(fiscal_identity)
    db.flush()

    invoice = InvoiceTemplate(
        name="Template 1",
        fiscal_identity_id=fiscal_identity.id,
        customer_id=customer.id,
        voucher_type=VoucherType.B,
        pos=1,
        concepto=Concepto.services,
    )
    db.add(invoice)
    db.flush()

    assert len(customer.invoice_templates) == 1

    with pytest.raises(CustomerInUseError):
        customer_crud.delete(db, customer)


def test_doc_number_none():
    with pytest.raises(ValidationError):
        CustomerUpdate(doc_type=DocType.CUIT, doc_number=None)


def test_doc_number_alone(db, user):
    customer = factories.make_customer(db, user.id)
    customer_crud.update(db, customer, CustomerUpdate(doc_type=DocType.CUIT))
    assert customer.doc_type == DocType.CUIT
    assert customer.doc_number is not None


def test_update_or_create_does_not_touch_another_users_customer(db, user, other_user):
    """El `get_by_doc` de adentro está scopeado, así que la rama que elige cambia.

    Esta función no la llama ningún router todavía —el `/import` resuelve pero no
    escribe—, así que ningún test de HTTP la cubre. Sin el scoping, el mismo documento
    bajo otro dueño la mandaba por la rama de update y le pisaba el nombre al cliente de
    otro usuario.
    """
    theirs = factories.make_customer(
        db, other_user.id, name="Theirs", doc_type=DocType.CUIT, doc_number="20182810674"
    )

    mine = customer_crud.update_or_create(
        db,
        CustomerCreate(
            name="Mine",
            condicion_iva=CondicionIva.INSCRIPTO,
            doc_type=DocType.CUIT,
            doc_number="20182810674",
        ),
        user.id,
    )

    assert mine.id != theirs.id
    assert theirs.name == "Theirs"
    assert len(customer_crud.get_all(db, user.id)) == 1
