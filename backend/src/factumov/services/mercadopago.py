"""El cobro por Mercado Pago: el checkout hosteado y el webhook que acredita.

**Es el único módulo que puede escribir un `ACTIVE`.** Todo lo demás del plan —quién es Pro,
qué puede un Free, cuándo se corta— lo decide `services/subscription.py` leyendo la fila; acá
se escribe la fila, y se escribe únicamente con lo que Mercado Pago informa.

## Preapproval y no "pago"

El camino es la API de `preapproval`: una autorización de débito automático sobre la tarjeta o
el dinero en cuenta del usuario. Tres cosas la hacen la opción correcta y ninguna es el
precio:

1. **Renueva sola.** El churn involuntario —el que te quería seguir pagando y se olvidó— se
   come mucho más que cualquier comisión.
2. **El checkout lo hostea Mercado Pago.** FactuMov nunca ve un número de tarjeta, así que no
   entra en PCI y no tiene nada que proteger de ese lado. Lo que se guarda es un id.
3. **Avisa.** Cada cobro, exitoso o fallido, llega por webhook. Sin eso no se sabe cuándo
   activar ni cuándo cortar sin que alguien mire el homebanking — ver *Monetización*.

## Lo que este módulo **no** hace

**No guarda el `preapproval_id` al crear el checkout.** La fila lo recibe recién cuando el
webhook dice que quedó autorizado, y hasta entonces el vínculo lo lleva `external_reference`,
que va con el id del usuario adentro del preapproval. Guardarlo antes ataría la cuenta a una
autorización que quizás nunca se complete —el que abandona el checkout— y el `unique` de esa
columna convertiría el segundo intento en un error sobre una fila que no se llegó a usar.

**No hace de reloj.** Ni el vencimiento del período ni el importe se calculan acá: salen de
`next_payment_date` y de `transaction_amount` de Mercado Pago. Es su calendario el que decide
cuándo vuelve a cobrar, así que una cuenta propia solo podría discrepar — y discrepar acá es
cortarle el acceso a alguien a quien le van a seguir cobrando, o al revés.

**No confía en la URL.** El webhook no tiene sesión: lo llama un servidor ajeno contra un
endpoint público que escribe `ACTIVE`. Su única autenticación es la firma `x-signature`, y sin
`MERCADOPAGO_WEBHOOK_SECRET` configurado el endpoint no procesa nada.
"""

import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any

import requests
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from requests.exceptions import RequestException
from sqlalchemy.orm import Session

from factumov.crud import subscription as subscription_crud
from factumov.crud import subscription_payment as payment_crud
from factumov.enums import BillingInterval, BillingProvider, PaymentStatus, SubscriptionStatus
from factumov.exceptions import MercadoPagoError, WebhookSignatureError
from factumov.models.subscription import Subscription
from factumov.models.user import User
from factumov.services import email
from factumov.services import subscription as subscription_service

logger = logging.getLogger(__name__)

API_BASE = "https://api.mercadopago.com"

# Mercado Pago contesta rápido cuando anda. Veinte segundos es el mismo número que Balance360
# y acota lo que puede tardar "Suscribirme", que es lo único que espera a esto con un usuario
# adelante.
TIMEOUT_SECONDS = 20

# Lo que el usuario ve como concepto en su resumen y en el mail de Mercado Pago. Es texto de
# cara al cliente, así que va en castellano y con el nombre del producto adentro.
REASON = "FactuMov Pro"

# A dónde vuelve el navegador después del checkout. La query la lee la pantalla del plan para
# explicar que la activación puede tardar unos segundos — el que activa es el webhook, no este
# regreso, y creerle a la URL sería dejar que el usuario se haga Pro volviendo a mano.
_BACK_PATH = "/plan?pago=listo"

# Cada cuánto cobra Mercado Pago, en su vocabulario. El anual es "12 meses" y no "1 año":
# `frequency_type` solo acepta `days` y `months`.
_RECURRENCE = {
    BillingInterval.MONTHLY: (1, "months"),
    BillingInterval.YEARLY: (12, "months"),
}

