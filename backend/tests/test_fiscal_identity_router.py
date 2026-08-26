"""Tests for the /fiscal-identities routes.

The issuer is the user's own company, so these rows are the ones a second user must never
see. The scoping section at the bottom pins that; the rest of the file pins the behaviour
scoping had to preserve.
"""

import uuid

from factumov.enums import CondicionIva
from factumov.models.fiscal_identity import FiscalIdentity
from tests import factories

URL = "/fiscal-identities"


def payload(**overrides):
    body = {
        "name": "Acme SRL",
        "condicion_iva": CondicionIva.INSCRIPTO.value,
        "tax_id": "30714597066",
    }
    body.update(overrides)
    return body


def test_create_answers_201_with_the_stored_identity(client):
    response = client.post(URL, json=payload(address="Aroma 2312", iibb="901-123456-01"))

    assert response.status_code == 201
    body = response.json()

    assert body["name"] == "Acme SRL"
    assert body["tax_id"] == "30714597066"
    assert body["condicion_iva"] == CondicionIva.INSCRIPTO.value
    assert body["address"] == "Aroma 2312"
    assert body["iibb"] == "901-123456-01"
    assert body["start_date"] is None


def test_create_rejects_a_duplicate_name(user, client, db):
    factories.make_fiscal_identity(db, user.id, name="Acme SRL")

    response = client.post(URL, json=payload())

    assert response.status_code == 409
    assert response.json()["detail"] == "Nombre duplicado"


def test_create_rejects_a_duplicate_tax_id(user, client, db):
    """The pair of duplicate tests is the reason this file exists.

    `fiscal_identities_name_key` and `fiscal_identities_tax_id_key` are two constraints
    that the CRUD maps to two exceptions and the router to two different messages. Every
    test below the HTTP layer passes just as happily with those two branches swapped; only
    an assertion on the message catches it, and the user is the one who would otherwise be
    told the wrong field is at fault.
    """
    factories.make_fiscal_identity(db, user.id, tax_id="30714597066")

    response = client.post(URL, json=payload(name="Another Name"))

    assert response.status_code == 409
    assert response.json()["detail"] == "CUIT duplicado"


def test_create_rejects_a_tax_id_that_is_not_eleven_digits(client):
    response = client.post(URL, json=payload(tax_id="3071459"))

    assert response.status_code == 422


def test_create_rejects_a_tax_id_that_is_not_all_digits(client):
    """`max_length=11` alone would let this through — the field validator is what stops it."""
    response = client.post(URL, json=payload(tax_id="30-71459706"))

    assert response.status_code == 422


def test_create_rejects_condicion_iva_final(client):
    """A consumidor final receives invoices; it cannot issue them.

    The same enum is legal on a `Customer`, which is why the rule lives in this schema
    rather than in the enum itself.
    """
    response = client.post(URL, json=payload(condicion_iva=CondicionIva.FINAL.value))

    assert response.status_code == 422


def test_list_answers_the_stored_identities(user, client, db):
    factories.make_fiscal_identity(db, user.id, name="First")
    factories.make_fiscal_identity(db, user.id, name="Second")

    response = client.get(URL)

    assert response.status_code == 200
    assert {identity["name"] for identity in response.json()} == {"First", "Second"}


def test_get_answers_the_identity(client, fiscal_identity):
    response = client.get(f"{URL}/{fiscal_identity.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(fiscal_identity.id)


def test_get_an_unknown_id_is_a_404(client):
    response = client.get(f"{URL}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Identidad fiscal no encontrada"


def test_patch_touches_only_the_fields_it_was_given(client, fiscal_identity):
    original_tax_id = fiscal_identity.tax_id

    response = client.patch(f"{URL}/{fiscal_identity.id}", json={"address": "Aroma 2312"})

    assert response.status_code == 200
    body = response.json()

    assert body["address"] == "Aroma 2312"
    assert body["tax_id"] == original_tax_id
    assert body["condicion_iva"] == CondicionIva.INSCRIPTO.value


def test_patch_into_a_duplicate_name_is_a_409(user, client, db, fiscal_identity):
    factories.make_fiscal_identity(db, user.id, name="Taken")

    response = client.patch(f"{URL}/{fiscal_identity.id}", json={"name": "Taken"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Nombre duplicado"


def test_patch_into_a_duplicate_tax_id_is_a_409(user, client, db, fiscal_identity):
    factories.make_fiscal_identity(db, user.id, tax_id="30714597066")

    response = client.patch(f"{URL}/{fiscal_identity.id}", json={"tax_id": "30714597066"})

    assert response.status_code == 409
    assert response.json()["detail"] == "CUIT duplicado"


def test_patch_an_unknown_id_is_a_404(client):
    response = client.patch(f"{URL}/{uuid.uuid4()}", json={"name": "Renamed"})

    assert response.status_code == 404


def test_delete_answers_204(client, fiscal_identity):
    response = client.delete(f"{URL}/{fiscal_identity.id}")

    assert response.status_code == 204
    assert client.get(f"{URL}/{fiscal_identity.id}").status_code == 404


def test_delete_an_identity_that_has_templates_is_a_409(client, db, fiscal_identity, customer):
    factories.make_invoice_template(db, fiscal_identity, customer)

    response = client.delete(f"{URL}/{fiscal_identity.id}")

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "No se puede eliminar una identidad fiscal con modelos asociados"
    )


def test_delete_an_unknown_id_is_a_404(client):
    response = client.delete(f"{URL}/{uuid.uuid4()}")

    assert response.status_code == 404


# --- Ownership scoping -------------------------------------------------------------


def test_list_excludes_another_users_identities(user, other_user, client, db):
    factories.make_fiscal_identity(db, user.id, name="Mine")
    factories.make_fiscal_identity(db, other_user.id, name="Theirs")

    response = client.get(URL)

    assert response.status_code == 200
    assert {identity["name"] for identity in response.json()} == {"Mine"}


def test_get_another_users_identity_is_404(other_user, client, db):
    theirs = factories.make_fiscal_identity(db, other_user.id)

    response = client.get(f"{URL}/{theirs.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Identidad fiscal no encontrada"


def test_patch_another_users_identity_is_404(other_user, client, db):
    theirs = factories.make_fiscal_identity(db, other_user.id, name="Theirs")

    response = client.patch(f"{URL}/{theirs.id}", json={"name": "Hijacked"})

    assert response.status_code == 404
    db.refresh(theirs)
    assert theirs.name == "Theirs"


def test_delete_another_users_identity_is_404(other_user, client, db):
    theirs = factories.make_fiscal_identity(db, other_user.id)

    response = client.delete(f"{URL}/{theirs.id}")

    assert response.status_code == 404
    assert db.get(FiscalIdentity, theirs.id) is not None


def test_create_allows_a_name_and_tax_id_already_used_by_another_user(other_user, client, db):
    """Los dos uniques de la tabla son por usuario.

    El del CUIT es el que más importa: global impediría que el contador cargue el CUIT de
    su cliente mientras el titular tiene su propia cuenta, y el 409 delataría que ese CUIT
    ya está en el sistema. Que la delegación en ARCA se verifique por identidad fiscal es
    lo que hace que aflojar el unique no afloje el control de titularidad.
    """
    factories.make_fiscal_identity(db, other_user.id, name="Acme SRL", tax_id="30714597066")

    response = client.post(URL, json=payload())

    assert response.status_code == 201
    assert response.json()["tax_id"] == "30714597066"
