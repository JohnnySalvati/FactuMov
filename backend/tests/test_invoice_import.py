"""Tests for POST /invoice-templates/import.

The endpoint parses an uploaded PDF and answers with an `InvoiceTemplateDraft`. It reads
the database to resolve the issuer and the customer, but writes nothing: the draft is a
proposal the user reviews and then confirms with `POST /invoice-templates`.
"""

from pathlib import Path

from sqlalchemy import func, select

from factumov.enums import DocType, IvaAliquot, VoucherType
from factumov.models.customer import Customer
from factumov.routers import invoice_template
from tests import factories

SAMPLES = Path(__file__).parent / "samples"

# Factura C, punto de venta 1, one exempt line, and a billed period — which is what makes
# the expected `concepto` "services" rather than "products".
SAMPLE = "20206205297_011_00001_00000205.pdf"
ISSUER_TAX_ID = "20206205297"
CUSTOMER_DOC_NUMBER = "30714597066"

# Factura B, punto de venta 10, two lines at 21%. B prints no aliquot column, so the rate
# is deduced from the letter.
SAMPLE_B = "30714597066_006_00010_00000055.pdf"

# Factura A, the only letter that discriminates IVA per line: its rate is read off the
# printed column rather than deduced.
SAMPLE_A = "20182810674_001_00002_00000134.pdf"

NOT_A_PDF = b"\xff\xd8\xff\xe0 this is the start of a jpeg"
UNREADABLE_PDF = b"%PDF-1.4 truncated before anything readable"


def post_import(client, filename=SAMPLE, content=None, content_type="application/pdf"):
    """Upload a sample PDF — or arbitrary bytes — as multipart/form-data.

    The key in `files` has to match the endpoint's parameter name, so renaming the
    parameter breaks this call rather than silently sending an unread part.

    `content` replaces the body without touching the declared type, which is what lets a
    guard test send something that is not a PDF while still claiming to be one.
    """
    file_bytes = (SAMPLES / filename).read_bytes() if content is None else content
    return client.post(
        "/invoice-templates/import",
        files={"file": (filename, file_bytes, content_type)},
    )


def count_customers(db):
    return db.execute(select(func.count()).select_from(Customer)).scalar()


def test_import_resolves_the_ids_of_an_issuer_and_customer_already_stored(user, client, db):
    fiscal_identity = factories.make_fiscal_identity(db, user.id, tax_id=ISSUER_TAX_ID)
    customer = factories.make_customer(
        db, user.id, doc_type=DocType.CUIT, doc_number=CUSTOMER_DOC_NUMBER
    )

    response = post_import(client)

    assert response.status_code == 200
    draft = response.json()

    assert draft["fiscal_identity_id"] == str(fiscal_identity.id)
    assert draft["customer_id"] == str(customer.id)
    assert draft["issuer_tax_id"] == ISSUER_TAX_ID

    # The PDF carries no template name — the user picks one in the editor.
    assert draft["name"] is None

    assert draft["pos"] == 1
    assert draft["concepto"] == "services"

    # The parsed customer travels even though the row already exists, so the editor can
    # show what the PDF says next to what is stored and let the user reconcile the two.
    assert draft["customer"]["name"] == "M & G TECHNOLOGY S.R.L."
    assert draft["customer"]["doc_type"] == DocType.CUIT.value
    assert draft["customer"]["doc_number"] == CUSTOMER_DOC_NUMBER

    # Decimals cross the wire as strings, which is why the scale survives: "1.00", not 1.0.
    assert draft["lines"] == [
        {
            "description": "Alquiler local 11 de septiembre 3900",
            "quantity": "1.00",
            "unit_price": "2805000.00",
            "iva_aliquot": IvaAliquot.exempt.value,
        }
    ]

    # The endpoint reads; it must not write. If it ever reached for `update_or_create`,
    # importing the same PDF twice would quietly fork the customer's history.
    assert count_customers(db) == 1