# Cuánto dura un período si Mercado Pago no dijo cuándo vuelve a cobrar. Es un fallback que no
# debería usarse nunca —`next_payment_date` viene siempre— y por eso redondea **para arriba**:
# de este lado el error se paga con unos días de Pro regalados, y del otro con el acceso
# cortado a alguien que pagó.
_FALLBACK_LENGTH = {
    BillingInterval.MONTHLY: timedelta(days=31),
    BillingInterval.YEARLY: timedelta(days=366),
}

# Los dos temas que mueven algo. Mercado Pago manda muchos más —`payment`, `plan`, `invoice`—
# y varios describen el **mismo** cobro por otro canal: procesarlos todos sería aplicar dos
# veces cada renovación. Se atienden estos dos y el resto se contesta 200 sin hacer nada, que
# es lo que hace que Mercado Pago deje de reintentarlos.
_PREAPPROVAL_TOPICS = frozenset({"subscription_preapproval", "preapproval"})
_AUTHORIZED_PAYMENT_TOPICS = frozenset({"subscription_authorized_payment"})


class MercadoPagoSettings(BaseSettings):
    """Las credenciales de **este servidor** ante Mercado Pago.

    Las dos son opcionales y vacías es válido, igual que con Balance360: la app arranca lo
    mismo y lo único que no anda es el cobro, que lo dice en la pantalla del plan en vez de
    reventar con un 500 cuando alguien aprieta "Suscribirme".

    Son dos secretos distintos y no uno: el access token sirve para **hablarle** a Mercado
    Pago —crear el preapproval, cancelarlo, leer un cobro— y el del webhook sirve para
    **verificar** que lo que llega viene de ellos. Confundirlos sería usar una credencial de
    escritura como clave de verificación.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mercadopago_access_token: SecretStr | None = None
    mercadopago_webhook_secret: SecretStr | None = None


@lru_cache
def get_mercadopago_settings() -> MercadoPagoSettings:
    return MercadoPagoSettings()


def is_configured() -> bool:
    """Si este servidor puede cobrar y acreditar. Las dos mitades o ninguna — ver abajo."""
    return unavailable_reason() is None


def unavailable_reason() -> str | None:
    """Qué le impide a este servidor cobrar. `None` si puede.

    Junta las dos variables porque para la pantalla son una sola pregunta —si el botón de pago
    tiene sentido— y devuelve el motivo en vez de un booleano por lo mismo que
    `balance360.unavailable_reason`: las dos se arreglan en el `.env`, y un "no disponible"
    pelado deja al operador adivinando cuál falta.

    **El secreto del webhook cuenta como faltante aunque el token esté.** Sin él se podría
    crear el checkout, el usuario pagaría y la notificación se rechazaría por no venir
    firmada: cobrar sin poder acreditar es peor que no cobrar.
    """
    settings = get_mercadopago_settings()
    if settings.mercadopago_access_token is None:
        return (
            "Este servidor no tiene configurado el cobro con Mercado Pago: "
            "falta MERCADOPAGO_ACCESS_TOKEN."
        )
    if settings.mercadopago_webhook_secret is None:
        return (
            "Este servidor no puede acreditar los pagos de Mercado Pago: "
            "falta MERCADOPAGO_WEBHOOK_SECRET."
        )
    return None


def _require_token() -> str:
    settings = get_mercadopago_settings()
    if settings.mercadopago_access_token is None:
        raise MercadoPagoError(unavailable_reason() or "", retryable=False)
    return settings.mercadopago_access_token.get_secret_value()


def _detail(response: requests.Response) -> str:
    """El mensaje de Mercado Pago, o uno propio si contestó algo que no se entiende.

    A diferencia del `detail` de Balance360, este texto **no** está escrito para un usuario
    final: dice cosas como "auto_recurring.transaction_amount is invalid". Se propaga igual
    porque es lo único que nombra la causa, y el router lo envuelve en una frase que sí se
    entiende.
    """
    try:
        payload = response.json()
    except ValueError:
        return f"Mercado Pago contestó {response.status_code}."
    if isinstance(payload, dict):
        for key in ("message", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return f"Mercado Pago contestó {response.status_code}."


def _request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    missing_is_empty: bool = False,
) -> dict[str, Any]:
    """Una llamada a la API, con el bearer puesto y los errores traducidos.

    `idempotency_key` va solo en el POST que **crea** algo. Es el mecanismo del propio Mercado
    Pago: dos requests con la misma clave no crean dos preapprovals, y eso cubre el doble
    click y el reintento de un timeout, que son los dos momentos en que este endpoint se puede
    llamar dos veces sin querer.

    `missing_is_empty` convierte el 404 en un diccionario vacío. Lo usa la baja: que Mercado
    Pago no conozca el preapproval que se quiere cancelar significa que ya no está, y tratarlo
    como error dejaría a la cuenta sin poder darse de baja de este lado por algo que del otro
    ya ocurrió.
    """
    headers = {
        "Authorization": f"Bearer {_require_token()}",
        "Accept": "application/json",
    }
    if idempotency_key is not None:
        headers["X-Idempotency-Key"] = idempotency_key

    try:
        response = requests.request(
            method,
            f"{API_BASE}{path}",
            json=payload,
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
    except RequestException as error:
        raise MercadoPagoError(
            "No pudimos conectarnos con Mercado Pago. Probá de nuevo en un rato."
        ) from error

    if response.status_code == 404 and missing_is_empty:
        return {}
    if response.status_code in (401, 403):
        # Es un problema de la instalación —token vencido, de otra aplicación, o de prueba
        # contra la API de producción— y no del usuario. Se loguea con nombre y apellido
        # porque es lo único que dice dónde mirar, y el mensaje que sube no lo repite.
        logger.error(
            "Mercado Pago rechazó las credenciales de este servidor (%s %s): %s",
            method,
            path,
            _detail(response),
        )
        raise MercadoPagoError(
            "Este servidor no está autorizado ante Mercado Pago. "
            "Revisá MERCADOPAGO_ACCESS_TOKEN.",
            retryable=False,
        )
    if not response.ok:
        # Reintentable solo si el problema es de ellos. Un 4xx va a contestar lo mismo
        # siempre: reintentarlo es gastar el intento y hacer esperar al usuario.
        raise MercadoPagoError(_detail(response), retryable=response.status_code >= 500)

    try:
        body = response.json()
    except ValueError as error:
        raise MercadoPagoError("Mercado Pago contestó algo que no entendimos.") from error
    if not isinstance(body, dict):
        raise MercadoPagoError("Mercado Pago contestó algo que no entendimos.")
    return body


# --- El checkout ------------------------------------------------------------------------


@dataclass(frozen=True)
class Checkout:
    """A dónde mandar al usuario, y con qué id va a volver el webhook."""

    preapproval_id: str
    init_point: str


def _back_url() -> str:
    """De dónde cuelga el regreso del checkout: la misma base que los links de los mails.

    Se lee de `EmailSettings.app_base_url` y no de una variable propia. Es el mismo dato —en
    qué URL vive la SPA— y una segunda copia sería una que queda vieja el día que la app
    cambie de dominio, justo en el único lugar donde el usuario vuelve con plata de por medio.
    """
    return f"{email.get_email_settings().app_base_url.rstrip('/')}{_BACK_PATH}"


def _free_trial_days(subscription: Subscription | None, now: datetime | None = None) -> int:
    """Cuántos días de prueba le quedan al que está contratando, para no cobrárselos.

    **El que paga en el día 5 de su prueba no pierde los 25 que le faltaban.** Sin esto,
    Mercado Pago cobra en el acto y el usuario compra 30 días habiendo tenido 25 gratis en la
    mano: es la clase de detalle que termina en un pedido de reembolso, y castiga justamente
    al que decidió pagar antes de que se lo pidieran. Con el `free_trial` del preapproval, la
    autorización queda hecha ya mismo y el primer cobro cae el día que la prueba se termina.

    Cero para todos los demás —el Free cuya prueba venció, el que vuelve después de darse de
    baja— porque ahí no hay nada regalado que respetar y el cobro tiene que entrar ahora.
    """
    if subscription is None or subscription.status is not SubscriptionStatus.TRIALING:
        return 0
    now = now or datetime.now(UTC)
    return max(0, (subscription.current_period_end - now).days)


def create_checkout(
    user: User, subscription: Subscription | None, interval: BillingInterval
) -> Checkout:
    """Crea el preapproval y devuelve la URL del checkout hosteado.

    `external_reference` lleva el id del usuario, y es **el único vínculo** entre la
    autorización y la cuenta hasta que el webhook la confirme: la fila todavía no tiene
    `provider_subscription_id` — ver el encabezado del módulo.

    `payer_email` es el mail de la cuenta de FactuMov. Precarga el checkout, pero además
    obliga a que quien pague sea esa persona: Mercado Pago no deja completar el preapproval
    con otra cuenta. Es lo correcto —el que paga es el titular— y es también la razón por la
    que el circuito no se puede probar con la cuenta que cobra, que en Mercado Pago no puede
    pagarse a sí misma.
    """
    frequency, frequency_type = _RECURRENCE[interval]
    auto_recurring: dict[str, Any] = {
        "frequency": frequency,
        "frequency_type": frequency_type,
        # `float` y no `Decimal`: el JSON de la API es un número, y `json` no sabe serializar
        # un Decimal. Es el único lugar del proyecto donde un importe se convierte a float, y
        # se puede porque acá termina el camino — no se vuelve a operar con él.
        "transaction_amount": float(subscription_service.price(interval)),
        "currency_id": subscription_service.CURRENCY,
    }

    free_trial_days = _free_trial_days(subscription)
    if free_trial_days > 0:
        auto_recurring["free_trial"] = {"frequency": free_trial_days, "frequency_type": "days"}

    body = _request(
        "POST",
        "/preapproval",
        payload={
            "reason": REASON,
            "external_reference": str(user.id),
            "payer_email": user.email,
            "back_url": _back_url(),
            "auto_recurring": auto_recurring,
            # `pending` es lo que hace que Mercado Pago devuelva un `init_point` en vez de
            # intentar cobrar en el acto: la autorización la da el usuario en esa pantalla.
            "status": "pending",
        },
        # La clave es del intento y no de la cuenta: dos intentos legítimos separados en el
        # tiempo —cambiar de tarjeta, arrepentirse y volver— tienen que poder crear cada uno
        # el suyo. Lo que cubre es el doble click y el reintento de un timeout.
        idempotency_key=str(uuid.uuid4()),
    )

    preapproval_id = body.get("id")
    init_point = body.get("init_point")
    if not isinstance(preapproval_id, str) or not isinstance(init_point, str) or not init_point:
        raise MercadoPagoError("Mercado Pago no devolvió un checkout utilizable.")
    logger.info(
        "Checkout de Mercado Pago creado para %s (%s, %d días de prueba sin cobrar).",
        user.email,
        interval.value,
        free_trial_days,
    )
    return Checkout(preapproval_id=preapproval_id, init_point=init_point)


def cancel_preapproval(preapproval_id: str) -> None:
    """Da de baja el débito automático del lado de Mercado Pago.

    **Es la mitad de la baja que no se puede saltear.** Marcar la fila local sin esto deja a
    Mercado Pago cobrando todos los meses una suscripción que la app da por terminada, y el
    usuario se entera por el resumen de la tarjeta.

    Un preapproval que Mercado Pago no conoce se toma como ya cancelado: lo que se busca es
    que no se cobre más, y eso ya se cumple.
    """
    _request(
        "PUT",
        f"/preapproval/{preapproval_id}",
        payload={"status": "cancelled"},
        missing_is_empty=True,
    )


# --- La firma del webhook ---------------------------------------------------------------


def verify_signature(
    *, signature: str | None, request_id: str | None, data_id: str | None
) -> None:
    """Confirma que la notificación la mandó Mercado Pago. Levanta si no.

    El header viene como `ts=1725148800,v1=<hmac>` y lo que se firma es un manifiesto armado
    con el id del recurso, el `x-request-id` y ese timestamp. Los tramos cuyo dato no vino se
    omiten, que es como lo define Mercado Pago: incluirlos vacíos da otro HMAC.

    **No se chequea que el `ts` sea reciente**, y es a propósito. Lo que un rechazo por
    antigüedad evitaría es que alguien reenvíe una notificación vieja capturada; pero
    reenviarla no logra nada —un cobro que ya se aplicó vuelve a caer en la idempotencia de
    `subscription_payments`, y un estado de preapproval se relee de Mercado Pago cada vez— y a
    cambio se perdería cualquier entrega demorada, que sí puede ser el cobro que activa una
    cuenta. El riesgo real es el de la firma, no el del reloj.

    `compare_digest` y no `==`: la comparación tiene que tardar lo mismo esté donde esté la
    primera diferencia.
    """
    secret = get_mercadopago_settings().mercadopago_webhook_secret
    if secret is None:
        # No es una firma inválida: es que este servidor no puede validar ninguna. El router
        # lo distingue y contesta 503, para que Mercado Pago reintente cuando esté puesta.
        raise MercadoPagoError(unavailable_reason() or "", retryable=False)

    parts = dict(piece.split("=", 1) for piece in (signature or "").split(",") if "=" in piece)
    timestamp = parts.get("ts", "").strip()
    received = parts.get("v1", "").strip()
    if not timestamp or not received:
        raise WebhookSignatureError("La notificación no viene firmada.")

    manifest = ""
    if data_id:
        # En minúscula: cuando el id es alfanumérico, Mercado Pago arma el manifiesto así.
        manifest += f"id:{data_id.lower()};"
    if request_id:
        manifest += f"request-id:{request_id};"
    manifest += f"ts:{timestamp};"

    expected = hmac.new(
        secret.get_secret_value().encode(), manifest.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise WebhookSignatureError("La firma de la notificación no coincide.")


# --- Lo que hace cada notificación -------------------------------------------------------


def _parse_datetime(value: Any) -> datetime | None:
    """Una fecha de Mercado Pago (`2026-09-01T10:00:00.000-04:00`), o `None`.

    Nunca devuelve una fecha sin huso: la columna es `timezone=True` y compararla con una
    naive explota. Una fecha sin huso se asume UTC.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        logger.warning("Mercado Pago mandó una fecha que no se pudo leer: %r", value)
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _interval_of(preapproval: dict[str, Any]) -> BillingInterval:
    """Mensual o anual, según cada cuánto dijo Mercado Pago que va a cobrar."""
    recurring = preapproval.get("auto_recurring")
    if isinstance(recurring, dict):
        for candidate, (frequency, frequency_type) in _RECURRENCE.items():
            if (
                recurring.get("frequency") == frequency
                and recurring.get("frequency_type") == frequency_type
            ):
                return candidate
    logger.warning("No se pudo leer la frecuencia del preapproval; se asume mensual.")
    return BillingInterval.MONTHLY


