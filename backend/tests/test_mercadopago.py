"""El cobro por Mercado Pago: el checkout, la firma del webhook y lo que cada aviso escribe.

**Nada de acá sale a la red.** Se parchea `requests.request` en el módulo del cliente, que es
el nivel más bajo con sentido —igual que en `test_balance360.py`—: así se ejercita de verdad
el armado del preapproval, la lectura de la respuesta y la traducción de un evento a una fila.
Mockear `mercadopago.handle_notification` probaría que el router llama a una función.

Lo que estos tests cuidan por encima de todo son las dos propiedades de las que depende que
nadie pague de más ni de menos:

1. **El webhook no acredita nada sin firma.** Es el único endpoint de la app sin sesión que
   puede volver Pro a una cuenta.
2. **El mismo cobro no se aplica dos veces.** Mercado Pago reintenta, y un período empujado de
   más es un mes regalado por cada entrega repetida.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from factumov.crud import subscription as subscription_crud
from factumov.crud import subscription_payment as payment_crud
from factumov.enums import BillingInterval, BillingProvider, PaymentStatus, SubscriptionStatus
from factumov.exceptions import MercadoPagoError, WebhookSignatureError
from factumov.services import mercadopago
from factumov.services import subscription as subscription_service
from tests.conftest import MERCADOPAGO_WEBHOOK_SECRET
from tests.factories import make_subscription, make_user

PREAPPROVAL_ID = "2c9380849876a1b30198a2c4d5e60001"
PAYMENT_ID = "112233445566"

WEBHOOK_PATH = "/webhooks/mercado-pago"


class FakeResponse:
    """Lo mínimo de `requests.Response` que usa el cliente."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("no es JSON")
        return self._payload


@pytest.fixture
def mp(monkeypatch):
    """Intercepta las llamadas a la API y deja elegir qué contesta cada una.

    Las respuestas se registran por `(método, prefijo del path)` y no en una sola ranura,
    porque un mismo camino toca dos endpoints distintos: acreditar un cobro lee el
    `authorized_payment` **y** relee el `preapproval` para saber hasta cuándo llega el período
    nuevo. Con una ranura única, el test del cobro tendría que dejar puesta la respuesta del
    otro y no se podría afirmar sobre ninguno de los dos.
    """
    calls = []
    routes = {}

    def fake_request(method, url, json=None, headers=None, timeout=None):
        path = url[len(mercadopago.API_BASE) :]
        calls.append({"method": method, "path": path, "json": json, "headers": headers or {}})
        for (route_method, prefix), result in routes.items():
            if method == route_method and path.startswith(prefix):
                if isinstance(result, Exception):
                    raise result
                return result
        return FakeResponse(200, {})

    monkeypatch.setattr(mercadopago.requests, "request", fake_request)
    return SimpleNamespace(calls=calls, routes=routes)


def set_plan(db, user, **fields):
    """Mueve la suscripción que el usuario **ya tiene** al estado que el test necesita.

    El fixture `user` le da una desde el vamos —así sale del registro— y `subscriptions.user_id`
    es `unique`, así que crear otra sería un error de integridad y no un caso de prueba. Es el
    mismo criterio que el fixture `free_plan` de `test_subscription.py`: se vence o se mueve la
    que hay, no se inventa una segunda.
    """
    subscription = subscription_crud.get_for_user(db, user.id)
    for name, value in fields.items():
        setattr(subscription, name, value)
    db.flush()
    return subscription


def preapproval_body(status="authorized", user_id=None, next_payment_date=None, frequency=1):
    """Un `preapproval` como lo devuelve Mercado Pago, con lo que el módulo mira."""
    return {
        "id": PREAPPROVAL_ID,
        "status": status,
        "external_reference": str(user_id) if user_id is not None else None,
        "next_payment_date": next_payment_date or "2026-10-01T10:00:00.000-03:00",
        "auto_recurring": {
            "frequency": frequency,
            "frequency_type": "months",
            "transaction_amount": 7000.0,
            "currency_id": "ARS",
        },
    }


