import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from factumov.enums import BillingInterval, BillingProvider, SubscriptionStatus
from factumov.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from factumov.models.user import User


class Subscription(Base, TimestampMixin):
    """La relación comercial con un usuario: qué estado tiene y hasta cuándo está paga.

    **Una tabla y no columnas en `users`**, al revés que las cuatro de `balance360_*` en
    `invoices`. Aquellas son 1 a 1, sin historia y se leen en la misma grilla que la factura,
    así que sacarlas afuera solo agregaba un join. Acá pasa lo contrario en los tres puntos:
    es una relación comercial con su propia contraparte del lado de Mercado Pago —ids de
    proveedor, intervalo, vencimiento—, la va a acompañar una tabla de pagos cuando exista el
    webhook, y no se lee en cada request sino solo en los endpoints que cobran algo. Mezclarla
    con la tabla de autenticación pondría datos del proveedor de pagos al lado del hash de la
    contraseña sin ninguna razón estructural.

    **Lo que la tabla guarda son hechos; el plan efectivo se deduce.** No hay columna `plan`
    ni columna `is_pro`: si estuvieran, el día que `current_period_end` quede en el pasado la
    fila diría "PRO" y "vencida" a la vez. Es el mismo argumento por el que `voucher_type`
    dejó de ser columna de `invoice_templates` — ver *Modelo de datos → La letra del
    comprobante se deduce*. Quién es Pro lo contesta `services/subscription.py`, que es
    también donde vive la política (los días de gracia, el largo del trial, los límites del
    Free), porque son números comerciales que cambian por decisión y no por migración.

    **Toda cuenta tiene fila desde el registro**, con el trial ya corriendo. La alternativa
    —fila solo para el que paga, ausencia = Free— ahorraba un INSERT y obligaba a que cada
    lector tratara el `None` como un estado más; con el trial automático, además, la fila
    aparecía igual en el 100% de los casos.
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # `unique` y no un índice a secas: "la suscripción del usuario" es una sola fila. Sin
    # `ondelete`, como las demás FK a `users` — el NO ACTION por defecto hace fallar el
    # borrado de un usuario con datos, y elegir entre cascada y anonimizar es trabajo de la
    # unidad de baja de cuenta.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus))
    # Hasta cuándo llega lo que el usuario tiene: el fin del trial mientras está `TRIALING`,
    # y el fin del período pagado después. Una sola columna para los dos porque la pregunta
    # que contestan es la misma —"¿hasta cuándo?"— y dos columnas exigirían que cada lector
    # eligiera cuál mirar según el estado, o sea la misma rama repetida en todos lados.
    #
    # No es "hasta cuándo tiene acceso": la gracia posterior al vencimiento se suma al leer,
    # no acá. Guardarla sumada haría que la fecha que la pantalla muestra ("se renueva el
    # 28") y la que decide el acceso fueran la misma columna diciendo dos cosas.
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # `None` mientras es trial: no se cobra, así que no hay cada cuánto.
    billing_interval: Mapped[BillingInterval | None] = mapped_column(Enum(BillingInterval))
    provider: Mapped[BillingProvider | None] = mapped_column(Enum(BillingProvider))
    # El `preapproval_id` de Mercado Pago, o `None` si todavía no hay débito automático
    # asociado. Es lo que permite ir de un webhook a la fila sin buscar por usuario, y lo que
    # hay que cancelar del otro lado cuando el usuario da de baja.
    #
    # `unique` porque una suscripción del proveedor no puede estar atada a dos usuarios; el
    # día que el webhook exista, ese unique es lo que convierte un cruce de ids en un error en
    # vez de en un cobro atribuido a la cuenta equivocada. Postgres deja repetir el NULL, que
    # es lo que tienen todas las filas en trial.
    provider_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Cuándo el usuario pidió la baja. No corta el acceso: lo que corta es que
    # `current_period_end` pase, y hasta ese día el período ya está pagado. Timestamp y no
    # booleano, mismo criterio que `email_confirmed_at` y `delegation_verified_at`.
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Sin `back_populates`, igual que `Balance360Connection.user`: nada necesita navegar de
    # `User` hacia acá —el CRUD busca por `user_id`, como `balance360_connection.get_for_user`—
    # y declarar el lado inverso obligaría a decidir hoy el cascade del borrado de una cuenta,
    # que es la decisión que la unidad de baja todavía no tomó.
    user: Mapped["User"] = relationship()