def _period_end_of(preapproval: dict[str, Any], interval: BillingInterval) -> datetime:
    """Hasta cuándo llega lo pagado: la fecha del **próximo** cobro, según Mercado Pago.

    Es su calendario y no uno propio, por lo mismo que el importe sale de ellos: son quienes
    deciden cuándo vuelven a cobrar, así que una cuenta local solo podría discrepar — y
    discrepar acá es cortarle el acceso a alguien a quien le van a cobrar igual.
    """
    next_payment = _parse_datetime(preapproval.get("next_payment_date"))
    if next_payment is not None:
        return next_payment
    logger.warning("El preapproval no trae next_payment_date; se estima el período.")
    return datetime.now(UTC) + _FALLBACK_LENGTH[interval]


def _subscription_of(db: Session, preapproval: dict[str, Any]) -> Subscription | None:
    """De qué cuenta es este preapproval.

    Dos caminos, en este orden. El id del proveedor es el vínculo firme, pero recién existe
    después de la primera activación; antes de esa, lo único que hay es el `external_reference`
    que se mandó al crear el checkout. Buscar primero por el id es lo que evita que una
    referencia vieja mueva una suscripción que ya tiene dueño.
    """
    preapproval_id = preapproval.get("id")
    if isinstance(preapproval_id, str):
        found = subscription_crud.get_by_provider_subscription_id(db, preapproval_id)
        if found is not None:
            return found

    reference = preapproval.get("external_reference")
    if not isinstance(reference, str):
        return None
    try:
        user_id = uuid.UUID(reference)
    except ValueError:
        logger.warning("El preapproval trae un external_reference ilegible: %r", reference)
        return None
    return subscription_crud.get_for_user(db, user_id)