def authorized_payment_body(payment_status="approved", amount=7000.0):
    return {
        "id": PAYMENT_ID,
        "preapproval_id": PREAPPROVAL_ID,
        "transaction_amount": amount,
        "currency_id": "ARS",
        "debit_date": "2026-09-01T10:00:00.000-03:00",
        "payment": {
            "id": 998877,
            "status": payment_status,
            "date_approved": "2026-09-01T10:05:00.000-03:00",
        },
    }


def signed_headers(data_id, request_id="req-de-prueba", secret=MERCADOPAGO_WEBHOOK_SECRET):
    """Los dos headers con los que Mercado Pago firma una notificación.

    El manifiesto se arma acá a mano, del mismo modo que lo documenta Mercado Pago, y no
    llamando a la función que se está probando: si el test reusara el código del módulo,
    cualquier error en el armado del manifiesto pasaría de largo porque las dos puntas se
    equivocarían igual.
    """
    timestamp = "1725148800"
    manifest = f"id:{data_id.lower()};request-id:{request_id};ts:{timestamp};"
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={timestamp},v1={v1}", "x-request-id": request_id}


def notify(client, topic, data_id, headers=None):
    return client.post(
        WEBHOOK_PATH,
        json={"type": topic, "action": "updated", "data": {"id": data_id}},
        headers=signed_headers(data_id) if headers is None else headers,
    )


# --- La firma ------------------------------------------------------------------------------


def test_a_correctly_signed_notification_passes():
    mercadopago.verify_signature(
        signature=signed_headers(PREAPPROVAL_ID)["x-signature"],
        request_id="req-de-prueba",
        data_id=PREAPPROVAL_ID,
    )


def test_a_signature_from_another_secret_is_rejected():
    forged = signed_headers(PREAPPROVAL_ID, secret="otro-secreto")["x-signature"]
    with pytest.raises(WebhookSignatureError):
        mercadopago.verify_signature(
            signature=forged, request_id="req-de-prueba", data_id=PREAPPROVAL_ID
        )


def test_a_notification_for_another_resource_is_rejected():
    """La firma cubre el id: cambiarlo y reusar el HMAC no cuela.

    Es lo que impide que alguien capture una notificación válida y le cambie el id por el del
    preapproval de otra cuenta.
    """
    headers = signed_headers(PREAPPROVAL_ID)
    with pytest.raises(WebhookSignatureError):
        mercadopago.verify_signature(
            signature=headers["x-signature"], request_id="req-de-prueba", data_id="otro-id"
        )


def test_no_signature_header_is_rejected():
    with pytest.raises(WebhookSignatureError):
        mercadopago.verify_signature(
            signature=None, request_id="req-de-prueba", data_id=PREAPPROVAL_ID
        )


def test_a_server_without_the_secret_cannot_verify_anything(monkeypatch):
    """Sin `MERCADOPAGO_WEBHOOK_SECRET` no se acepta ninguna notificación.

    Y no es una firma inválida: es que este servidor no puede validar ninguna. La diferencia
    importa porque termina en 503 y no en 401, que es lo que hace que Mercado Pago reintente
    el aviso cuando la variable esté puesta en vez de darlo por perdido.
    """
    monkeypatch.delenv("MERCADOPAGO_WEBHOOK_SECRET")
    mercadopago.get_mercadopago_settings.cache_clear()
    with pytest.raises(MercadoPagoError):
        mercadopago.verify_signature(
            signature=signed_headers(PREAPPROVAL_ID)["x-signature"],
            request_id="req-de-prueba",
            data_id=PREAPPROVAL_ID,
        )


# --- El endpoint del webhook ---------------------------------------------------------------


def test_the_webhook_needs_no_session(anonymous_client, db, user, mp):
    """Lo llama un servidor de Mercado Pago, que no tiene ninguna cookie de esta app."""
    mp.routes[("GET", "/preapproval")] = FakeResponse(200, preapproval_body(user_id=user.id))
    response = notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)
    assert response.status_code == 200


def test_an_unsigned_notification_gets_a_401(anonymous_client, mp):
    """El caso que hace falta que sea imposible: hacerse Pro con un `curl`."""
    response = anonymous_client.post(
        WEBHOOK_PATH,
        json={"type": "subscription_preapproval", "data": {"id": PREAPPROVAL_ID}},
    )
    assert response.status_code == 401
    # Y no se consultó nada: la firma se verifica antes de salir a leer el recurso.
    assert mp.calls == []


