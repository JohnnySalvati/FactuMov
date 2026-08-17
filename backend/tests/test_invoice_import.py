"""Tests for POST /invoice-templates/import.

The endpoint parses an uploaded PDF and answers with an `InvoiceTemplateDraft`. It reads
the database to resolve the issuer and the customer, but writes nothing: the draft is a
proposal the user reviews and then confirms with `POST /invoice-templates`.
"""

from pathlib import Path

from sqlalchemy import func, select

from factumov.enums import DocType, IvaAliquot
from factumov.models.customer import Customer
from tests import factories

SAMPLES = Path(__file__).parent / "samples"

# Factura C, punto de venta 1, one exempt line, and a billed period — which is what makes
# the expected `concepto` "services" rather than "products".
SAMPLE = "20206205297_011_00001_00000205.pdf"
ISSUER_TAX_ID = "20206205297"
CUSTOMER_DOC_NUMBER = "30714597066"


def post_import(client, filename=SAMPLE):
    """Upload one of the sample PDFs as multipart/form-data.

    The key in `files` has to match the endpoint's parameter name, so renaming the
    parameter breaks this call rather than silently sending an unread part.
    """
    file_bytes = (SAMPLES / filename).read_bytes()
    return client.post(
        "/invoice-templates/import",
        files={"file": (filename, file_bytes, "application/pdf")},
    )


def count_customers(db):
    return db.execute(select(func.count()).select_from(Customer)).scalar()


def test_import_resolves_the_ids_of_an_issuer_and_customer_already_stored(client, db):
    fiscal_identity = factories.make_fiscal_identity(db, tax_id=ISSUER_TAX_ID)
    customer = factories.make_customer(db, doc_type=DocType.CUIT, doc_number=CUSTOMER_DOC_NUMBER)

    response = post_import(client)

    assert response.status_code == 200
    draft = response.json()

    assert draft["fiscal_identity_id"] == str(fiscal_identity.id)
    assert draft["customer_id"] == str(customer.id)
    assert draft["issuer_tax_id"] == ISSUER_TAX_ID

    # The PDF carries no template name — the user picks one in the editor.
    assert draft["name"] is None

    assert draft["voucher_type"] == "C"
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
