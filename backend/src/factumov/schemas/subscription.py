"""Salida del estado del plan. **No hay schema de entrada, y eso es la mitad del diseño.**

El usuario no elige su plan mandando un PATCH: el plan es consecuencia de que un pago se haya
acreditado, y el que acredita es el proveedor. Un endpoint de escritura acá sería un endpoint
para hacerse Pro gratis. La transición la escribe el webhook de Mercado Pago, contra su
propia firma; el único cambio que el usuario pide desde la app es la baja, que es su propio
endpoint sin body.

Lo que sí tiene entrada es el **checkout**, y no contradice lo anterior: `CheckoutRequest` no
elige un plan, elige qué se va a pagar. Lo único que produce es una URL de Mercado Pago; el
plan lo sigue escribiendo el webhook cuando el cobro se acredita, y postear acá sin pagar no
mueve una sola columna.
"""

import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from factumov.enums import BillingInterval, SubscriptionStatus


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


class PlanOffer(BaseModel):
    """Qué se puede contratar y a qué precio. **Es del servidor, no de la cuenta.**

    Va aparte de `SubscriptionRead` y no como tres campos más, aunque eso ahorrara un request.
    `SubscriptionRead` lo pide el contexto una vez por sesión y lo consultan seis lugares que
    fueron a hacer otra cosa; la lista de precios la mira **una** pantalla, la del plan, y
    solo cuando alguien entra a ella. Mezclarlas sería mandarle el precio a cada carga de la
    app para que lo lea el 1% de las veces.
    """

    # Si el botón de pago tiene sentido en este servidor. Es config de la instalación —el
    # token y el secreto del webhook— y no algo del usuario.
    available: bool
    # Qué falta, cuando falta. Lo lee el operador en la pantalla, que es donde se nota; el
    # texto nombra la variable de entorno porque es lo único que dice dónde tocar.
    unavailable_reason: str | None
    currency: str
    # Como string en el JSON, igual que todos los importes del proyecto: Pydantic serializa
    # `Decimal` a string para que no pase por el float de JavaScript.
    monthly_price: Decimal
    yearly_price: Decimal


class CheckoutRequest(BaseModel):
    """Qué se quiere pagar: el mes o el año.

    Es el único campo, y es lo único que el usuario elige. Ni el precio ni la moneda viajan
    desde el cliente — un importe mandado por el navegador sería un formulario para elegir
    cuánto pagar.
    """

    interval: BillingInterval


class CheckoutStart(BaseModel):
    """A dónde mandar al navegador para pagar.

    Solo la URL: el `preapproval_id` se queda del lado del servidor. El frontend no tiene nada
    que hacer con él —no lo puede usar para nada, y la fila lo recibe recién cuando el webhook
    confirma la autorización— así que mandarlo sería publicar un identificador del proveedor
    sin ningún uso.
    """

    init_point: str


class MercadoPagoNotification(BaseModel):
    """El cuerpo de una notificación de Mercado Pago, leído con la mano floja.

    **Todo opcional y `extra="ignore"`**, al revés que el resto de los schemas del proyecto.
    No es un contrato nuestro: lo define Mercado Pago, lo cambia sin avisar y manda el mismo
    aviso en dos formatos —el webhook moderno con `type`/`data.id` en el cuerpo, y el IPN
    viejo con `topic`/`id` en la query, a veces sin cuerpo—. Un schema estricto convertiría
    cualquiera de esas variantes en un 422, y un 422 le dice a Mercado Pago que reintente
    para siempre algo que nunca vamos a poder leer.

    Los campos que de verdad deciden algo son dos —de qué tipo de recurso habla y cuál es su
    id— y los dos se validan igual leyendo el recurso contra la API antes de escribir nada.
    """

    model_config = ConfigDict(extra="ignore")

    # El formato nuevo dice `type`; el viejo, `topic`. Se aceptan los dos y el router elige
    # el que vino.
    type: str | None = None
    topic: str | None = None
    # `payment.created`, `updated`… No se usa: qué hacer lo decide el estado que el recurso
    # tenga cuando se lo lea, no el nombre del evento que avisó.
    action: str | None = None
    data: dict[str, Any] | None = None
    # El id del recurso en el formato viejo. Puede venir como número.
    id: str | int | None = None
