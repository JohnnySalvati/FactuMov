"""Tests for the /invoice-templates routes other than /import.

These go through HTTP, unlike `test_invoice_template_crud.py`, because what they check
lives in the router rather than in the CRUD: the status code each failure earns, the 404
the path dependency raises, and the JSON shape the frontend will be written against. "The
CRUD raises the right exception" and "the API answers the right status" are two different
claims, and only the second one is a contract with the client.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from factumov.enums import IvaAliquot
from factumov.models.invoice_template import InvoiceTemplate
from factumov.models.invoice_template_line import InvoiceTemplateLine
from tests import factories

URL = "/invoice-templates"


def payload(fiscal_identity_id, customer_id, **kwargs):
    """A create body, as JSON.

    Built by dumping the same schema the CRUD tests already build, so the two cannot drift
    apart: a field added to `InvoiceTemplateCreate` reaches this file without editing it.
    `mode="json"` is what turns the UUIDs and the Decimals into strings — a plain
    `model_dump()` would hand `client.post` objects its JSON encoder rejects.
    """
    return factories.make_template_create(fiscal_identity_id, customer_id, **kwargs).model_dump(
        mode="json"
    )


def count_lines(db):
    """Row count straight from the table, not from the in-memory collection."""
    return db.execute(select(func.count()).select_from(InvoiceTemplateLine)).scalar()


def test_create_numbers_the_lines_in_array_order(client, fiscal_identity, customer):
    response = client.post(
        URL,
        json=payload(fiscal_identity.id, customer.id, descriptions=("First", "Second", "Third")),
    )

    assert response.status_code == 201
    body = response.json()

    assert body["name"] == "Template"
    assert body["fiscal_identity_id"] == str(fiscal_identity.id)
    assert body["customer_id"] == str(customer.id)
    # Deducida, no elegida: los dos fixtures son responsables inscriptos y esa
    # combinación es la única que da A. Ver `services/voucher.py`.
    assert body["voucher_type"] == "A"
    assert body["concepto"] == "products"

    # `position` is never sent by the client: the order of the array is the order of the
    # lines, and the CRUD assigns the numbers with `enumerate()`.
    assert [(line["position"], line["description"]) for line in body["lines"]] == [
        (0, "First"),
        (1, "Second"),
        (2, "Third"),
    ]
    assert body["lines"][0]["iva_aliquot"] == IvaAliquot.standard.value


def test_create_answers_the_amounts_as_strings(client, fiscal_identity, customer):
    """Amounts cross the wire as JSON strings, so no float ever rounds one.

    The comparison goes through `Decimal` rather than string equality on purpose: what
    comes back carries the scale that was sent, because nothing reloaded the row from the
    `Numeric(18, 4)` column that would pad it. The contract is the value and the type, not
    the padding — asserting `"2.5000"` here would pin down when the session happens to
    refresh, which is not a promise the API makes.
    """
    body = payload(fiscal_identity.id, customer.id, descriptions=("Only",))
    body["lines"][0]["quantity"] = "2.5"
    body["lines"][0]["unit_price"] = "1234.56"

    response = client.post(URL, json=body)

    assert response.status_code == 201
    line = response.json()["lines"][0]

    assert isinstance(line["quantity"], str)
    assert Decimal(line["quantity"]) == Decimal("2.5")
    assert Decimal(line["unit_price"]) == Decimal("1234.56")


def test_create_rejects_a_duplicate_name_under_one_identity(client, db, fiscal_identity, customer):
    factories.make_invoice_template(db, fiscal_identity, customer, name="Alquiler")

    response = client.post(URL, json=payload(fiscal_identity.id, customer.id, name="Alquiler"))

    assert response.status_code == 409
    assert response.json()["detail"] == "Nombre duplicado"


def test_create_allows_the_same_name_under_another_identity(
    user, client, db, fiscal_identity, customer
):
    """The unique constraint spans both columns, so the name alone is not the conflict.

    Two of the user's own companies can each have their own "Alquiler"; only repeating it
    inside one of them is a 409.
    """
    other_identity = factories.make_fiscal_identity(db, user.id)
    factories.make_invoice_template(db, fiscal_identity, customer, name="Alquiler")

    response = client.post(URL, json=payload(other_identity.id, customer.id, name="Alquiler"))

    assert response.status_code == 201


def test_create_with_an_unknown_customer(client, fiscal_identity):
    """422 rather than 404: the id is well formed, it just points at nothing.

    Only one of the two foreign keys is broken per test. With both wrong, Postgres reports
    whichever constraint it happens to check first, and the assertion on the message would
    be testing the planner instead of the router.
    """
    response = client.post(URL, json=payload(fiscal_identity.id, uuid.uuid4()))

    assert response.status_code == 422
    assert response.json()["detail"] == "Cliente desconocido"


def test_create_with_an_unknown_fiscal_identity(client, customer):
    response = client.post(URL, json=payload(uuid.uuid4(), customer.id))

    assert response.status_code == 422
    assert response.json()["detail"] == "Identidad fiscal desconocida"


def test_create_rejects_an_empty_line_array(client, fiscal_identity, customer):
    """A template with no lines cannot be issued, so `[]` never reaches the CRUD.

    `min_length=1` on the schema turns this into a 422 during validation. The body has to
    be built as a raw dict because the factory would refuse to construct it.
    """
    body = payload(fiscal_identity.id, customer.id)
    body["lines"] = []

    response = client.post(URL, json=body)

    assert response.status_code == 422


def test_create_rejects_a_point_of_sale_of_zero(client, fiscal_identity, customer):
    body = payload(fiscal_identity.id, customer.id)
    body["pos"] = 0

    response = client.post(URL, json=body)

    assert response.status_code == 422


def test_list_answers_the_stored_templates(client, db, fiscal_identity, customer):
    factories.make_invoice_template(db, fiscal_identity, customer, name="First")
    factories.make_invoice_template(db, fiscal_identity, customer, name="Second")
    # Same shared-session caveat as the ordering test: without expiring, the collections
    # are already in memory and the claim below about eager loading would hold whether or
    # not `get_all` asked for it.
    db.expire_all()

    response = client.get(URL)

    assert response.status_code == 200
    body = response.json()

    assert {template["name"] for template in body} == {"First", "Second"}
    assert all(template["lines"] for template in body)


def test_get_answers_the_lines_ordered_by_position(client, db, fiscal_identity, customer):
    """Insertion order and `position` disagree on purpose.

    Rows written as Third/First/Second can only come back in the right order if the
    relationship's `order_by` is doing the sorting.

    The expire is what makes that a real question, for the same reason the CRUD suite
    expires before its own ordering test. Test and request share one session, so without
    it `get_by_id` hands back the identity-mapped instance whose collection is still in
    insertion order, and no SELECT — hence no `order_by` — ever runs. In production the
    point is moot: every request gets its own session and must load the collection from
    the table.
    """
    template = factories.make_invoice_template(
        db, fiscal_identity, customer, lines=((2, "Third"), (0, "First"), (1, "Second"))
    )
    db.expire(template)

    response = client.get(f"{URL}/{template.id}")

    assert response.status_code == 200
    assert [line["description"] for line in response.json()["lines"]] == [
        "First",
        "Second",
        "Third",
    ]


def test_get_an_unknown_id_is_a_404(client):
    response = client.get(f"{URL}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Modelo no encontrado"


def test_get_a_path_that_is_not_a_uuid_is_a_validation_error(client):
    """422, not 404 — and the difference is one the client needs.

    FastAPI coerces the path parameter before the endpoint runs, so a malformed id never
    reaches `get_invoice_template_or_404`. A frontend that read every 4xx on this route as
    "not found" would hide its own bug of having built a bad URL.
    """
    response = client.get(f"{URL}/not-a-uuid")

    assert response.status_code == 422


def test_patch_the_name_leaves_the_lines_untouched(client, db, fiscal_identity, customer):
    """`lines` absent means "do not touch", which is not the same as an empty list."""
    template = factories.make_invoice_template(db, fiscal_identity, customer)

    response = client.patch(f"{URL}/{template.id}", json={"name": "Renamed"})

    assert response.status_code == 200
    body = response.json()

    assert body["name"] == "Renamed"
    assert [line["description"] for line in body["lines"]] == ["First", "Second"]
    assert count_lines(db) == 2


def test_patch_replaces_the_whole_line_array(client, db, fiscal_identity, customer):
    """The editor always sends the complete list, so update replaces rather than merges."""
    template = factories.make_invoice_template(
        db, fiscal_identity, customer, lines=((0, "First"), (1, "Second"), (2, "Third"))
    )

    response = client.patch(
        f"{URL}/{template.id}",
        json={"lines": [factories.make_line_create(description="Only").model_dump(mode="json")]},
    )

    assert response.status_code == 200
    assert [(line["position"], line["description"]) for line in response.json()["lines"]] == [
        (0, "Only")
    ]

    # The orphans are gone from the table, not merely detached from the collection.
    assert count_lines(db) == 1


def test_patch_rejects_an_empty_line_array(client, db, fiscal_identity, customer):
    template = factories.make_invoice_template(db, fiscal_identity, customer)

    response = client.patch(f"{URL}/{template.id}", json={"lines": []})

    assert response.status_code == 422


def test_patch_into_a_name_that_already_exists(client, db, fiscal_identity, customer):
    factories.make_invoice_template(db, fiscal_identity, customer, name="Alquiler")
    template = factories.make_invoice_template(db, fiscal_identity, customer, name="Honorarios")

    response = client.patch(f"{URL}/{template.id}", json={"name": "Alquiler"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Nombre duplicado"


def test_patch_an_unknown_id_is_a_404(client):
    response = client.patch(f"{URL}/{uuid.uuid4()}", json={"name": "Renamed"})

    assert response.status_code == 404


def test_delete_answers_204_and_takes_the_lines_with_it(client, db, fiscal_identity, customer):
    template = factories.make_invoice_template(db, fiscal_identity, customer)

    response = client.delete(f"{URL}/{template.id}")

    assert response.status_code == 204
    assert client.get(f"{URL}/{template.id}").status_code == 404
    assert count_lines(db) == 0


def test_delete_an_unknown_id_is_a_404(client):
    response = client.delete(f"{URL}/{uuid.uuid4()}")

    assert response.status_code == 404


# --- Ownership scoping -------------------------------------------------------------
#
# La tabla no tiene `user_id`: el scoping sale del join contra `fiscal_identities`. Estos
# tests son los que prueban que ese join alcanza — que un modelo ajeno no aparece en la
# lista y no se puede leer, editar ni borrar por id.
#
# La escritura es el otro lado: un id de padre ajeno tiene que dar el mismo 422 que un id
# inexistente. La base no lo impide sola —la FK apunta a una fila que sí existe—, así que
# lo garantiza la validación del CRUD.


def other_pair(db, other_user):
    """Una identidad fiscal y un cliente del otro usuario."""
    return (
        factories.make_fiscal_identity(db, other_user.id),
        factories.make_customer(db, other_user.id),
    )


def test_list_excludes_another_users_templates(db, other_user, client, fiscal_identity, customer):
    factories.make_invoice_template(db, fiscal_identity, customer, name="Mine")
    their_identity, their_customer = other_pair(db, other_user)
    factories.make_invoice_template(db, their_identity, their_customer, name="Theirs")

    response = client.get(URL)

    assert response.status_code == 200
    assert {template["name"] for template in response.json()} == {"Mine"}


def test_get_another_users_template_is_404(db, other_user, client):
    their_identity, their_customer = other_pair(db, other_user)
    theirs = factories.make_invoice_template(db, their_identity, their_customer)

    response = client.get(f"{URL}/{theirs.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Modelo no encontrado"


def test_patch_another_users_template_is_404(db, other_user, client):
    their_identity, their_customer = other_pair(db, other_user)
    theirs = factories.make_invoice_template(db, their_identity, their_customer, name="Theirs")

    response = client.patch(f"{URL}/{theirs.id}", json={"name": "Hijacked"})

    assert response.status_code == 404
    db.refresh(theirs)
    assert theirs.name == "Theirs"


def test_delete_another_users_template_is_404(db, other_user, client):
    their_identity, their_customer = other_pair(db, other_user)
    theirs = factories.make_invoice_template(db, their_identity, their_customer)

    response = client.delete(f"{URL}/{theirs.id}")

    assert response.status_code == 404
    assert db.get(InvoiceTemplate, theirs.id) is not None


def test_create_with_another_users_customer_is_422(db, other_user, client, fiscal_identity):
    """Mismo 422 y mismo mensaje que un `customer_id` que no existe.

    Es el caso que la base no puede atajar: la FK apunta a una fila real, así que sin la
    validación del CRUD el modelo se crearía apuntando al cliente de otro. Y el mensaje es
    el de siempre a propósito: uno propio confirmaría que ese id existe.
    """
    their_customer = factories.make_customer(db, other_user.id)

    response = client.post(URL, json=payload(fiscal_identity.id, their_customer.id))

    assert response.status_code == 422
    assert response.json()["detail"] == "Cliente desconocido"


def test_create_with_another_users_fiscal_identity_is_422(db, other_user, client, customer):
    their_identity = factories.make_fiscal_identity(db, other_user.id)

    response = client.post(URL, json=payload(their_identity.id, customer.id))

    assert response.status_code == 422
    assert response.json()["detail"] == "Identidad fiscal desconocida"


def test_patch_into_another_users_customer_is_422(
    db, other_user, client, fiscal_identity, customer
):
    """El PATCH también valida: sin esto, el modelo se reapunta después de creado."""
    template = factories.make_invoice_template(db, fiscal_identity, customer)
    their_customer = factories.make_customer(db, other_user.id)

    response = client.patch(f"{URL}/{template.id}", json={"customer_id": str(their_customer.id)})

    assert response.status_code == 422
    assert response.json()["detail"] == "Cliente desconocido"
    db.refresh(template)
    assert template.customer_id == customer.id


# --- El texto del mail ----------------------------------------------------------------------
#
# El asunto y el cuerpo con los que se manda la factura emitida de este modelo. Son del plan
# Pro, y el chequeo vive en el router y no en el schema porque es una condición de la cuenta:
# el mismo JSON es válido o no según quién lo mande. Lo que sale al enviar lo prueba
# `test_emission.py`; acá se fija quién puede guardarlo.


def test_the_email_text_is_saved_and_read_back(client, fiscal_identity, customer):
    response = client.post(
        URL,
        json=payload(
            fiscal_identity.id,
            customer.id,
            email_subject="Tu factura del mes",
            email_body="Hola! Te mando la factura. Cualquier cosa avisame.",
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email_subject"] == "Tu factura del mes"
    assert body["email_body"] == "Hola! Te mando la factura. Cualquier cosa avisame."


def test_a_template_without_email_text_reads_back_as_null(client, fiscal_identity, customer):
    """`null` es "mandá el mail de FactuMov", que es lo que hacen todos los modelos de antes."""
    body = client.post(URL, json=payload(fiscal_identity.id, customer.id)).json()

    assert body["email_subject"] is None
    assert body["email_body"] is None


def test_a_blank_email_text_is_stored_as_no_text(client, fiscal_identity, customer):
    """Un `<textarea>` vacío manda `""`, no `null`, y las dos cosas significan lo mismo.

    Guardar el string vacío dejaría al modelo mandando facturas sin asunto y sin cuerpo, que
    no es lo que pidió nadie: quien borra el campo está pidiendo volver al texto de la app.
    """
    body = client.post(
        URL,
        json=payload(fiscal_identity.id, customer.id, email_subject="   ", email_body=""),
    ).json()

    assert body["email_subject"] is None
    assert body["email_body"] is None


def test_the_email_text_is_trimmed(client, fiscal_identity, customer):
    body = client.post(
        URL,
        json=payload(fiscal_identity.id, customer.id, email_subject="  Tu factura  "),
    ).json()

    assert body["email_subject"] == "Tu factura"


def test_a_subject_over_the_column_length_is_a_422(client, fiscal_identity, customer):
    """El tope lo pone el schema, así que el body se arma a mano.

    `payload()` construye el `InvoiceTemplateCreate` y lo serializa, o sea que un asunto
    demasiado largo explotaría en el test antes de llegar a HTTP — y lo que hay que fijar acá
    es el 422 que ve el frontend, no la excepción de Pydantic.
    """
    body = payload(fiscal_identity.id, customer.id)
    body["email_subject"] = "x" * 201

    assert client.post(URL, json=body).status_code == 422


def test_the_email_text_can_be_patched(client, db, fiscal_identity, customer):
    template = factories.make_invoice_template(db, fiscal_identity, customer)

    response = client.patch(
        f"{URL}/{template.id}", json={"email_subject": "Otro asunto", "email_body": "Otro texto"}
    )

    assert response.status_code == 200
    assert response.json()["email_subject"] == "Otro asunto"
    assert response.json()["email_body"] == "Otro texto"


def test_clearing_the_email_text_goes_back_to_the_default(client, db, fiscal_identity, customer):
    template = factories.make_invoice_template(
        db, fiscal_identity, customer, email_subject="Propio", email_body="Propio"
    )

    response = client.patch(f"{URL}/{template.id}", json={"email_subject": None, "email_body": ""})

    assert response.status_code == 200
    assert response.json()["email_subject"] is None
    assert response.json()["email_body"] is None


def test_a_patch_that_does_not_mention_the_email_text_leaves_it_alone(
    client, db, fiscal_identity, customer
):
    """`exclude_unset`: "no lo mandó" y "lo mandó en null" son cosas distintas."""
    template = factories.make_invoice_template(
        db, fiscal_identity, customer, email_subject="Propio", email_body="Propio"
    )

    response = client.patch(f"{URL}/{template.id}", json={"name": "Otro nombre"})

    assert response.status_code == 200
    assert response.json()["email_subject"] == "Propio"


def test_a_free_account_cannot_write_the_email_text(
    client, fiscal_identity, customer, free_plan
):
    response = client.post(
        URL, json=payload(fiscal_identity.id, customer.id, email_body="Mi texto")
    )

    # 402 y no 403: el permiso sobre sus propios datos lo tiene, lo que falta es el plan.
    assert response.status_code == 402
    assert "Pro" in response.json()["detail"]


def test_a_free_account_cannot_patch_the_email_text(
    client, db, fiscal_identity, customer, free_plan
):
    template = factories.make_invoice_template(db, fiscal_identity, customer)

    response = client.patch(f"{URL}/{template.id}", json={"email_body": "Mi texto"})

    assert response.status_code == 402
    db.refresh(template)
    assert template.email_body is None


def test_a_free_account_can_still_save_the_rest_of_the_template(
    client, db, fiscal_identity, customer, free_plan
):
    """El PATCH del formulario manda el objeto entero, textos vacíos incluidos.

    Sin la distinción entre "trae texto" y "lo trae vacío", un Free no podría guardar **ningún**
    cambio de ningún modelo: cada PATCH parecería un intento de personalizar el mail.
    """
    template = factories.make_invoice_template(db, fiscal_identity, customer)

    response = client.patch(
        f"{URL}/{template.id}",
        json={"name": "Otro nombre", "email_subject": None, "email_body": ""},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Otro nombre"


def test_a_free_account_can_clear_a_text_it_can_no_longer_edit(
    client, db, fiscal_identity, customer, free_plan
):
    """La salida del ex-Pro: borrarlo se permite siempre, porque deja el default en su lugar."""
    template = factories.make_invoice_template(
        db, fiscal_identity, customer, email_subject="Propio", email_body="Propio"
    )

    response = client.patch(
        f"{URL}/{template.id}", json={"email_subject": None, "email_body": None}
    )

    assert response.status_code == 200
    assert response.json()["email_subject"] is None