def test_import_leaves_both_ids_empty_when_neither_party_is_stored(client, db):
    """A first import: nothing to resolve, but everything parsed still travels.

    This is the ordinary case for a new user, and the draft has to carry enough for the
    editor to offer creating both rows — so the ids being None does not make the rest of
    the payload empty.
    """
    response = post_import(client)

    assert response.status_code == 200
    draft = response.json()

    assert draft["fiscal_identity_id"] is None
    assert draft["customer_id"] is None

    assert draft["issuer_tax_id"] == ISSUER_TAX_ID
    assert draft["customer"]["doc_number"] == CUSTOMER_DOC_NUMBER
    assert draft["customer"]["name"] == "M & G TECHNOLOGY S.R.L."
    assert draft["lines"]

    assert count_customers(db) == 0


def test_import_reads_a_type_b_invoice_with_two_lines(client):
    """B deduces 21% from the letter, and both lines carry it.

    The descriptions also show the parser reassembled rows that ARCA wrapped over several
    printed lines, which is where a two-line invoice differs from a one-line one.
    """
    response = post_import(client, filename=SAMPLE_B)

    assert response.status_code == 200
    draft = response.json()

    assert draft["pos"] == 10
    assert draft["customer"]["doc_number"] == "30535621159"

    assert draft["lines"] == [
        {
            "description": "Almuerzos consumidos desde el 29/06/26 al 03/07/26 "
            "OC 4701183101 Usuario Responsable: Lorena Del Valle Ferreyra",
            "quantity": "169.00",
            "unit_price": "28000.00",
            "iva_aliquot": IvaAliquot.standard.value,
        },
        {
            "description": "Almuerzos consumidos desde el 06/07/26 al 10/07/26 "
            "OC 4701183101 Usuario Responsable: Lorena Del Valle Ferreyra",
            "quantity": "109.00",
            "unit_price": "28000.00",
            "iva_aliquot": IvaAliquot.standard.value,
        },
    ]


def test_import_reads_a_type_a_invoice(client):
    """A is the letter whose rate is read off the line instead of deduced.

    It also uses a different item layout and a different label for the receptor's address,
    so this is the end-to-end guard that both survive `build_draft` and come out as JSON.
    """
    response = post_import(client, filename=SAMPLE_A)

    assert response.status_code == 200
    draft = response.json()

    assert draft["pos"] == 2
    assert draft["issuer_tax_id"] == "20182810674"

    assert draft["customer"]["doc_number"] == "23105048009"
    assert draft["customer"]["address"] == "Hubac 4686 - Capital Federal, Ciudad de Buenos Aires"

    assert [line["iva_aliquot"] for line in draft["lines"]] == [
        IvaAliquot.standard.value,
        IvaAliquot.standard.value,
    ]
    assert [line["unit_price"] for line in draft["lines"]] == ["35000.00", "15000.00"]


def test_import_carries_the_letter_of_the_parsed_invoice(client):
    """La letra del PDF viaja en el draft, y no se guarda en ningún lado.

    Es lo que le dice al editor **cómo leer el `unit_price` que viene en el draft**: en A es
    neto y en B y C trae el IVA adentro. Sin ella, un draft de una A cuyo receptor todavía no
    está en la cartera —o sea sin par emisor/cliente del que deducir la letra— se sembraría en
    la columna equivocada y al guardarlo el precio quedaría un 21% corrido.

    Las tres muestras son las tres letras, que es justo lo que hace falta cubrir: la C es la
    del default de `post_import`.
    """
    assert post_import(client).json()["voucher_type"] == VoucherType.C.value
    assert post_import(client, filename=SAMPLE_B).json()["voucher_type"] == VoucherType.B.value
    assert post_import(client, filename=SAMPLE_A).json()["voucher_type"] == VoucherType.A.value


