"""Tests for the /customers routes.

`test_customer_crud.py` proves the CRUD functions behave; this file proves the HTTP layer
above them does. The two are not the same claim: the CRUD raising `DuplicateCustomerError`
says nothing about whether the router turns it into a 409 or lets it escape as a 500.
"""

import uuid

from factumov.enums import CondicionIva, DocType
from tests import factories

URL = "/customers"


def payload(**overrides):
    """A create body, as JSON, with the enums already reduced to their wire values.

    `CondicionIva` and `DocType` are plain int-valued enums, so what travels is 1 and 80,
    not "INSCRIPTO" and "CUIT". Writing them through the enum rather than as literals is
    what makes this file fail loudly if an ARCA code ever changes.
    """
    body = {
        "name": "Acme SRL",
        "condicion_iva": CondicionIva.INSCRIPTO.value,
        "doc_type": DocType.CUIT.value,
        "doc_number": "30714597066",
    }
    body.update(overrides)
    return body


def test_create_answers_201_with_the_stored_customer(client):
    response = client.post(URL, json=payload())

    assert response.status_code == 201
    body = response.json()

    assert body["name"] == "Acme SRL"
    assert body["doc_type"] == DocType.CUIT.value
    assert body["doc_number"] == "30714597066"
    assert body["condicion_iva"] == CondicionIva.INSCRIPTO.value
    assert uuid.UUID(body["id"])


def test_create_rejects_a_duplicate_doc_type_and_number(client, db):
    factories.make_customer(db, doc_type=DocType.CUIT, doc_number="30714597066")

    response = client.post(URL, json=payload())

    assert response.status_code == 409
    assert response.json()["detail"] == "Numero de documento/CUIT duplicado"


def test_create_allows_the_same_number_under_another_doc_type(client, db):
    """`uq_customers_doc_type_doc_number` spans both columns, so the number alone is free.

    A CUIT and a DNI can legally share digits. Keying the constraint — or the import
    endpoint's lookup — on the number alone would collapse two different people into one.
    """
    factories.make_customer(db, doc_type=DocType.DNI, doc_number="30714597066")

    response = client.post(URL, json=payload(doc_type=DocType.CUIT.value))

    assert response.status_code == 201


def test_create_requires_a_doc_number(client):
    """FactuMov has no anonymous customers, so the field has no default to fall back on.

    This is the rule that replaced `DocType.FINAL`: a buyer who hands over no document has
    no template worth saving, and a NULL `doc_number` used to make `get_by_doc` blind to
    the row forever.
    """
    body = payload()
    del body["doc_number"]

    response = client.post(URL, json=body)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "doc_number"]


def test_create_rejects_an_unknown_doc_type(client):
    """The enum is closed at {CUIT, CUIL, DNI} — 99, ARCA's "sin identificar", is gone."""
    response = client.post(URL, json=payload(doc_type=99))

    assert response.status_code == 422


def test_create_rejects_a_malformed_email(client):
    response = client.post(URL, json=payload(email="not-an-email"))

    assert response.status_code == 422


def test_create_normalises_the_email(client):
    """Case is not identity for a mailbox, and the address is what will send the invoice.

    Storing it as typed would let the same customer arrive twice under two spellings.
    """
    response = client.post(URL, json=payload(email="Miguel@Example.COM"))

    assert response.status_code == 201
    assert response.json()["email"] == "miguel@example.com"


def test_list_answers_the_stored_customers(client, db):
    factories.make_customer(db, name="First")
    factories.make_customer(db, name="Second")

    response = client.get(URL)

    assert response.status_code == 200
    assert {customer["name"] for customer in response.json()} == {"First", "Second"}


def test_get_answers_the_customer(client, customer):
    response = client.get(f"{URL}/{customer.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(customer.id)


def test_get_an_unknown_id_is_a_404(client):
    response = client.get(f"{URL}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Cliente no encontrado"


def test_patch_touches_only_the_fields_it_was_given(client, customer):
    """`exclude_unset` is what keeps an absent field from being written as None.

    Without it a rename would blank out the address, which is the kind of loss the user
    only notices on the next invoice.
    """
    original_doc_number = customer.doc_number

    response = client.patch(f"{URL}/{customer.id}", json={"name": "Renamed"})

    assert response.status_code == 200
    body = response.json()

    assert body["name"] == "Renamed"
    assert body["doc_number"] == original_doc_number
    assert body["condicion_iva"] == CondicionIva.INSCRIPTO.value


def test_patch_into_a_duplicate_doc_is_a_409(client, db):
    taken = factories.make_customer(db, doc_type=DocType.CUIT, doc_number="30714597066")
    customer = factories.make_customer(db, doc_type=DocType.CUIT, doc_number="20182810674")

    response = client.patch(f"{URL}/{customer.id}", json={"doc_number": taken.doc_number})

    assert response.status_code == 409
    assert response.json()["detail"] == "Numero de documento/CUIT duplicado"


def test_patch_rejects_a_null_doc_number(client, customer):
    """Explicit null is refused, while an absent key still means "leave it alone".

    `CustomerUpdate` can only tell those apart through `model_fields_set`, because both
    end up as `doc_number is None` on the model.
    """
    response = client.patch(f"{URL}/{customer.id}", json={"doc_number": None})

    assert response.status_code == 422


def test_patch_an_unknown_id_is_a_404(client):
    response = client.patch(f"{URL}/{uuid.uuid4()}", json={"name": "Renamed"})

    assert response.status_code == 404


def test_delete_answers_204(client, customer):
    response = client.delete(f"{URL}/{customer.id}")

    assert response.status_code == 204
    assert client.get(f"{URL}/{customer.id}").status_code == 404


def test_delete_a_customer_that_has_templates_is_a_409(client, db, fiscal_identity, customer):
    """The FK refuses the delete and the router explains why rather than answering 500.

    `passive_deletes="all"` is what lets the database be the one to object: SQLAlchemy
    neither cascades nor nulls the FK, so the constraint fires and the CRUD maps it.
    """
    factories.make_invoice_template(db, fiscal_identity, customer)

    response = client.delete(f"{URL}/{customer.id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "No se puede eliminar un cliente con modelos asociados"


def test_delete_an_unknown_id_is_a_404(client):
    response = client.delete(f"{URL}/{uuid.uuid4()}")

    assert response.status_code == 404
