import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import BillingProvider, PaymentStatus
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.subscription import Subscription


class SubscriptionPayment(Base, TimestampMixin):
    """Cada cobro que el proveedor informó. **Es a la vez el historial y el antiduplicado.**

    Las dos cosas en una tabla y no en dos, porque son la misma pregunta hecha con distinta
    intención: "¿este cobro ya lo procesamos?" y "¿de qué se le cobró a esta cuenta?" se
    contestan las dos con la lista de cobros. Una tabla aparte de ids vistos —el
    `processed_webhook_events` del manual— guardaría los mismos ids sin el importe ni la
    fecha, o sea el registro de idempotencia sin el único dato que además sirve para algo.

    **El webhook de Mercado Pago llega más de una vez.** MP reintenta ante cualquier respuesta
    que no sea 2xx, y también manda el mismo evento por dos canales distintos; sin esta tabla,
    tres entregas del mismo cobro empujarían el período tres meses. `provider_payment_id` es
    `unique` justamente para que eso sea imposible incluso si dos entregas llegan a la vez a
    dos workers: la segunda choca contra la restricción en vez de duplicar el período.

    **La idempotencia es sobre el par (id, estado) y no sobre el id solo**, y eso no es un
    detalle. Mercado Pago *recicla* un cobro rechazado: reintenta la misma tarjeta durante
    varios días **con el mismo id**, y cuando por fin entra manda otra notificación sobre esa
    misma referencia con el estado ya en `approved`. Descartando por id, esa aprobación se
    perdería y el usuario quedaría en `PAST_DUE` hasta que la gracia se le acabe, habiendo
    pagado. Por eso la fila guarda su `status` y el reintento con un estado **distinto** se
    aplica y actualiza la fila — ver `crud/subscription_payment.py`.

    **No lleva `user_id`.** Cuelga de la suscripción, que ya tiene uno solo por definición
    (`subscriptions.user_id` es `unique`), así que una segunda columna sería una copia que
    puede desincronizarse. Es el mismo criterio que `invoices`, que se scopea por join contra
    `fiscal_identities`.
    """

    __tablename__ = "subscription_payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Con índice: la lectura natural es "los cobros de esta suscripción", en orden.
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id"), index=True
    )
    # De qué proveedor vino. Está acá además de en `subscriptions.provider` porque el de la
    # suscripción es el de **hoy**: una cuenta que pagó un año por transferencia y después
    # contrató el débito automático tiene filas de los dos, y sin esta columna el historial
    # diría que todas entraron por el último.
    provider: Mapped[BillingProvider] = mapped_column(Enum(BillingProvider))
    # El id del cobro del lado del proveedor: el `authorized_payment` de Mercado Pago. Es la
    # clave de idempotencia, y por eso es `unique` a nivel base y no solo un chequeo en el
    # servicio: el chequeo pierde contra dos entregas simultáneas, la restricción no.
    provider_payment_id: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus))
    # Lo que se cobró, tal como lo informó el proveedor y no como lo dice la lista de precios:
    # el precio se va a cambiar, y una fila vieja tiene que seguir diciendo lo que se pagó ese
    # día. Misma precisión que los importes de `invoices`.
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=2))
    # ISO 4217. Hoy siempre "ARS" —el precio está anclado en dólares pero se cobra en pesos—,
    # y guardarla igual es lo que hace que un importe viejo se pueda seguir leyendo el día que
    # eso cambie.
    currency: Mapped[str] = mapped_column(String(3))
    # Cuándo lo cobró el proveedor, según el proveedor. No es `created_at`: entre el cobro y
    # la notificación que lo trae puede haber horas, y más todavía si el webhook se reintentó.
    charged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    subscription: Mapped["Subscription"] = relationship()
