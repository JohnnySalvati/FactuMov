from fastapi import APIRouter, Depends

from factumov.dependencies import CurrentUserDep, SessionDep, get_current_user
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

    Es el único endpoint de esta unidad. Los otros dos lugares donde el plan aparece no son
    endpoints nuevos sino campos que se sumaron a los que ya estaban —`blocked_reason` en el
    `preview` de emisión— para que la pantalla no tenga que combinar dos respuestas antes de
    decidir si el botón se ofrece.
    """
    return subscription_service.entitlements(db, user.id)