def test_an_unknown_topic_is_answered_without_doing_anything(anonymous_client, mp):
    """Mercado Pago avisa de cosas que a esta app no le mueven nada.

    Contestarles con un error las pondría a reintentar para siempre.
    """
    response = notify(anonymous_client, "plan", "algo-que-no-nos-toca")
    assert response.status_code == 200
    assert response.json()["result"] == "ignorado"
    assert mp.calls == []


def test_the_legacy_ipn_format_is_understood(anonymous_client, db, user, mp):
    """El formato viejo manda `topic`/`id` por query y **sin cuerpo**.

    Cuál de los dos llega lo decide la configuración del panel de Mercado Pago y no esta app,
    así que rechazar el viejo con un 422 sería no procesar cobros por una casilla mal tildada.
    """
    mp.routes[("GET", "/preapproval")] = FakeResponse(200, preapproval_body(user_id=user.id))

    response = anonymous_client.post(
        f"{WEBHOOK_PATH}?topic=preapproval&id={PREAPPROVAL_ID}",
        headers=signed_headers(PREAPPROVAL_ID),
    )

    assert response.status_code == 200
    assert response.json()["result"] == "autorizada"


# --- El estado de la autorización ----------------------------------------------------------


def test_an_authorized_preapproval_activates_the_account(anonymous_client, db, user, mp):
    """El único camino por el que una cuenta pasa a `ACTIVE`.

    Se encuentra por `external_reference`, que es el vínculo que existe antes de que la fila
    tenga el id del proveedor — ese id lo escribe justamente esta notificación.
    """
    subscription = subscription_crud.get_for_user(db, user.id)
    mp.routes[("GET", "/preapproval")] = FakeResponse(200, preapproval_body(user_id=user.id))

    response = notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)

    assert response.status_code == 200
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.provider is BillingProvider.MERCADO_PAGO
    assert subscription.provider_subscription_id == PREAPPROVAL_ID
    assert subscription.billing_interval is BillingInterval.MONTHLY
    # El período sale de `next_payment_date` de Mercado Pago y no de una cuenta local: son
    # ellos los que deciden cuándo vuelven a cobrar.
    assert subscription.current_period_end == datetime.fromisoformat(
        "2026-10-01T10:00:00.000-03:00"
    )


def test_twelve_months_is_read_as_the_yearly_plan(anonymous_client, db, user, mp):
    """El anual viaja como "12 meses": `frequency_type` solo acepta `days` y `months`."""
    subscription = subscription_crud.get_for_user(db, user.id)
    mp.routes[("GET", "/preapproval")] = FakeResponse(
        200, preapproval_body(user_id=user.id, frequency=12)
    )

    notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)

    assert subscription.billing_interval is BillingInterval.YEARLY


def test_the_same_authorization_twice_leaves_the_same_row(anonymous_client, db, user, mp):
    """La idempotencia de este camino no necesita ninguna tabla.

    El evento no dice qué pasó: dice qué recurso mirar. Al releerlo de Mercado Pago, procesar
    dos veces la misma notificación escribe dos veces lo mismo.
    """
    subscription = subscription_crud.get_for_user(db, user.id)
    mp.routes[("GET", "/preapproval")] = FakeResponse(200, preapproval_body(user_id=user.id))

    notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)
    first_end = subscription.current_period_end
    notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)

    assert subscription.current_period_end == first_end
    assert subscription.status is SubscriptionStatus.ACTIVE


def test_a_cancelled_preapproval_does_not_cut_the_access(anonymous_client, db, user, mp):
    """La baja pedida desde Mercado Pago es la misma que la del botón: no toca el período."""
    period_end = datetime.now(UTC) + timedelta(days=20)
    subscription = set_plan(
        db,
        user,
        status=SubscriptionStatus.ACTIVE,
        current_period_end=period_end,
        provider=BillingProvider.MERCADO_PAGO,
        provider_subscription_id=PREAPPROVAL_ID,
    )
    mp.routes[("GET", "/preapproval")] = FakeResponse(
        200, preapproval_body(status="cancelled", user_id=user.id)
    )

    notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)

    assert subscription.status is SubscriptionStatus.CANCELED
    assert subscription.current_period_end == period_end
    assert subscription_service.is_pro(subscription)