def _apply_preapproval(db: Session, preapproval_id: str) -> str:
    """El estado de la autorización cambió: se relee de Mercado Pago y se copia a la fila.

    **Se relee en vez de creerle al evento**, y eso es lo que hace que este camino sea
    idempotente sin ninguna tabla de por medio: procesar dos veces la misma notificación
    escribe dos veces lo mismo, y procesar una vieja escribe el estado de **ahora** y no el de
    entonces. La idempotencia que sí necesita un registro es la del dinero, que es la de
    `subscription_payments`.
    """
    remote = _request("GET", f"/preapproval/{preapproval_id}")
    subscription = _subscription_of(db, remote)
    if subscription is None:
        logger.warning("Llegó un preapproval %s que no es de ninguna cuenta.", preapproval_id)
        return "sin cuenta"

    status = remote.get("status")
    if status == "authorized":
        interval = _interval_of(remote)
        subscription_crud.activate(
            db,
            subscription,
            current_period_end=_period_end_of(remote, interval),
            billing_interval=interval,
            provider=BillingProvider.MERCADO_PAGO,
            provider_subscription_id=preapproval_id,
        )
        return "autorizada"
    if status == "cancelled":
        # No corta el acceso: el período que se pagó se termina de usar. Es la misma baja que
        # el botón de la app, y llega por acá cuando el usuario la pide desde Mercado Pago.
        if subscription.status is not SubscriptionStatus.CANCELED:
            subscription_crud.cancel(db, subscription)
        return "cancelada"
    if status == "paused":
        # Mercado Pago pausa una suscripción cuyos cobros vienen fallando. Es exactamente lo
        # que `PAST_DUE` significa acá, con sus días de gracia: el usuario sigue siendo Pro
        # mientras se reintenta.
        subscription_crud.mark_past_due(db, subscription)
        return "pausada"
    # `pending` es el checkout que todavía no completó nadie. No es un error ni hay nada que
    # escribir: la cuenta sigue como estaba.
    return f"sin efecto ({status})"


