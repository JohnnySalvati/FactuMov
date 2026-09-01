from fastapi import APIRouter, Depends, HTTPException

from factumov.crud import subscription as subscription_crud
from factumov.dependencies import CurrentUserDep, SessionDep, get_current_user
from factumov.enums import SubscriptionStatus
from factumov.schemas.subscription import SubscriptionRead
from factumov.services import subscription as subscription_service

router = APIRouter(
    prefix="/subscription",
    tags=["subscription"],
    dependencies=[Depends(get_current_user)],
)


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


@router.post("/cancel", response_model=SubscriptionRead)
def cancel_subscription(
    db: SessionDep, user: CurrentUserDep
) -> subscription_service.Entitlements:
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
        # ACÁ VA LA BAJA DEL OTRO LADO. Cuando exista el checkout de Mercado Pago, esta fila
        # puede tener un `provider_subscription_id`, y marcarla sin cancelar el `preapproval`
        # dejaría a MP cobrando todos los meses una suscripción que la app da por terminada.
        # Hoy ninguna fila lo tiene —nada lo escribe todavía— así que no hay llamada que
        # hacer; ver *Lo que falta* en `docs/monetizacion.md`.
        subscription_crud.cancel(db, subscription)

    return subscription_service.entitlements(db, user.id)