def test_a_paused_preapproval_is_past_due_and_keeps_the_grace(anonymous_client, db, user, mp):
    """Mercado Pago pausa lo que viene fallando, que es lo que `PAST_DUE` significa acá."""
    period_end = datetime.now(UTC) - timedelta(days=1)
    subscription = set_plan(
        db,
        user,
        status=SubscriptionStatus.ACTIVE,
        current_period_end=period_end,
        provider=BillingProvider.MERCADO_PAGO,
        provider_subscription_id=PREAPPROVAL_ID,
    )
    mp.routes[("GET", "/preapproval")] = FakeResponse(
        200, preapproval_body(status="paused", user_id=user.id)
    )

    notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)

    assert subscription.status is SubscriptionStatus.PAST_DUE
    # La fecha no se mueve: los días de gracia se suman al leer, no acá.
    assert subscription.current_period_end == period_end
    assert subscription_service.is_pro(subscription)


def test_a_preapproval_of_nobody_is_answered_without_writing(anonymous_client, db, mp):
    mp.routes[("GET", "/preapproval")] = FakeResponse(200, preapproval_body(user_id=None))
    response = notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)
    assert response.status_code == 200
    assert response.json()["result"] == "sin cuenta"


def test_mercado_pago_being_down_asks_for_a_retry(anonymous_client, db, user, mp):
    """Un 502 es lo que hace que Mercado Pago reintente el aviso más tarde.

    Perder una notificación por contestar 200 sobre algo que no se pudo procesar puede ser
    perder el cobro que activa una cuenta.
    """
    mp.routes[("GET", "/preapproval")] = FakeResponse(500, {"message": "cayó"})
    response = notify(anonymous_client, "subscription_preapproval", PREAPPROVAL_ID)
    assert response.status_code == 502


# --- Los cobros --------------------------------------------------------------------------


@pytest.fixture
def paying(db, user):
    """Una cuenta con el débito automático ya atado, que es donde caen los cobros."""
    return set_plan(
        db,
        user,
        status=SubscriptionStatus.ACTIVE,
        current_period_end=datetime.now(UTC) + timedelta(days=1),
        billing_interval=BillingInterval.MONTHLY,
        provider=BillingProvider.MERCADO_PAGO,
        provider_subscription_id=PREAPPROVAL_ID,
    )


def test_an_approved_charge_extends_the_period_and_is_recorded(
    anonymous_client, db, user, paying, mp
):
    mp.routes[("GET", "/authorized_payments")] = FakeResponse(200, authorized_payment_body())
    mp.routes[("GET", "/preapproval")] = FakeResponse(200, preapproval_body(user_id=user.id))

    response = notify(anonymous_client, "subscription_authorized_payment", PAYMENT_ID)

    assert response.status_code == 200
    assert paying.status is SubscriptionStatus.ACTIVE
    assert paying.current_period_end == datetime.fromisoformat("2026-10-01T10:00:00.000-03:00")

    payment = payment_crud.get_by_provider_payment_id(db, PAYMENT_ID)
    assert payment is not None
    assert payment.status is PaymentStatus.APPROVED
    # El importe se guarda como lo informó el proveedor y no como lo dice la lista de precios:
    # el precio se va a cambiar, y la fila vieja tiene que seguir diciendo lo que se pagó.
    assert payment.amount == Decimal("7000.00")
    assert payment.currency == "ARS"


def test_the_same_charge_delivered_twice_does_not_extend_twice(
    anonymous_client, db, user, paying, mp
):
    """El motivo de que exista `subscription_payments`.

    Mercado Pago reintenta ante cualquier respuesta que no sea 2xx y manda el mismo aviso más
    de una vez. Sin la idempotencia, tres entregas serían tres meses regalados.
    """
    mp.routes[("GET", "/authorized_payments")] = FakeResponse(200, authorized_payment_body())
    mp.routes[("GET", "/preapproval")] = FakeResponse(200, preapproval_body(user_id=user.id))

    notify(anonymous_client, "subscription_authorized_payment", PAYMENT_ID)
    second = notify(anonymous_client, "subscription_authorized_payment", PAYMENT_ID)

    assert second.json()["result"] == "duplicado"
    assert len(payment_crud.list_for_subscription(db, paying.id)) == 1


