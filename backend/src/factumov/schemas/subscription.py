"""Salida del estado del plan. **No hay schema de entrada, y eso es la mitad del diseño.**

El usuario no elige su plan mandando un PATCH: el plan es consecuencia de que un pago se haya
acreditado, y el que acredita es el proveedor. Un endpoint de escritura acá sería un endpoint
para hacerse Pro gratis. La transición la va a escribir el webhook de Mercado Pago, contra su
propia firma; el único cambio que el usuario pide desde la app es la baja, y esa va a ser su
propio endpoint sin body.
"""

import datetime

from pydantic import BaseModel, ConfigDict

from factumov.enums import SubscriptionStatus


class SubscriptionRead(BaseModel):
    """Qué plan tiene la cuenta y qué le queda del mes.

    Es el `Entitlements` de `services/subscription.py` serializado tal cual, propiedades
    incluidas: `from_attributes` las lee igual que a los campos. Se copian y no se calculan de
    nuevo acá justamente para que la pantalla y el endpoint que corta la acción no puedan
    discrepar — el mismo criterio por el que los importes del `preview` salen del backend.
    """

    model_config = ConfigDict(from_attributes=True)

    is_pro: bool
    # `null` solo en el caso anómalo de una cuenta sin fila de suscripción, que
    # `entitlements` trata como Free y loguea. No es un estado que la app pueda producir.
    status: SubscriptionStatus | None
    # Hasta cuándo llega el trial o el período pagado. **No es hasta cuándo hay acceso**: si el
    # cobro falla, los días de gracia se suman después de esta fecha. La pantalla la usa para
    # "se renueva el …", que es la pregunta que el usuario tiene.
    current_period_end: datetime.datetime | None
    invoices_used: int
    # `null` = sin límite, o sea Pro. Cero sería lo contrario, así que la pantalla tiene que
    # leer la ausencia y no la falsedad.
    invoices_limit: int | None
    fiscal_identities_used: int
    fiscal_identities_limit: int | None
    can_emit: bool
    can_add_fiscal_identity: bool
    voice_enabled: bool
