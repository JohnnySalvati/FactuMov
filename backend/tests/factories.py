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

from factumov.enums import (
    Concepto,
    CondicionIva,
    DocType,
    IvaAliquot,
    SubscriptionStatus,
    VoucherType,
)
from factumov.models.arca_ticket import ArcaTicket
from factumov.models.balance360_connection import Balance360Connection
from factumov.models.customer import Customer
from factumov.models.email_confirmation import EmailConfirmation
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.models.invoice import Invoice
from factumov.models.invoice_line import InvoiceLine
from factumov.models.invoice_template import InvoiceTemplate
from factumov.models.invoice_template_line import InvoiceTemplateLine
from factumov.models.password_reset import PasswordReset
from factumov.models.subscription import Subscription
from factumov.models.user import User
from factumov.models.user_session import UserSession
from factumov.schemas.invoice_template import InvoiceTemplateCreate
from factumov.schemas.invoice_template_line import InvoiceTemplateLineCreate
from factumov.services import secrets as secrets_service
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
    issued_at=None,
):
    """Una fila de `arca_tickets`. Es la única tabla sin dueño: el ticket es del certificado.

    `expires_at` por default a doce horas, que es lo que dura un TA de verdad. Los tests del
    vencimiento lo pasan en el pasado, que es más simple que parchear un reloj — el mismo
    truco que `make_user_session`.

    `issued_at` por default a ahora, o sea recién emitido. Los tests de la edad lo pasan en el
    pasado **dejando `expires_at` donde está**, que es justo la combinación que importa: un
    ticket vigente y viejo a la vez, que es el que miente sobre las relaciones.
    """
    n = next(_sequence)
    ticket = ArcaTicket(
        env=env,
        service=service,
        token=token or f"token{n}",
        sign=sign or f"sign{n}",
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=12),
        issued_at=issued_at or datetime.now(UTC),
    )
    db.add(ticket)
    db.flush()
    return ticket


def make_invoice(
    db,
    fiscal_identity,
    customer,
    voucher_type=VoucherType.A,
    pos=1,
    number=None,
    lines=None,
    net_total=Decimal("1000.00"),
    iva_total=Decimal("210.00"),
    total=Decimal("1210.00"),
):
    """Una factura ya emitida, escrita directo por el ORM.

    No pasa por `services/emission.py` a propósito: emitir sale a ARCA, y lo que estos tests
    necesitan es el resultado —una fila con CAE— y no el camino. Recibe la identidad fiscal y
    el cliente enteros y no sus ids porque copia de ellos las columnas del emisor y del
    receptor, que es justamente lo que hace la emisión de verdad.
    """
    if lines is None:
        lines = [
            InvoiceLine(
                position=0,
                description="Desarrollo",
                quantity=Decimal("1"),
                unit_price=Decimal("1000.00"),
                iva_aliquot=IvaAliquot.standard,
            )
        ]
    invoice = Invoice(
        fiscal_identity_id=fiscal_identity.id,
        customer_id=customer.id,
        voucher_type=voucher_type,
        pos=pos,
        number=number if number is not None else next(_sequence),
        date=datetime.now(UTC).date(),
        concepto=Concepto.products,
        cae="86350816969306",
        cae_expiry=datetime.now(UTC).date() + timedelta(days=10),
        net_total=net_total,
        iva_total=iva_total,
        total=total,
        issuer_name=fiscal_identity.name,
        issuer_tax_id=fiscal_identity.tax_id,
        issuer_condicion_iva=fiscal_identity.condicion_iva,
        issuer_address=fiscal_identity.address,
        issuer_iibb=fiscal_identity.iibb,
        issuer_start_date=fiscal_identity.start_date,
        customer_name=customer.name,
        customer_doc_type=customer.doc_type,
        customer_doc_number=customer.doc_number,
        customer_condicion_iva=customer.condicion_iva,
        customer_address=customer.address,
        lines=lines,
    )
    db.add(invoice)
    db.flush()
    return invoice


def make_subscription(
    db,
    user_id,
    status=SubscriptionStatus.TRIALING,
    current_period_end=None,
    billing_interval=None,
    provider=None,
    canceled_at=None,
):
    """La suscripción de un usuario. Por default, el trial recién empezado.

    Ese default es el estado en el que la app deja a toda cuenta nueva, así que el fixture
    `user` lo usa tal cual y la suite entera corre como Pro — que es lo que corresponde: casi
    ningún test de este proyecto es sobre el plan, y hacerlos correr en Free los habría hecho
    fallar de a montones el día que se agregue un límite más.

    `current_period_end` por default a treinta días adelante. Los tests del vencimiento lo
    pasan en el pasado, que es más simple que parchear un reloj — el mismo truco que
    `make_user_session` y `make_arca_ticket`.
    """
    subscription = Subscription(
        user_id=user_id,
        status=status,
        current_period_end=(
            current_period_end
            if current_period_end is not None
            else datetime.now(UTC) + timedelta(days=30)
        ),
        billing_interval=billing_interval,
        provider=provider,
        canceled_at=canceled_at,
    )
    db.add(subscription)
    db.flush()
    return subscription


def make_balance360_connection(
    db,
    user_id,
    token="b360_token_de_prueba",
    auto_register=True,
    verified_at=None,
):
    """La conexión con Balance360, con el token cifrado de verdad.

    Cifra en vez de escribir cualquier cosa en `encrypted_token` porque el camino que estos
    tests ejercitan lo descifra: un valor inventado fallaría en `secrets.decrypt` y el test
    pasaría —o fallaría— por un motivo que no es el que está probando.
    """
    connection = Balance360Connection(
        user_id=user_id,
        encrypted_token=secrets_service.encrypt(token),
        token_hint=token[-4:],
        auto_register=auto_register,
        verified_at=verified_at,
    )
    db.add(connection)
    db.flush()
    return connection