def test_a_rejected_charge_marks_past_due_without_moving_the_period(
    anonymous_client, db, user, paying, mp
):
    period_end = paying.current_period_end
    mp.routes[("GET", "/authorized_payments")] = FakeResponse(
        200, authorized_payment_body(payment_status="rejected")
    )

    notify(anonymous_client, "subscription_authorized_payment", PAYMENT_ID)

    assert paying.status is SubscriptionStatus.PAST_DUE
    assert paying.current_period_end == period_end
    # Y sigue siendo Pro: ahí está la gracia, y sale de no haber tocado la fecha.
    assert subscription_service.is_pro(paying)
    payment = payment_crud.get_by_provider_payment_id(db, PAYMENT_ID)
    assert payment is not None and payment.status is PaymentStatus.REJECTED


def test_a_recycled_charge_that_finally_goes_through_is_applied(
    anonymous_client, db, user, paying, mp
):
    """El caso que obliga a que la clave de idempotencia sea el par (id, estado).

    Mercado Pago reintenta el cobro rechazado **con el mismo id** durante varios días. Si el
    filtro fuera solo por id, la aprobación se descartaría como duplicada y el usuario se
    quedaría en `PAST_DUE` hasta que se le acabe la gracia, habiendo pagado.
    """
    mp.routes[("GET", "/authorized_payments")] = FakeResponse(
        200, authorized_payment_body(payment_status="rejected")
    )
    notify(anonymous_client, "subscription_authorized_payment", PAYMENT_ID)
    assert paying.status is SubscriptionStatus.PAST_DUE

    mp.routes[("GET", "/authorized_payments")] = FakeResponse(200, authorized_payment_body())
    mp.routes[("GET", "/preapproval")] = FakeResponse(200, preapproval_body(user_id=user.id))
    notify(anonymous_client, "subscription_authorized_payment", PAYMENT_ID)

    assert paying.status is SubscriptionStatus.ACTIVE
    payments = payment_crud.list_for_subscription(db, paying.id)
    assert len(payments) == 1
    assert payments[0].status is PaymentStatus.APPROVED


def test_a_charge_still_in_flight_writes_nothing(anonymous_client, db, user, paying, mp):
    """`in_process` no es ni sí ni no: cuando se resuelva va a llegar otro aviso."""
    mp.routes[("GET", "/authorized_payments")] = FakeResponse(
        200, authorized_payment_body(payment_status="in_process")
    )

    response = notify(anonymous_client, "subscription_authorized_payment", PAYMENT_ID)

    assert response.json()["result"] == "en curso"
    assert paying.status is SubscriptionStatus.ACTIVE
    assert payment_crud.get_by_provider_payment_id(db, PAYMENT_ID) is None


def test_a_charge_before_its_authorization_asks_for_a_retry(anonymous_client, db, user, mp):
    """Los dos avisos pueden llegar al revés, y el cobro no se puede perder.

    Mientras la fila no tenga el `provider_subscription_id`, este cobro no es de nadie. Un 502
    hace que Mercado Pago lo reintente, y para entonces la otra notificación ya pasó.
    """
    mp.routes[("GET", "/authorized_payments")] = FakeResponse(200, authorized_payment_body())

    response = notify(anonymous_client, "subscription_authorized_payment", PAYMENT_ID)

    assert response.status_code == 502


# --- El checkout ---------------------------------------------------------------------------


def test_the_offer_lists_both_prices(client):
    response = client.get("/subscription/plans")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["currency"] == "ARS"
    # Como string, igual que todos los importes de la API: Pydantic serializa `Decimal` así
    # para que no pase por el float de JavaScript.
    assert body["monthly_price"] == str(subscription_service.PRICES[BillingInterval.MONTHLY])


def test_the_offer_says_what_is_missing_when_the_server_cannot_charge(client, monkeypatch):
    monkeypatch.delenv("MERCADOPAGO_ACCESS_TOKEN")
    mercadopago.get_mercadopago_settings.cache_clear()

    body = client.get("/subscription/plans").json()

    assert body["available"] is False
    assert "MERCADOPAGO_ACCESS_TOKEN" in body["unavailable_reason"]


