"""El plan de la cuenta: `services/subscription.py`, `GET /subscription` y los dos límites.

Dos mitades. La primera son tests de función pura sobre `is_pro`, que es donde vive la
política del acceso; la segunda ejercita los dos endpoints que cortan —el alta de identidad
fiscal y la emisión— por HTTP, porque lo que hay que fijar ahí es el 402 y su texto.

**Ninguno emite nada**, igual que `test_emission.py`: WSFE está mockeado y el que llega al
cupo lleno ni siquiera lo alcanza, que es justamente lo que uno de los tests afirma.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from factumov.crud import subscription as subscription_crud
from factumov.enums import BillingInterval, BillingProvider, CondicionIva, SubscriptionStatus
from factumov.services import arca
from factumov.services import subscription as subscription_service
from tests.factories import (
    make_customer,
    make_fiscal_identity,
    make_invoice,
    make_invoice_template,
    make_subscription,
    make_user,
)

# --- is_pro: la política del acceso ---------------------------------------------------------


def subscription_of(status, days_from_now):
    """Una suscripción suelta, sin base: `is_pro` no la necesita."""
    return SimpleNamespace(
        status=status, current_period_end=datetime.now(UTC) + timedelta(days=days_from_now)
    )


def test_a_running_trial_is_pro():
    assert subscription_service.is_pro(subscription_of(SubscriptionStatus.TRIALING, 5))


def test_an_expired_trial_is_not_pro():
    assert not subscription_service.is_pro(subscription_of(SubscriptionStatus.TRIALING, -1))


def test_an_expired_trial_gets_no_grace():
    """Los días de gracia son para el cobro que llega tarde, no para estirar la prueba.

    Sumárselos al trial haría que treinta días de prueba fueran cuarenta, que es una decisión
    de producto distinta tomada por accidente.
    """
    barely_expired = -1
    assert not subscription_service.is_pro(
        subscription_of(SubscriptionStatus.TRIALING, barely_expired)
    )


def test_an_active_subscription_is_pro():
    assert subscription_service.is_pro(subscription_of(SubscriptionStatus.ACTIVE, 12))


def test_a_failed_charge_keeps_access_during_the_grace_window():
    """Las tarjetas se vencen y se reemiten: cortar al primer rechazo pierde al que sí paga."""
    inside_grace = -(subscription_service.PAST_DUE_GRACE_DAYS - 1)
    assert subscription_service.is_pro(
        subscription_of(SubscriptionStatus.PAST_DUE, inside_grace)
    )


def test_a_failed_charge_stops_being_pro_after_the_grace_window():
    past_grace = -(subscription_service.PAST_DUE_GRACE_DAYS + 1)
    assert not subscription_service.is_pro(subscription_of(SubscriptionStatus.PAST_DUE, past_grace))


def test_a_cancelled_subscription_keeps_the_period_it_already_paid():
    """Dar de baja el 3 con el mes pago hasta el 28 no devuelve el mes: se termina de usar."""
    assert subscription_service.is_pro(subscription_of(SubscriptionStatus.CANCELED, 25))


def test_a_cancelled_subscription_gets_no_grace():
    """La gracia cubre un cobro que puede llegar tarde. Del que se fue no va a llegar ninguno."""
    inside_grace = -(subscription_service.PAST_DUE_GRACE_DAYS - 1)
    assert not subscription_service.is_pro(
        subscription_of(SubscriptionStatus.CANCELED, inside_grace)
    )


def test_no_subscription_at_all_is_free():
    assert not subscription_service.is_pro(None)


# --- El trial nace con la cuenta ------------------------------------------------------------


def test_registering_starts_a_trial(anonymous_client, db):
    response = anonymous_client.post(
        "/auth/register", json={"email": "nueva@cucu.com", "password": "unaPassword"}
    )
    assert response.status_code == 202

    from factumov.crud import user as user_crud

    registered = user_crud.get_by_email(db, "nueva@cucu.com")
    subscription = subscription_crud.get_for_user(db, registered.id)
    assert subscription.status is SubscriptionStatus.TRIALING
    assert subscription_service.is_pro(subscription)


def test_registering_twice_does_not_hand_out_a_second_trial(anonymous_client, db, user):
    """Volver a registrar una dirección que ya existe no es alguien registrándose.

    Sin el guard, el trial se renovaría con un POST y sería una suscripción Pro infinita y
    gratis. El unique de `user_id` lo atajaría con un 500, que es la peor forma de atajarlo.
    """
    before = subscription_crud.get_for_user(db, user.id).current_period_end

    response = anonymous_client.post(
        "/auth/register", json={"email": user.email, "password": "unaPassword"}
    )

    assert response.status_code == 202
    assert subscription_crud.get_for_user(db, user.id).current_period_end == before


# --- El contador del mes --------------------------------------------------------------------


def test_the_count_only_sees_this_users_invoices(db, user, other_user):
    """El scoping sale del join contra `fiscal_identities`: `invoices` no lleva `user_id`."""
    theirs = make_fiscal_identity(db, other_user.id)
    make_invoice(db, theirs, make_customer(db, other_user.id))

    assert subscription_service.count_invoices_this_month(db, user.id, datetime.now(UTC)) == 0


def test_the_count_goes_by_when_it_was_emitted_not_by_the_voucher_date(db, user, fiscal_identity):
    """Fechar el comprobante para atrás no devuelve cupo.

    La fecha del comprobante la elige el usuario dentro de la ventana que ARCA permite, así
    que contar por ella sería dejar el límite abierto con un campo del formulario. El cupo
    mide uso del servicio, y eso lo dice `created_at`.
    """
    invoice = make_invoice(db, fiscal_identity, make_customer(db, user.id))
    invoice.date = datetime.now(UTC).date() - timedelta(days=40)
    db.flush()

    assert subscription_service.count_invoices_this_month(db, user.id, datetime.now(UTC)) == 1


# --- GET /subscription ----------------------------------------------------------------------


def test_a_trialing_account_reports_no_limits(client):
    body = client.get("/subscription").json()

    assert body["is_pro"] is True
    assert body["status"] == "trialing"
    # `null` y no cero: la ausencia de límite se lee en la ausencia del número.
    assert body["invoices_limit"] is None
    assert body["fiscal_identities_limit"] is None
    assert body["voice_enabled"] is True


def test_a_free_account_reports_both_limits(client, free_plan):
    body = client.get("/subscription").json()

    assert body["is_pro"] is False
    assert body["invoices_limit"] == subscription_service.FREE_MONTHLY_INVOICES
    assert body["fiscal_identities_limit"] == subscription_service.FREE_FISCAL_IDENTITIES
    assert body["voice_enabled"] is False
    # Lo lee el editor del modelo para ofrecer los dos campos del mail o el aviso de Pro. Qué
    # texto sale al enviar no se decide con esto sino con el `Entitlements` del envío — ver
    # `test_emission.py`.
    assert body["custom_email_enabled"] is False


def test_the_usage_counters_come_from_the_rows(client, db, user, fiscal_identity, free_plan):
    make_invoice(db, fiscal_identity, make_customer(db, user.id))

    body = client.get("/subscription").json()

    assert body["invoices_used"] == 1
    assert body["fiscal_identities_used"] == 1
    assert body["can_emit"] is True


def test_a_free_account_that_spent_its_quota_cannot_emit(
    client, db, user, fiscal_identity, free_plan
):
    customer = make_customer(db, user.id)
    for _ in range(subscription_service.FREE_MONTHLY_INVOICES):
        make_invoice(db, fiscal_identity, customer)

    body = client.get("/subscription").json()

    assert body["invoices_used"] == subscription_service.FREE_MONTHLY_INVOICES
    assert body["can_emit"] is False


def test_the_subscription_needs_a_session(anonymous_client):
    assert anonymous_client.get("/subscription").status_code == 401


def test_an_account_without_a_subscription_is_free(client, db, user):
    """El caso anómalo: Free es el default seguro, y no un trial nuevo.

    Abrirle un trial acá convertiría un bug —una fila que no se creó— en una prueba gratis que
    se renueva sola con cada consulta.
    """
    db.delete(subscription_crud.get_for_user(db, user.id))
    db.flush()

    body = client.get("/subscription").json()

    assert body["is_pro"] is False
    assert body["status"] is None
    assert body["invoices_limit"] == subscription_service.FREE_MONTHLY_INVOICES


# --- POST /subscription/cancel --------------------------------------------------------------


def test_cancelling_marks_the_row_without_cutting_the_access(client, db, user):
    """El que da de baja con el período pago sigue adentro: ya lo pagó."""
    response = client.post("/subscription/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "canceled"
    assert body["is_pro"] is True
    assert body["invoices_limit"] is None

    db.expire_all()
    assert subscription_crud.get_for_user(db, user.id).canceled_at is not None


def test_cancelling_does_not_move_the_period(client, db, user):
    before = subscription_crud.get_for_user(db, user.id).current_period_end

    client.post("/subscription/cancel")

    db.expire_all()
    assert subscription_crud.get_for_user(db, user.id).current_period_end == before


def test_cancelling_twice_does_not_rewrite_when_it_was_asked(client, db, user):
    """`canceled_at` registra *cuándo lo pidió*. El segundo click no es un segundo pedido."""
    client.post("/subscription/cancel")
    db.expire_all()
    first = subscription_crud.get_for_user(db, user.id).canceled_at

    second = client.post("/subscription/cancel")

    assert second.status_code == 200
    assert second.json()["status"] == "canceled"
    db.expire_all()
    assert subscription_crud.get_for_user(db, user.id).canceled_at == first


def test_a_free_account_can_cancel_and_nothing_changes(client, free_plan):
    """No hay acceso que cortar, así que tampoco hay error que inventar."""
    body = client.post("/subscription/cancel").json()

    assert body["status"] == "canceled"
    assert body["is_pro"] is False


def test_cancelling_without_a_subscription_is_a_404(client, db, user):
    db.delete(subscription_crud.get_for_user(db, user.id))
    db.flush()

    assert client.post("/subscription/cancel").status_code == 404


def test_cancelling_needs_a_session(anonymous_client):
    assert anonymous_client.post("/subscription/cancel").status_code == 401


def test_cancelling_leaves_the_invoices_alone(client, db, user, fiscal_identity):
    """Lo emitido nunca queda detrás del paywall: es documentación fiscal obligatoria."""
    make_invoice(db, fiscal_identity, make_customer(db, user.id))

    client.post("/subscription/cancel")

    assert len(client.get("/invoices").json()) == 1


# --- El límite de identidades fiscales ------------------------------------------------------


def identity_payload(tax_id):
    return {
        "name": f"Emisor {tax_id}",
        "tax_id": tax_id,
        "condicion_iva": CondicionIva.INSCRIPTO.value,
    }


def test_a_free_account_can_create_its_first_fiscal_identity(client, free_plan):
    response = client.post("/fiscal-identities", json=identity_payload("20111111112"))

    assert response.status_code == 201


def test_a_free_account_cannot_create_a_second_one(client, fiscal_identity, free_plan):
    response = client.post("/fiscal-identities", json=identity_payload("20111111112"))

    # 402 y no 403: el permiso lo tiene, lo que falta es el plan.
    assert response.status_code == 402
    assert "Pro" in response.json()["detail"]


def test_a_pro_account_can_create_several(client, fiscal_identity):
    response = client.post("/fiscal-identities", json=identity_payload("20111111112"))

    assert response.status_code == 201


def test_downgrading_never_takes_away_the_identities_already_loaded(
    client, db, user, fiscal_identity, free_plan
):
    """Bajar de plan bloquea el alta, no borra datos.

    Elegir cuál de los tres CUIT sobrevive no es una decisión que le corresponda tomar a la
    app, y un emisor que desaparece se lleva puestos los modelos y las facturas que cuelgan
    de él.
    """
    make_fiscal_identity(db, user.id)

    listed = client.get("/fiscal-identities").json()

    assert len(listed) == 2
    blocked = client.post("/fiscal-identities", json=identity_payload("20111111112"))
    assert blocked.status_code == 402


# --- El límite de emisión, contra el endpoint que emite -------------------------------------


@pytest.fixture(autouse=True)
def ticket(monkeypatch):
    """Un TA ya emitido, sin tocar la base ni la red — calcado de `test_emission.py`."""
    monkeypatch.setattr(
        arca,
        "get_access_ticket",
        lambda service, max_age=None: arca.AccessTicket(token="tk", sign="sg"),
    )


@pytest.fixture
def wsfe_unreachable(monkeypatch):
    """ARCA explota si alguien la llama.

    Es lo contrario de un mock que contesta bien: acá lo que se prueba es que el corte por
    cupo ocurra **antes** de salir a la red. Si el chequeo se moviera abajo del `emit`, estos
    tests fallarían con un 502 en vez de pasar por casualidad.
    """

    def explode(url):
        raise AssertionError("No se tenía que llamar a ARCA con el cupo lleno.")

    monkeypatch.setattr(arca, "build_client", explode)


@pytest.fixture
def template(db, user):
    """Un modelo listo para emitir: identidad delegada, cliente exento, o sea una B."""
    identity = make_fiscal_identity(db, user.id, tax_id="20182810674")
    identity.delegation_verified_at = datetime.now(UTC)
    db.flush()
    customer = make_customer(db, user.id, condicion_iva=CondicionIva.EXENTO)
    return make_invoice_template(db, identity, customer, lines=[(0, "Alquiler")])


def spend_the_quota(db, user, template):
    for _ in range(subscription_service.FREE_MONTHLY_INVOICES):
        make_invoice(db, template.fiscal_identity, template.customer)


def test_emitting_with_the_quota_spent_answers_402(
    client, db, user, template, free_plan, wsfe_unreachable
):
    spend_the_quota(db, user, template)

    response = client.post(f"/invoice-templates/{template.id}/emit", json={})

    assert response.status_code == 402
    assert str(subscription_service.FREE_MONTHLY_INVOICES) in response.json()["detail"]


def test_the_preview_announces_the_quota_before_the_button(
    client, db, user, template, free_plan
):
    spend_the_quota(db, user, template)

    body = client.get(f"/invoice-templates/{template.id}/preview").json()

    assert str(subscription_service.FREE_MONTHLY_INVOICES) in body["blocked_reason"]


def test_the_preview_is_clean_with_quota_left(client, template, free_plan):
    body = client.get(f"/invoice-templates/{template.id}/preview").json()

    assert body["blocked_reason"] is None


def test_a_missing_delegation_wins_over_the_quota(client, db, user, template, free_plan):
    """Con los dos bloqueos puestos, la pantalla muestra el de la delegación.

    Es el que hace que ese CUIT no pueda emitir aunque el plan sobre, así que pasarse a Pro no
    destrabaría nada: mostrar el del plan primero sería cobrarle a alguien por un botón que
    igual no va a andar.
    """
    spend_the_quota(db, user, template)
    template.fiscal_identity.delegation_verified_at = None
    db.flush()

    body = client.get(f"/invoice-templates/{template.id}/preview").json()

    assert "delegación" in body["blocked_reason"]


# --- Las transiciones del CRUD --------------------------------------------------------------


def test_activating_moves_the_period_and_clears_the_cancellation(db, user):
    subscription = subscription_crud.get_for_user(db, user.id)
    subscription_crud.cancel(db, subscription)
    new_end = datetime.now(UTC) + timedelta(days=30)

    subscription_crud.activate(
        db,
        subscription,
        current_period_end=new_end,
        billing_interval=BillingInterval.MONTHLY,
        provider=BillingProvider.MERCADO_PAGO,
        provider_subscription_id="preapproval-1",
    )

    assert subscription.status is SubscriptionStatus.ACTIVE
    # Volver a pagar después de la baja es un alta nueva: dejar la marca haría que la próxima
    # renovación siguiera diciendo que esto está por terminarse.
    assert subscription.canceled_at is None


def test_a_manual_charge_does_not_wipe_the_automatic_debit(db, user):
    """Una transferencia no trae `preapproval_id`, y no puede borrar el que ya estaba atado."""
    subscription = subscription_crud.get_for_user(db, user.id)
    subscription.provider_subscription_id = "preapproval-1"
    db.flush()

    subscription_crud.activate(
        db,
        subscription,
        current_period_end=datetime.now(UTC) + timedelta(days=365),
        billing_interval=BillingInterval.YEARLY,
        provider=BillingProvider.MANUAL,
    )

    assert subscription.provider_subscription_id == "preapproval-1"


def test_a_failed_charge_does_not_move_the_period(db, user):
    """Ahí está toda la gracia: se calcula sobre esta fecha, sin una segunda que mantener."""
    subscription = subscription_crud.get_for_user(db, user.id)
    before = subscription.current_period_end

    subscription_crud.mark_past_due(db, subscription)

    assert subscription.status is SubscriptionStatus.PAST_DUE
    assert subscription.current_period_end == before


def test_one_subscription_per_user(db, user):
    """El unique de `user_id`: "la suscripción del usuario" tiene que ser una sola fila."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        make_subscription(db, user.id)


def test_a_provider_subscription_belongs_to_one_account(db, user, other_user):
    """Sin este unique, un cruce de ids en el webhook acredita el pago a la cuenta equivocada."""
    from sqlalchemy.exc import IntegrityError

    subscription_crud.get_for_user(db, user.id).provider_subscription_id = "preapproval-1"
    db.flush()
    subscription_crud.get_for_user(db, other_user.id).provider_subscription_id = "preapproval-1"

    with pytest.raises(IntegrityError):
        db.flush()


def test_make_user_alone_leaves_no_subscription(db):
    """La factory del usuario no arrastra la de la suscripción: son dos tablas.

    Fija que el trial de los fixtures venga del fixture y no de `make_user`, que es lo que deja
    a un test escribir un usuario en cualquier estado de plan sin pelearse con un default.
    """
    created = make_user(db)

    assert subscription_crud.get_for_user(db, created.id) is None
