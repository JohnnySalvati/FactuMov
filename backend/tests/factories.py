"""Arrangement helpers for the test suite.

These build rows directly through the ORM instead of going through `crud/`, so a bug in
one module's CRUD fails only that module's tests. The CRUD is the *act* under test; these
functions only set up the *arrangement*.

Unique columns (`fiscal_identities.name`, `fiscal_identities.tax_id`,
`customers.doc_number`) get their defaults from a module-level counter, so calling the same
factory twice inside one test does not collide. Those constraints are per-owner since the
ownership-scoping unit, so the counter is now belt and braces rather than the only thing
keeping two rows apart.

`make_fiscal_identity` and `make_customer` take `user_id` as a required argument rather
than defaulting to a freshly created user. Defaulting would be shorter to call and would
quietly hand a test's identity and its customer two different owners, and the failure that
follows — `UnknownCustomerError` out of a template create — points nowhere near the cause.
`make_invoice_template` needs no owner of its own: it reads one off the fiscal identity.

Neither template factory takes a `voucher_type`: the letter is derived from the issuer's and
the customer's IVA conditions, so a test that wants a particular letter sets those conditions
on the parents — see `services/voucher.py` for the table.
"""

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from factumov.enums import Concepto, CondicionIva, DocType, IvaAliquot
from factumov.models.arca_ticket import ArcaTicket
from factumov.models.customer import Customer
from factumov.models.email_confirmation import EmailConfirmation
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.models.invoice_template import InvoiceTemplate
from factumov.models.invoice_template_line import InvoiceTemplateLine
from factumov.models.password_reset import PasswordReset
from factumov.models.user import User
from factumov.models.user_session import UserSession
from factumov.schemas.invoice_template import InvoiceTemplateCreate
from factumov.schemas.invoice_template_line import InvoiceTemplateLineCreate
from factumov.services.security import hash_opaque_token, hash_password

_sequence = itertools.count(1)
# Pública: los tests de login la mandan en el body. El hash se calcula una sola vez al
# importar el módulo — con los parámetros recomendados de argon2, hashear por usuario
# duplicaría el tiempo de la suite.
PASSWORD = "onePassword"
PASSWORD_HASHED = hash_password(PASSWORD)


def make_fiscal_identity(db, user_id, name=None, tax_id=None, condicion_iva=CondicionIva.INSCRIPTO):
    n = next(_sequence)
    fiscal_identity = FiscalIdentity(
        user_id=user_id,
        name=f"Fiscal Identity {n}" if name is None else name,
        tax_id=f"20{n:09d}" if tax_id is None else tax_id,
        condicion_iva=condicion_iva,
    )
    db.add(fiscal_identity)
    db.flush()
    return fiscal_identity


def make_customer(
    db,
    user_id,
    name=None,
    doc_number: str = "",
    doc_type=DocType.CUIT,
    condicion_iva=CondicionIva.INSCRIPTO,
):
    n = next(_sequence)
    customer = Customer(
        user_id=user_id,
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


def make_user(
    db,
    email=None,
    email_confirmed_at=None,
    hashed_password=PASSWORD_HASHED,
    is_active=True,
):
    n = next(_sequence)
    user = User(
        email=f"email{n}@cucu.com" if email is None else email,
        email_confirmed_at=email_confirmed_at,
        hashed_password=hashed_password,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def make_user_session(
    db,
    user_id=None,
    raw_token=None,
    expires_at=None,
    revoked_at=None,
):
    n = next(_sequence)
    user_session = UserSession(
        user_id=user_id or make_user(db).id,
        token_hash=hash_opaque_token(f"token{n}" if raw_token is None else raw_token),
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
        revoked_at=revoked_at,
    )
    db.add(user_session)
    db.flush()
    return user_session


def make_email_confirmation(
    db,
    user_id=None,
    raw_token=None,
    expires_at=None,
    confirmed_at=None,
):
    n = next(_sequence)
    confirmation = EmailConfirmation(
        user_id=user_id or make_user(db).id,
        token_hash=hash_opaque_token(f"confirmation{n}" if raw_token is None else raw_token),
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=24),
        confirmed_at=confirmed_at,
    )
    db.add(confirmation)
    db.flush()
    return confirmation


def make_password_reset(
    db,
    user_id=None,
    raw_token=None,
    expires_at=None,
    used_at=None,
):
    n = next(_sequence)
    reset = PasswordReset(
        user_id=user_id or make_user(db).id,
        token_hash=hash_opaque_token(f"reset{n}" if raw_token is None else raw_token),
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
        used_at=used_at,
    )
    db.add(reset)
    db.flush()
    return reset


def make_arca_ticket(
    db,
    env="homo",
    service="wsfe",
    token=None,
    sign=None,
    expires_at=None,
):
    """Una fila de `arca_tickets`. Es la única tabla sin dueño: el ticket es del certificado.

    `expires_at` por default a doce horas, que es lo que dura un TA de verdad. Los tests del
    vencimiento lo pasan en el pasado, que es más simple que parchear un reloj — el mismo
    truco que `make_user_session`.
    """
    n = next(_sequence)
    ticket = ArcaTicket(
        env=env,
        service=service,
        token=token or f"token{n}",
        sign=sign or f"sign{n}",
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=12),
    )
    db.add(ticket)
    db.flush()
    return ticket