def test_starting_a_checkout_returns_the_hosted_url(client, db, user, mp):
    mp.routes[("POST", "/preapproval")] = FakeResponse(
        201, {"id": PREAPPROVAL_ID, "init_point": "https://mercadopago.test/checkout"}
    )

    response = client.post("/subscription/checkout", json={"interval": "monthly"})

    assert response.status_code == 200
    assert response.json() == {"init_point": "https://mercadopago.test/checkout"}

    sent = mp.calls[-1]["json"]
    # El id del usuario es el único vínculo entre la autorización y la cuenta hasta que el
    # webhook la confirme: sin esto, el aviso de "autorizada" no sabría de quién es.
    assert sent["external_reference"] == str(user.id)
    assert sent["payer_email"] == user.email
    assert sent["auto_recurring"]["transaction_amount"] == float(
        subscription_service.PRICES[BillingInterval.MONTHLY]
    )
    assert sent["auto_recurring"]["frequency_type"] == "months"


def test_the_checkout_does_not_make_anyone_pro(client, db, user, mp):
    """Postear acá no mueve una sola columna: lo único que produce es una URL."""
    subscription = subscription_crud.get_for_user(db, user.id)
    mp.routes[("POST", "/preapproval")] = FakeResponse(
        201, {"id": PREAPPROVAL_ID, "init_point": "https://mercadopago.test/checkout"}
    )

    client.post("/subscription/checkout", json={"interval": "monthly"})

    assert subscription.status is SubscriptionStatus.TRIALING
    assert subscription.provider_subscription_id is None


def test_paying_during_the_trial_does_not_burn_the_days_left(client, db, user, mp):
    """El que paga en el día 5 no pierde los 25 que le faltaban.

    Sin el `free_trial`, Mercado Pago cobra en el acto y el usuario compra treinta días
    teniendo veinticinco gratis en la mano.
    """
    set_plan(
        db,
        user,
        status=SubscriptionStatus.TRIALING,
        current_period_end=datetime.now(UTC) + timedelta(days=25, hours=1),
    )
    mp.routes[("POST", "/preapproval")] = FakeResponse(
        201, {"id": PREAPPROVAL_ID, "init_point": "https://mercadopago.test/checkout"}
    )

    client.post("/subscription/checkout", json={"interval": "monthly"})

    free_trial = mp.calls[-1]["json"]["auto_recurring"]["free_trial"]
    assert free_trial == {"frequency": 25, "frequency_type": "days"}


def test_a_free_account_is_charged_right_away(client, db, user, mp):
    """Al que ya se le venció la prueba no hay nada regalado que respetarle."""
    set_plan(
        db,
        user,
        status=SubscriptionStatus.TRIALING,
        current_period_end=datetime.now(UTC) - timedelta(days=1),
    )
    mp.routes[("POST", "/preapproval")] = FakeResponse(
        201, {"id": PREAPPROVAL_ID, "init_point": "https://mercadopago.test/checkout"}
    )

    client.post("/subscription/checkout", json={"interval": "monthly"})

    assert "free_trial" not in mp.calls[-1]["json"]["auto_recurring"]


def test_an_active_subscription_cannot_be_contracted_again(client, db, user, paying, mp):
    """Dos `preapproval` sobre la misma cuenta son dos débitos por el mismo servicio."""
    response = client.post("/subscription/checkout", json={"interval": "monthly"})
    assert response.status_code == 409
    assert mp.calls == []


def test_a_past_due_account_can_re_subscribe_and_the_old_one_is_cancelled(client, db, user, mp):
    """Es el que necesita rehacer la autorización con otra tarjeta.

    Lo que no puede quedar es la anterior viva: serían dos débitos automáticos.
    """
    set_plan(
        db,
        user,
        status=SubscriptionStatus.PAST_DUE,
        provider=BillingProvider.MERCADO_PAGO,
        provider_subscription_id=PREAPPROVAL_ID,
    )
    mp.routes[("PUT", "/preapproval")] = FakeResponse(200, {"id": PREAPPROVAL_ID})
    mp.routes[("POST", "/preapproval")] = FakeResponse(
        201, {"id": "otro-preapproval", "init_point": "https://mercadopago.test/checkout"}
    )

    response = client.post("/subscription/checkout", json={"interval": "monthly"})

    assert response.status_code == 200
    cancelled = [call for call in mp.calls if call["method"] == "PUT"]
    assert cancelled and cancelled[0]["json"] == {"status": "cancelled"}