def test_import_ignores_a_customer_whose_doc_type_differs(user, client, db):
    """The lookup keys on the pair, not on the number alone.

    `uq_customers_user_id_doc_type_doc_number` covers both columns, so the same digits can legally
    exist under two doc types. Matching on the number alone would attach the draft to the
    wrong row while looking entirely correct.
    """
    factories.make_customer(db, user.id, doc_type=DocType.DNI, doc_number=CUSTOMER_DOC_NUMBER)

    response = post_import(client)

    assert response.status_code == 200
    draft = response.json()

    assert draft["customer_id"] is None

    # The parsed receptor still travels, so the editor can offer to store it properly.
    assert draft["customer"]["doc_number"] == CUSTOMER_DOC_NUMBER
    assert draft["customer"]["doc_type"] == DocType.CUIT.value


def test_import_rejects_an_upload_that_is_not_a_pdf(client):
    """415 is decided on the magic bytes, not on the declared content type.

    The upload claims `application/pdf` on purpose: the header is what the file says about
    itself, while the content type is only what the client claims about it.
    """
    response = post_import(client, content=NOT_A_PDF)

    assert response.status_code == 415


def test_import_accepts_a_pdf_it_cannot_read_and_answers_an_empty_draft(client):
    """An unreadable PDF is not the same situation as a file of the wrong type.

    A scanned or corrupt invoice really is a PDF, so it earns a 200 with an empty draft
    and the UI offers manual entry. Folding this into the 415 above would refuse a
    document the user can still work with by hand.
    """
    response = post_import(client, content=UNREADABLE_PDF)

    assert response.status_code == 200
    draft = response.json()

    assert draft["lines"] == []
    assert draft["fiscal_identity_id"] is None


def test_import_rejects_an_upload_over_the_size_limit(client, monkeypatch):
    """413 fires before the file is parsed.

    The limit is patched rather than exercised at its real 10 MB, so the branch is covered
    without the suite carrying a 10 MB payload — the value itself is policy, not behaviour.
    Patching works only because the endpoint resolves the constant as a module global at
    call time; as a parameter default it would read a copy this never touches.
    """
    monkeypatch.setattr(invoice_template, "MAX_UPLOAD_BYTES", 100)

    response = post_import(client)

    assert response.status_code == 413


def test_import_requires_the_file_field(client):
    """No file at all is a validation error, answered before the endpoint body runs.

    A wrong field name produces this same response, so it doubles as a guard against the
    helper above drifting away from the endpoint's parameter name.
    """
    response = client.post("/invoice-templates/import")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "file"]


# --- Ownership scoping -------------------------------------------------------------
#
# Los dos lookups del endpoint son de solo lectura, y por eso el bug era silencioso: nadie
# escribía nada mal, pero el draft volvía con el id de una fila ajena. El usuario lo
# confirmaba en el editor y el modelo que se guardaba apuntaba al cliente de otro. Un
# lookup sin scopear delata además que ese documento ya está cargado por alguien.


def test_import_ignores_another_users_customer(other_user, client, db):
    factories.make_customer(
        db, other_user.id, doc_type=DocType.CUIT, doc_number=CUSTOMER_DOC_NUMBER
    )

    response = post_import(client)

    assert response.status_code == 200
    draft = response.json()

    # Ni el id ajeno ni ninguna otra señal de que esa fila existe: para este usuario, el
    # cliente todavía no está cargado, que es exactamente lo mismo que vería si no
    # existiera en absoluto.
    assert draft["customer_id"] is None
    assert draft["customer"]["doc_number"] == CUSTOMER_DOC_NUMBER


def test_import_ignores_another_users_fiscal_identity(other_user, client, db):
    factories.make_fiscal_identity(db, other_user.id, tax_id=ISSUER_TAX_ID)

    response = post_import(client)

    assert response.status_code == 200
    draft = response.json()

    assert draft["fiscal_identity_id"] is None
    assert draft["issuer_tax_id"] == ISSUER_TAX_ID
