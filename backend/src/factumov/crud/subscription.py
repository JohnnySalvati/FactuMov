"""Acceso a datos de `subscriptions`.

Scopeado por `user_id` como el resto, aunque acá el scoping sea casi trivial: la tabla tiene
una fila por usuario y `get_for_user` es la única lectura, igual que en
`crud/balance360_connection.py`.

**Este módulo no decide nada comercial.** No sabe cuánto dura el trial, cuántos días de
gracia hay ni qué puede hacer un Free: recibe fechas ya calculadas y escribe filas. La
política vive en `services/subscription.py`, que es donde se la cambia sin tocar SQL — y es
también lo que hace que subir el precio o alargar la gracia sea editar una constante y no
migrar una tabla.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factumov.enums import BillingInterval, BillingProvider, SubscriptionStatus
from factumov.models.subscription import Subscription


def get_for_user(db: Session, user_id: uuid.UUID) -> Subscription | None:
    return (
        db.execute(select(Subscription).where(Subscription.user_id == user_id)).scalars().first()
    )


def create_trialing(db: Session, user_id: uuid.UUID, current_period_end: datetime) -> Subscription:
    """La fila con la que nace toda cuenta: en trial y con el reloj ya corriendo.

    Recibe la fecha en vez de calcularla, igual que `email_confirmation.create`: cuánto dura
    el trial es una decisión comercial y no un detalle del acceso a datos.
    """
    subscription = Subscription(
        user_id=user_id,
        status=SubscriptionStatus.TRIALING,
        current_period_end=current_period_end,
    )
    db.add(subscription)
    db.flush()
    return subscription


def activate(
    db: Session,
    subscription: Subscription,
    *,
    current_period_end: datetime,
    billing_interval: BillingInterval,
    provider: BillingProvider,
    provider_subscription_id: str | None = None,
) -> Subscription:
    """Un cobro entró: el período llega hasta `current_period_end` y el estado vuelve a `ACTIVE`.

    Sirve para las tres transiciones que terminan en un pago acreditado —la primera compra
    desde el trial, la renovación normal y el reintento que rescata a un `PAST_DUE`— porque
    para la fila son la misma escritura. Distinguirlas obligaría a que quien cobra sepa de
    dónde venía el usuario, que es justo lo que el webhook de Mercado Pago no va a saber.

    **Limpia `canceled_at`.** Volver a pagar después de haber dado de baja es una alta nueva;
    dejar la marca puesta haría que la próxima renovación exitosa siguiera diciendo que esta
    suscripción está por terminarse.

    `provider_subscription_id` se pisa solo si viene: un cobro manual por transferencia no
    tiene ninguno y no puede borrar el débito automático que la cuenta ya tenía atado.
    """
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_end = current_period_end
    subscription.billing_interval = billing_interval
    subscription.provider = provider
    subscription.canceled_at = None
    if provider_subscription_id is not None:
        subscription.provider_subscription_id = provider_subscription_id
    db.flush()
    return subscription


def mark_past_due(db: Session, subscription: Subscription) -> Subscription:
    """Falló el cobro de la renovación. **No toca `current_period_end`.**

    Y ahí está toda la gracia: el acceso se calcula sobre esa fecha más los días de gracia
    (ver `services/subscription.py`), así que un cobro fallido deja al usuario adentro sin
    ninguna escritura extra y sin una segunda fecha que mantener sincronizada. Cuando el
    reintento entra, `activate` empuja el período y el estado vuelve solo.
    """
    subscription.status = SubscriptionStatus.PAST_DUE
    db.flush()
    return subscription


def cancel(db: Session, subscription: Subscription) -> Subscription:
    """El usuario pidió la baja. **Tampoco corta el acceso.**

    Lo que queda registrado es que no se va a renovar; el período que ya pagó se termina de
    usar. Cortar en el momento de la baja sería quedarse con plata por un servicio que no se
    presta, y encima le enseña al usuario a no dar de baja hasta el último día.

    `func.now()` y no `datetime.now()`, igual que `user_session.revoke`: el reloj es el de la
    base, que es el mismo contra el que se comparan las demás fechas.
    """
    subscription.status = SubscriptionStatus.CANCELED
    subscription.canceled_at = func.now()
    db.flush()
    return subscription