def test_a_server_that_cannot_charge_says_so(client, monkeypatch, mp):
    monkeypatch.delenv("MERCADOPAGO_ACCESS_TOKEN")
    mercadopago.get_mercadopago_settings.cache_clear()

    response = client.post("/subscription/checkout", json={"interval": "monthly"})

    assert response.status_code == 503
    assert mp.calls == []


def test_the_checkout_needs_a_session(anonymous_client):
    response = anonymous_client.post("/subscription/checkout", json={"interval": "monthly"})
    assert response.status_code == 401


# --- La baja, con su otra mitad ------------------------------------------------------------


def test_cancelling_also_cancels_the_automatic_debit(client, db, user, paying, mp):
    """La mitad que no se puede saltear.

    Marcar la fila sin cancelar el `preapproval` deja a Mercado Pago cobrando todos los meses
    una suscripción que la app da por terminada.
    """
    mp.routes[("PUT", "/preapproval")] = FakeResponse(200, {"id": PREAPPROVAL_ID})

    response = client.post("/subscription/cancel")

    assert response.status_code == 200
    assert paying.status is SubscriptionStatus.CANCELED
    assert mp.calls[-1]["method"] == "PUT"
    assert mp.calls[-1]["json"] == {"status": "cancelled"}


def test_if_mercado_pago_does_not_confirm_the_row_is_not_marked(client, db, user, paying, mp):
    """Contestar 502 y que vuelva a intentar es molesto; cobrarle de más, no.

    Una baja que existe solo de este lado es la única forma de que el usuario siga pagando por
    algo que la app ya dio por terminado.
    """
    mp.routes[("PUT", "/preapproval")] = FakeResponse(500, {"message": "cayó"})

    response = client.post("/subscription/cancel")

    assert response.status_code == 502
    assert paying.status is SubscriptionStatus.ACTIVE
    assert paying.canceled_at is None


def test_a_preapproval_mercado_pago_no_longer_knows_is_taken_as_cancelled(
    client, db, user, paying, mp
):
    """Lo que se busca es que no se cobre más, y con un 404 eso ya se cumple."""
    mp.routes[("PUT", "/preapproval")] = FakeResponse(404, {"message": "not found"})

    response = client.post("/subscription/cancel")

    assert response.status_code == 200
    assert paying.status is SubscriptionStatus.CANCELED


def test_a_trial_cancels_without_talking_to_mercado_pago(client, db, user, mp):
    """No hay débito automático que dar de baja: nunca se contrató nada."""
    response = client.post("/subscription/cancel")

    assert response.status_code == 200
    assert mp.calls == []


# --- El scoping de los cobros --------------------------------------------------------------


def test_the_same_provider_payment_never_lands_twice(db, user):
    """El `unique` que protege de aplicar dos veces el mismo cobro.

    Es a nivel base y no solo un chequeo en el servicio porque el chequeo pierde contra dos
    entregas simultáneas del mismo webhook, y la restricción no.
    """
    other = make_user(db)
    mine = subscription_crud.get_for_user(db, user.id)
    theirs = make_subscription(db, other.id)

    payment_crud.record(
        db,
        subscription_id=mine.id,
        provider=BillingProvider.MERCADO_PAGO,
        provider_payment_id=PAYMENT_ID,
        status=PaymentStatus.APPROVED,
        amount=Decimal("7000.00"),
        currency="ARS",
        charged_at=None,
    )
    # El mismo id otra vez no crea una segunda fila: es el mismo cobro, y `record` actualiza
    # el que ya estaba.
    payment_crud.record(
        db,
        subscription_id=theirs.id,
        provider=BillingProvider.MERCADO_PAGO,
        provider_payment_id=PAYMENT_ID,
        status=PaymentStatus.APPROVED,
        amount=Decimal("7000.00"),
        currency="ARS",
        charged_at=None,
    )

    assert len(payment_crud.list_for_subscription(db, mine.id)) == 1
    assert payment_crud.list_for_subscription(db, theirs.id) == []
