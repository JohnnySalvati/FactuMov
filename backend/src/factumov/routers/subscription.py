import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from factumov.crud import subscription as subscription_crud
from factumov.dependencies import (
    CurrentUserDep,
    SessionDep,
    enforce_rate_limit,
    get_current_user,
)
from factumov.enums import BillingInterval, BillingProvider, SubscriptionStatus
from factumov.exceptions import MercadoPagoError, WebhookSignatureError
from factumov.schemas.subscription import (
    CheckoutRequest,
    CheckoutStart,
    MercadoPagoNotification,
    PlanOffer,
    SubscriptionRead,
)
from factumov.services import mercadopago
from factumov.services import subscription as subscription_service
from factumov.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/subscription",
    tags=["subscription"],
    dependencies=[Depends(get_current_user)],
)

# Cada intento crea un `preapproval` del lado de Mercado Pago. No hace daño —los que nadie
# completa vencen solos— pero es una llamada a una API ajena por click, así que el límite está
# para que un botón que rebota o un script no la usen de martillo. Generoso a propósito: probar
# con otra tarjeta, arrepentirse y volver es un camino normal, y quedarse sin poder pagar sería
# el peor final posible para el que estaba pagando.
_CHECKOUT_LIMITER = RateLimiter(limit=20, window_seconds=60 * 60)


@router.get("", response_model=SubscriptionRead)
def get_subscription(db: SessionDep, user: CurrentUserDep) -> subscription_service.Entitlements:
    """El plan de la cuenta y lo que le queda del mes.

    **Singular y sin id en la ruta**, como `/auth/me`: el recurso es "mi suscripción" y solo
    existe una. Un `/subscriptions/{id}` daría a entender que se pueden listar o que se puede
    mirar la de otro, que es exactamente lo que no.

    Los otros dos lugares donde el plan aparece no son endpoints nuevos sino campos que se
    sumaron a los que ya estaban —`blocked_reason` en el `preview` de emisión— para que la
    pantalla no tenga que combinar dos respuestas antes de decidir si el botón se ofrece.
    """
    return subscription_service.entitlements(db, user.id)


@router.get("/plans", response_model=PlanOffer)
def get_plans() -> PlanOffer:
    """La lista de precios y si este servidor puede cobrar.

    **No mira la cuenta ni toca la base**, y por eso no recibe ni `db` ni el usuario: lo que
    devuelve es igual para todos. Sigue exigiendo sesión —la dependencia está en el router—
    porque es la pantalla del plan la que lo consulta y no hay ninguna razón para publicar la
    lista de precios en un endpoint anónimo.

    Está separado de `GET /subscription` a propósito: aquel lo pide el contexto en cada
    sesión y lo leen seis lugares, y el precio lo mira una sola pantalla. Ver `PlanOffer`.
    """
    reason = mercadopago.unavailable_reason()
    return PlanOffer(
        available=reason is None,
        unavailable_reason=reason,
        currency=subscription_service.CURRENCY,
        monthly_price=subscription_service.price(BillingInterval.MONTHLY),
        yearly_price=subscription_service.price(BillingInterval.YEARLY),
    )


@router.post("/checkout", response_model=CheckoutStart)
def start_checkout(
    payload: CheckoutRequest, db: SessionDep, user: CurrentUserDep
) -> CheckoutStart:
    """Arma el checkout de Mercado Pago y devuelve a dónde mandar al navegador.

    **No cambia el plan, y esa es toda la idea.** Lo único que produce es una URL: el usuario
    autoriza el débito del otro lado, Mercado Pago avisa por webhook y recién ahí la fila pasa
    a `ACTIVE`. Si esta llamada activara algo, sería un endpoint para hacerse Pro con un
    `curl` — ver `schemas/subscription.py`.

    **El que ya está pagando no puede volver a contratar.** Un segundo `preapproval` sobre la
    misma cuenta son dos débitos automáticos por el mismo servicio, y el usuario se entera por
    el resumen. En cambio el `PAST_DUE` **sí** puede: es justamente el que necesita rehacer la
    autorización con otra tarjeta, y ahí se cancela primero la que viene fallando para que no
    queden las dos vivas.
    """
    reason = mercadopago.unavailable_reason()
    if reason is not None:
        # 503 y no 500: no está roto, está sin configurar, y lo que falta lo pone quien
        # administra el servidor. Es el mismo criterio que `SecretsNotConfiguredError`.
        raise HTTPException(status_code=503, detail=reason)

    enforce_rate_limit(_CHECKOUT_LIMITER, str(user.id))

    subscription = subscription_crud.get_for_user(db, user.id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Esta cuenta no tiene ninguna suscripción.")

    if (
        subscription.status is SubscriptionStatus.ACTIVE
        and subscription.provider_subscription_id is not None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta cuenta ya tiene una suscripción activa. Si querés cambiar el medio de "
                "pago, dala de baja primero y volvé a contratarla."
            ),
        )

    try:
        if (
            subscription.status is SubscriptionStatus.PAST_DUE
            and subscription.provider_subscription_id is not None
        ):
            # Se cancela la anterior antes de crear la nueva, y no después: al revés, un fallo
            # en el medio dejaría dos débitos automáticos vivos, que es el único desenlace
            # que le cuesta plata al usuario.
            mercadopago.cancel_preapproval(subscription.provider_subscription_id)
            subscription.provider_subscription_id = None
            db.flush()

        checkout = mercadopago.create_checkout(user, subscription, payload.interval)
    except MercadoPagoError as error:
        # 502 y no 500: el que falló es el proveedor, no esta app. El texto de Mercado Pago
        # entra envuelto en una frase que sí se entiende — el suyo está escrito para quien
        # programa la integración, no para quien está intentando pagar.
        raise HTTPException(
            status_code=502, detail=f"No se pudo abrir el pago con Mercado Pago. {error}"
        ) from error

    return CheckoutStart(init_point=checkout.init_point)


