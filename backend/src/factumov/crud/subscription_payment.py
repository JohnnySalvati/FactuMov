"""Acceso a datos de `subscription_payments`: el historial de cobros y el antiduplicado.

**Este módulo tampoco decide nada comercial.** Recibe un cobro ya interpretado —cuánto, en qué
moneda, si entró o no— y lo escribe. Quién traduce un evento de Mercado Pago a eso es
`services/mercadopago.py`, y qué hace ese cobro con el plan lo decide
`crud/subscription.py` a través de `activate` y `mark_past_due`.

Lo único que sí vive acá es **la regla de idempotencia**, porque es una propiedad de la fila:
un cobro es el mismo cobro si tiene el mismo id del proveedor, y es una novedad si además
cambió de estado.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from factumov.enums import BillingProvider, PaymentStatus
from factumov.models.subscription_payment import SubscriptionPayment


def get_by_provider_payment_id(db: Session, provider_payment_id: str) -> SubscriptionPayment | None:
    return (
        db.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.provider_payment_id == provider_payment_id
            )
        )
        .scalars()
        .first()
    )


def is_already_applied(db: Session, provider_payment_id: str, status: PaymentStatus) -> bool:
    """¿Este cobro, **en este estado**, ya se procesó?

    El par y no el id solo. Mercado Pago recicla un cobro rechazado —lo reintenta durante
    días con la misma referencia— así que el mismo id vuelve más adelante ya aprobado: filtrar
    por id dejaría a un usuario que pagó en `PAST_DUE` hasta que se le acabe la gracia. Y
    filtrar por nada dejaría que los reintentos del webhook, que llegan varias veces por
    cobro, empujaran el período una vez por entrega.
    """
    existing = get_by_provider_payment_id(db, provider_payment_id)
    return existing is not None and existing.status is status


def record(
    db: Session,
    *,
    subscription_id: uuid.UUID,
    provider: BillingProvider,
    provider_payment_id: str,
    status: PaymentStatus,
    amount: Decimal,
    currency: str,
    charged_at: datetime | None,
) -> SubscriptionPayment:
    """Deja anotado el cobro, o actualiza el que ya estaba si cambió de estado.

    Un upsert y no un insert a secas por el reciclado: el rechazo que después entra es el
    **mismo** cobro y no uno nuevo, así que dos filas contarían dos veces en el historial y
    romperían el `unique` de `provider_payment_id`, que es el que protege de duplicar el
    período cuando dos entregas del webhook llegan a la vez.
    """
    payment = get_by_provider_payment_id(db, provider_payment_id)
    if payment is None:
        payment = SubscriptionPayment(
            subscription_id=subscription_id,
            provider=provider,
            provider_payment_id=provider_payment_id,
            status=status,
            amount=amount,
            currency=currency,
            charged_at=charged_at,
        )
        db.add(payment)
    else:
        payment.status = status
        payment.amount = amount
        payment.currency = currency
        payment.charged_at = charged_at
    db.flush()
    return payment


def list_for_subscription(db: Session, subscription_id: uuid.UUID) -> list[SubscriptionPayment]:
    """Los cobros de una suscripción, del más nuevo al más viejo.

    Todavía no lo muestra ninguna pantalla. Existe porque el historial es la mitad del motivo
    de esta tabla —la otra es la idempotencia— y porque es la consulta con la que se contesta
    "¿de qué me cobraron?" cuando alguien lo pregunte por mail, que hoy es la única forma en
    la que esa pregunta llega.
    """
    return list(
        db.execute(
            select(SubscriptionPayment)
            .where(SubscriptionPayment.subscription_id == subscription_id)
            .order_by(SubscriptionPayment.charged_at.desc().nullslast())
        )
        .scalars()
        .all()
    )
