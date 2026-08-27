"""The voucher letter is derived, not chosen.

These are pure-function tests plus one end-to-end guard through the router. The table itself
is the interesting part: it is the rule ARCA imposes, and getting one cell wrong produces a
plausible, wrong letter rather than an error — the invoice would be rejected at CAE time, or
worse, accepted and legally wrong.
"""

import pytest

from factumov.enums import CondicionIva, VoucherType
from factumov.exceptions import UndecidableVoucherTypeError
from factumov.services.voucher import voucher_type_for
from tests.factories import make_customer, make_fiscal_identity, make_template_create

# Every issuer/customer pair that the API can produce, and the single letter it yields. The
# issuer can never be FINAL — `FiscalIdentityCreate` rejects it — so that row is not here; it
# has its own test below.
COMBINATIONS = [
    (CondicionIva.INSCRIPTO, CondicionIva.INSCRIPTO, VoucherType.A),
    (CondicionIva.INSCRIPTO, CondicionIva.MONOTRIBUTO, VoucherType.B),
    (CondicionIva.INSCRIPTO, CondicionIva.EXENTO, VoucherType.B),
    (CondicionIva.INSCRIPTO, CondicionIva.FINAL, VoucherType.B),
    (CondicionIva.MONOTRIBUTO, CondicionIva.INSCRIPTO, VoucherType.C),
    (CondicionIva.MONOTRIBUTO, CondicionIva.MONOTRIBUTO, VoucherType.C),
    (CondicionIva.MONOTRIBUTO, CondicionIva.EXENTO, VoucherType.C),
    (CondicionIva.MONOTRIBUTO, CondicionIva.FINAL, VoucherType.C),
    (CondicionIva.EXENTO, CondicionIva.INSCRIPTO, VoucherType.C),
    (CondicionIva.EXENTO, CondicionIva.MONOTRIBUTO, VoucherType.C),
    (CondicionIva.EXENTO, CondicionIva.EXENTO, VoucherType.C),
    (CondicionIva.EXENTO, CondicionIva.FINAL, VoucherType.C),
]


@pytest.mark.parametrize("issuer, customer, expected", COMBINATIONS)
def test_the_letter_is_a_function_of_the_two_conditions(issuer, customer, expected):
    assert voucher_type_for(issuer, customer) == expected


def test_only_an_inscripto_selling_to_an_inscripto_gets_an_a():
    """The A is the only letter that discriminates IVA, and only a registered taxpayer can
    take that IVA as a credit — so it is also the only pair that produces one."""
    with_an_a = [pair for *pair, letter in COMBINATIONS if letter == VoucherType.A]

    assert with_an_a == [[CondicionIva.INSCRIPTO, CondicionIva.INSCRIPTO]]


def test_no_pair_ever_yields_a_credit_note():
    """FactuMov does not offer credit notes: it automates the voucher that repeats every
    month, and nobody credits their customers monthly. Their absence is what makes the
    intersection a single letter, so a stray NC in either table would break the derivation
    itself — not just add an unwanted option.
    """
    letters = {letter for *_, letter in COMBINATIONS}

    assert letters == {VoucherType.A, VoucherType.B, VoucherType.C}


def test_a_consumidor_final_issuer_has_no_letter_at_all():
    """Unreachable through the API — `FiscalIdentityCreate` returns 422 for it. The check
    exists so that loosening that validator fails loudly instead of silently producing a
    letter nobody can emit."""
    with pytest.raises(UndecidableVoucherTypeError):
        voucher_type_for(CondicionIva.FINAL, CondicionIva.INSCRIPTO)


def test_the_router_derives_the_letter_from_the_two_parents(client, db, user):
    """The end-to-end guard: nothing about the letter is in the request body, and two
    templates that differ only in their customer's IVA condition come back with different
    letters."""
    fiscal_identity = make_fiscal_identity(db, user.id, condicion_iva=CondicionIva.INSCRIPTO)
    inscripto = make_customer(db, user.id, condicion_iva=CondicionIva.INSCRIPTO)
    final = make_customer(db, user.id, condicion_iva=CondicionIva.FINAL)

    def create(name, customer):
        body = make_template_create(fiscal_identity.id, customer.id, name=name)
        return client.post("/invoice-templates", json=body.model_dump(mode="json"))

    to_inscripto = create("A un inscripto", inscripto)
    to_final = create("A un consumidor final", final)

    assert to_inscripto.status_code == 201
    assert to_final.status_code == 201
    assert to_inscripto.json()["voucher_type"] == "A"
    assert to_final.json()["voucher_type"] == "B"


def test_the_letter_follows_the_customer_when_it_changes(client, db, user):
    """The reason the column is gone. A customer who registers for IVA turns every template
    that bills them from a B into an A; a stored letter would keep saying B until somebody
    noticed, and ARCA would reject the CAE — or accept a legally wrong invoice.
    """
    fiscal_identity = make_fiscal_identity(db, user.id, condicion_iva=CondicionIva.INSCRIPTO)
    customer = make_customer(db, user.id, condicion_iva=CondicionIva.MONOTRIBUTO)
    body = make_template_create(fiscal_identity.id, customer.id)
    created = client.post("/invoice-templates", json=body.model_dump(mode="json"))

    assert created.json()["voucher_type"] == "B"

    promoted = client.patch(
        f"/customers/{customer.id}", json={"condicion_iva": CondicionIva.INSCRIPTO.value}
    )

    assert promoted.status_code == 200
    reread = client.get(f"/invoice-templates/{created.json()['id']}")

    assert reread.json()["voucher_type"] == "A"


def test_the_letter_cannot_be_sent_by_the_client(client, fiscal_identity, customer):
    """Both fixtures are inscriptos, so the derivation says A. Asking for a B in the body
    changes nothing: the field is not part of the write schema, and Pydantic drops it rather
    than letting the client contradict the rule."""
    body = make_template_create(fiscal_identity.id, customer.id).model_dump(mode="json")
    body["voucher_type"] = "B"

    response = client.post("/invoice-templates", json=body)

    assert response.status_code == 201
    assert response.json()["voucher_type"] == "A"