@router.post("/cancel", response_model=SubscriptionRead)
def cancel_subscription(db: SessionDep, user: CurrentUserDep) -> subscription_service.Entitlements:
    """Dar de baja: no se renueva más, pero el período que ya está pago se termina de usar.

    **`POST /subscription/cancel` y no `DELETE /subscription`.** El DELETE diría que la
    suscripción desaparece, y acá no desaparece nada: la fila queda, el acceso sigue hasta
    `current_period_end` y volver a pagar es la misma fila pasando a `ACTIVE` otra vez. Es una
    transición de estado, no un borrado, y la ruta tiene que decir eso.

    **Sin body**, que es la otra mitad del diseño de `schemas/subscription.py`: la baja es el
    único cambio de plan que el usuario pide desde la app. Todo lo demás lo escribe el
    proveedor cuando un cobro se acredita — un PATCH del plan sería un endpoint para hacerse
    Pro gratis.

    **Devuelve los entitlements y no un 204.** La pantalla que aprieta el botón muestra el
    estado y la fecha hasta la que sigue habiendo acceso, y las dos cambian con esta llamada:
    contestar vacío la obligaría a un `GET` inmediatamente después para pintar lo que el
    usuario acaba de hacer.

    **Primero Mercado Pago y después la fila, y si Mercado Pago no confirma no se marca
    nada.** Es la decisión más importante del endpoint: una baja que existe solo de este lado
    deja al proveedor cobrando todos los meses una suscripción que la app da por terminada, y
    el usuario se entera por el resumen de la tarjeta. Contestar 502 y que vuelva a intentar
    es molesto; cobrarle de más, no.

    **Idempotente.** Dar de baja dos veces contesta lo mismo y no vuelve a escribir
    `canceled_at`: esa columna registra *cuándo lo pidió*, y pisarla con el segundo click —o
    con el reintento de una respuesta que se perdió— la haría mentir sobre una fecha que ya
    ocurrió.

    Un Free —trial vencido, nunca pagó— también puede llamar y no es un error: su fila queda
    en `CANCELED` y el acceso no cambia, porque ya no había ninguno que cortar. Inventarle un
    409 sería un caso más para el frontend a cambio de nada.
    """
    subscription = subscription_crud.get_for_user(db, user.id)
    if subscription is None:
        # El caso anómalo que `entitlements` loguea y trata como Free. Acá no se puede tratar
        # como nada: no hay fila que marcar. 404 sobre el recurso que se quiso tocar.
        raise HTTPException(status_code=404, detail="Esta cuenta no tiene ninguna suscripción.")

    if subscription.status is not SubscriptionStatus.CANCELED:
        if (
            subscription.provider is BillingProvider.MERCADO_PAGO
            and subscription.provider_subscription_id is not None
        ):
            try:
                mercadopago.cancel_preapproval(subscription.provider_subscription_id)
            except MercadoPagoError as error:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "No pudimos dar de baja el débito automático en Mercado Pago, así que "
                        f"la suscripción sigue como está. Probá de nuevo en un rato. {error}"
                    ),
                ) from error
        subscription_crud.cancel(db, subscription)

    return subscription_service.entitlements(db, user.id)