def _outcome_of(authorized_payment: dict[str, Any]) -> PaymentStatus | None:
    """Si el cobro entró, si se rechazó, o si todavía está en vuelo (`None`).

    El estado que importa es el del pago de adentro y no el del `authorized_payment`, que dice
    en qué anda el intento (`scheduled`, `recycling`, `processed`) y no si hubo plata. Un
    cobro en vuelo no escribe nada: cuando se resuelva va a llegar otra notificación, y una
    fila `PENDING` que nadie vuelve a mirar es peor que ninguna fila.
    """
    payment = authorized_payment.get("payment")
    status = payment.get("status") if isinstance(payment, dict) else None
    if status == "approved":
        return PaymentStatus.APPROVED
    if status in ("rejected", "cancelled"):
        return PaymentStatus.REJECTED
    return None


def _apply_authorized_payment(db: Session, payment_id: str) -> str:
    """Un cobro de la suscripción: acredita el período nuevo, o marca que falló."""
    remote = _request("GET", f"/authorized_payments/{payment_id}")

    preapproval_id = remote.get("preapproval_id")
    if not isinstance(preapproval_id, str):
        logger.warning("Llegó un cobro %s sin preapproval asociado.", payment_id)
        return "sin suscripción"
    subscription = subscription_crud.get_by_provider_subscription_id(db, preapproval_id)
    if subscription is None:
        # Puede pasar legítimamente: el cobro de la primera cuota puede llegar antes que la
        # notificación que autorizó el preapproval, y ahí la fila todavía no tiene el id.
        # Levantar hace que el router conteste 502 y que Mercado Pago lo reintente, que es
        # exactamente lo que corresponde — para entonces el otro evento ya pasó.
        raise MercadoPagoError(
            f"Todavía no hay ninguna cuenta atada al preapproval {preapproval_id}."
        )

    outcome = _outcome_of(remote)
    if outcome is None:
        return "en curso"
    if payment_crud.is_already_applied(db, payment_id, outcome):
        return "duplicado"

    if outcome is PaymentStatus.APPROVED:
        # El período nuevo sale del preapproval releído: después de un cobro exitoso, Mercado
        # Pago ya movió ahí el `next_payment_date`. Es una llamada más a cambio de no sumar un
        # mes a mano y arriesgar que las dos fechas discrepen.
        preapproval = _request("GET", f"/preapproval/{preapproval_id}")
        interval = _interval_of(preapproval)
        subscription_crud.activate(
            db,
            subscription,
            current_period_end=_period_end_of(preapproval, interval),
            billing_interval=interval,
            provider=BillingProvider.MERCADO_PAGO,
            provider_subscription_id=preapproval_id,
        )
    else:
        # No se toca `current_period_end`: ahí está toda la mecánica de la gracia. Ver
        # `crud/subscription.mark_past_due`.
        subscription_crud.mark_past_due(db, subscription)

    payment = remote.get("payment")
    approved_at = (
        _parse_datetime(payment.get("date_approved")) if isinstance(payment, dict) else None
    )
    payment_crud.record(
        db,
        subscription_id=subscription.id,
        provider=BillingProvider.MERCADO_PAGO,
        provider_payment_id=payment_id,
        status=outcome,
        # `str()` antes del `Decimal`: Mercado Pago manda el importe como número JSON, o sea
        # un float, y `Decimal(1234.56)` se queda con el error de representación del binario.
        amount=Decimal(str(remote.get("transaction_amount") or "0")),
        currency=str(remote.get("currency_id") or subscription_service.CURRENCY),
        charged_at=approved_at or _parse_datetime(remote.get("debit_date")),
    )
    logger.info(
        "Cobro %s de Mercado Pago: %s (suscripción %s).", payment_id, outcome.value, subscription.id
    )
    return outcome.value


def handle_notification(db: Session, topic: str | None, data_id: str | None) -> str:
    """Aplica una notificación ya verificada. Devuelve qué hizo, para el log y la respuesta.

    **No commitea**: corre adentro de un request y de eso se encarga `get_db`. Es al revés que
    `balance360.register`, que sí commitea porque corre en un background task con su propia
    sesión y no hay ningún request que vaya a cerrarle la transacción.

    Un tema desconocido no es un error. Mercado Pago manda notificaciones de cosas que a esta
    app no le mueven nada, y contestarles con un fallo las pone a reintentar para siempre.
    """
    if not data_id:
        return "sin id"
    if topic in _PREAPPROVAL_TOPICS:
        return _apply_preapproval(db, data_id)
    if topic in _AUTHORIZED_PAYMENT_TOPICS:
        return _apply_authorized_payment(db, data_id)
    return "ignorado"