# --- El webhook -----------------------------------------------------------------------------
#
# Router aparte y **sin la dependencia de sesión**, como `fiscal_identity.delegation_router`:
# quien lo llama es un servidor de Mercado Pago, que no tiene ninguna cookie de esta app. Su
# autenticación es la firma, y por eso no puede colgar del router de arriba ni siquiera con un
# `dependencies=[]` local — un router entero sin sesión hace evidente qué es lo que no la pide.
#
# Fuera de `/subscription` a propósito: la ruta la copia y pega alguien en el panel de Mercado
# Pago, y `/webhooks/mercado-pago` dice qué es y de quién sin tener que leer el código.

webhook_router = APIRouter(prefix="/webhooks", tags=["subscription"])


@webhook_router.post("/mercado-pago")
def mercado_pago_webhook(
    db: SessionDep,
    payload: Annotated[MercadoPagoNotification | None, Body()] = None,
    # El formato viejo (IPN) manda todo por query y a veces sin cuerpo. Se aceptan los dos
    # porque cuál llega lo decide la configuración del panel de Mercado Pago, no esta app.
    query_type: Annotated[str | None, Query(alias="type")] = None,
    query_topic: Annotated[str | None, Query(alias="topic")] = None,
    query_data_id: Annotated[str | None, Query(alias="data.id")] = None,
    query_id: Annotated[str | None, Query(alias="id")] = None,
    signature: Annotated[str | None, Header(alias="x-signature")] = None,
    request_id: Annotated[str | None, Header(alias="x-request-id")] = None,
) -> dict[str, str]:
    """Lo que Mercado Pago avisa: una autorización que cambió, o un cobro que entró o falló.

    **Es el único endpoint de la app que puede volver Pro a una cuenta**, y no tiene sesión.
    De ahí que lo primero que haga sea verificar la firma y que un fallo de firma sea 401:
    sin eso, cualquiera con la URL se suscribe gratis con un `curl`.

    **Sincrónico y no `async`.** Todo lo que hace adentro es sincrónico —SQLAlchemy y
    `requests` contra Mercado Pago—, así que un `async def` bloquearía el event loop durante
    toda la conversación con ellos. Con `def`, FastAPI lo corre en el threadpool.

    Qué status contesta importa más que de costumbre, porque del otro lado hay una máquina que
    lee la respuesta y decide si reintenta:

    - **200** cuando se aplicó, y también cuando no había nada que aplicar (un tema que a esta
      app no le mueve nada, un cobro todavía en vuelo, un duplicado). Reintentar eso sería
      reintentarlo para siempre.
    - **401** si la firma no cierra. No se reintenta y está bien: no va a mejorar.
    - **503** si a este servidor le falta el secreto con el que se verifica. Es config que
      falta, y el reintento de Mercado Pago es exactamente lo que se quiere: cuando la
      variable esté puesta, el aviso vuelve.
    - **502** si Mercado Pago no contestó cuando fuimos a leer el recurso. También se quiere
      el reintento: ese evento puede ser el cobro que activa una cuenta, y perderlo sale mucho
      más caro que procesarlo tarde.

    El cuerpo de la respuesta dice qué se hizo. No lo lee ningún programa —Mercado Pago solo
    mira el status— pero queda en el panel de notificaciones, que es donde se mira cuando algo
    no anda.
    """
    data_id = None
    if payload is not None and payload.data is not None:
        raw = payload.data.get("id")
        data_id = str(raw) if raw is not None else None
    data_id = data_id or query_data_id or query_id or (
        str(payload.id) if payload is not None and payload.id is not None else None
    )
    topic = (payload.type or payload.topic if payload is not None else None) or (
        query_type or query_topic
    )

    try:
        mercadopago.verify_signature(
            signature=signature, request_id=request_id, data_id=data_id
        )
    except WebhookSignatureError as error:
        # Warning y no error: llegar acá es lo esperable cuando alguien prueba la URL, y un
        # ERROR por cada sonda de internet enterraría los que sí importan.
        logger.warning("Se rechazó una notificación de Mercado Pago: %s", error)
        raise HTTPException(status_code=401, detail=str(error)) from error
    except MercadoPagoError as error:
        logger.error(
            "Llegó una notificación de Mercado Pago y este servidor no puede verificarla: %s",
            error,
        )
        raise HTTPException(status_code=503, detail=str(error)) from error

    try:
        result = mercadopago.handle_notification(db, topic, data_id)
    except MercadoPagoError as error:
        logger.warning(
            "No se pudo procesar la notificación %s/%s de Mercado Pago: %s",
            topic,
            data_id,
            error,
        )
        raise HTTPException(status_code=502, detail=str(error)) from error

    logger.info("Notificación %s/%s de Mercado Pago: %s.", topic, data_id, result)
    return {"result": result}
