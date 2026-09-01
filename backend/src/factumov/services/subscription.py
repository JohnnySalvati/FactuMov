"""La política comercial de FactuMov: quién es Pro, qué puede hacer un Free y hasta cuándo.

**Toda la política está en las cuatro constantes de acá arriba.** Es a propósito: el largo del
trial, los días de gracia y los dos límites del Free son números que se cambian por decisión
comercial —y se van a cambiar— así que no pueden estar repartidos entre una columna, un
`if` en un router y una constante del frontend. Cambiar el corte del Free tiene que ser editar
un número, correr los tests y listo.

**Y por eso `subscriptions` no guarda ni el plan ni el acceso.** La fila guarda hechos —en qué
estado está, hasta cuándo llega lo pagado— y este módulo los lee contra la política de hoy. Si
el plan fuera una columna, subir la gracia de 10 a 15 días sería una migración que reescribe
filas, y una fila vieja seguiría diciendo lo que la política decía el día que se escribió. Es
el mismo argumento por el que `voucher_type` se deduce en `invoice_templates` — ver
*Modelo de datos → La letra del comprobante se deduce*.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factumov.crud import subscription as subscription_crud
from factumov.enums import BillingInterval, SubscriptionStatus
from factumov.exceptions import PlanLimitReachedError
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.models.invoice import Invoice
from factumov.models.subscription import Subscription

logger = logging.getLogger(__name__)

# Cuánto dura la prueba de Pro con la que nace toda cuenta. Arranca en el registro y no en la
# confirmación del mail: son minutos de diferencia en el caso normal, y ponerlo en el registro
# deja un solo lugar donde la fila puede nacer.
TRIAL_DAYS = 30

# Cuántos días sigue siendo Pro una suscripción cuyo cobro falló. Existe porque las tarjetas se
# vencen, se reemiten y se rechazan por saldo todo el tiempo: cortar al primer rechazo pierde
# clientes que querían pagar. **No se aplica al trial ni a la baja voluntaria** — ver `is_pro`.
PAST_DUE_GRACE_DAYS = 10

# El corte del Free. Es por volumen y no por cantidad de identidades fiscales, y esa es la
# decisión de producto más importante de la unidad: el usuario típico de FactuMov es un
# monotributista con **un solo** CUIT, así que un Free limitado a una entidad le regala el
# producto completo y no lo hace pagar nunca. El volumen, en cambio, crece con el uso: el que
# factura tres veces por mes se queda gratis y recomienda, y el que factura treinta convierte.
FREE_MONTHLY_INVOICES = 5

# Multi-entidad sigue siendo Pro, pero como el segundo límite y no como el único.
FREE_FISCAL_IDENTITIES = 1

# La moneda en la que se cobra. El precio está **anclado en dólares y cobrado en pesos**: un
# precio fijo en pesos se lo come la inflación, y cobrar en dólares mete una fricción enorme en
# una app de consumo local. ISO 4217, que es lo que espera Mercado Pago en `currency_id`.
CURRENCY = "ARS"

# La lista de precios, en pesos. Está acá y no en el `.env` por lo mismo que el largo del trial
# y los dos límites del Free: es política comercial, y lo que cambia un precio es una decisión
# que se toma una vez y se acompaña con los tests, no una variable de entorno que cada
# instalación puede tener distinta — dos servidores cobrando distinto por el mismo plan es un
# problema mucho peor que un deploy.
#
# **El anual vale diez mensuales**, o sea dos meses bonificados (~17%). No más: con un 50% de
# descuento todos eligen anual —hacen bien— y se pierde la mitad del ingreso a cambio de un
# flujo de caja que a esta escala no hace falta.
#
# El número en pesos es lo único de la política que se desactualiza solo, porque el ancla es en
# dólares: se revisa periódicamente y se anuncia. Ver *Monetización → Precios y cobro*.
PRICES = {
    BillingInterval.MONTHLY: Decimal("7000"),
    BillingInterval.YEARLY: Decimal("70000"),
}


def price(interval: BillingInterval) -> Decimal:
    """Cuánto sale ese plan, hoy y en pesos."""
    return PRICES[interval]


# El mes se corta en hora argentina y no en UTC. Con UTC, las facturas emitidas entre las 21 y
# la medianoche del último día del mes caerían en el mes siguiente: el usuario vería el
# contador reiniciarse tres horas antes de tiempo, y peor, un 30 a la noche gastaría cupo del
# mes que todavía no empezó. Es el mismo error de un día que `isoDate` evita en el frontend.
_ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")


@dataclass(frozen=True)
class Entitlements:
    """Qué puede hacer esta cuenta ahora mismo, resuelto de una sola vez.

    Un objeto y no una función por pregunta porque los tres lugares que lo consultan —el
    endpoint de la suscripción, el `preview` de emisión y el alta de identidad fiscal— quieren
    además los números para mostrarlos ("usaste 4 de 5 este mes"). Devolver solo un booleano
    obligaría a repetir los mismos `COUNT` desde la pantalla.

    Los `*_limit` en `None` significan **sin límite**, que es lo que tiene un Pro. Cero sería
    lo contrario y es justo el valor que un `int | None` mal leído produce.
    """

    is_pro: bool
    status: SubscriptionStatus | None
    current_period_end: datetime | None
    invoices_used: int
    invoices_limit: int | None
    fiscal_identities_used: int
    fiscal_identities_limit: int | None

    @property
    def can_emit(self) -> bool:
        return self.invoices_limit is None or self.invoices_used < self.invoices_limit

    @property
    def can_add_fiscal_identity(self) -> bool:
        return (
            self.fiscal_identities_limit is None
            or self.fiscal_identities_used < self.fiscal_identities_limit
        )

    @property
    def custom_email_enabled(self) -> bool:
        """El texto del mail con el que se manda la factura se escribe con el plan Pro.

        Es el único derecho de esta lista que decide **dos** cosas, y por eso se consulta desde
        dos lados: si el modelo puede guardar un texto propio (lo corta
        `check_can_customize_email` en el router del modelo) y si ese texto se usa al mandar la
        factura (lo mira `POST /invoices/{id}/send`).

        La segunda mitad es lo que distingue este límite del de las identidades fiscales. Allá
        el Free que fue Pro conserva las tres que cargó y las sigue usando: bajar de plan no
        borra datos, y elegir cuál sobrevive no le corresponde a la app. Acá el dato tampoco se
        borra —el texto queda guardado y vuelve solo si la cuenta vuelve a Pro— pero deja de
        usarse: lo que el Free recupera es el mail por default, que es el que la app manda
        desde siempre y dice lo mismo. La diferencia con una identidad fiscal es que ahí "dejar
        de usarla" significaría no poder facturar con ese CUIT, y acá significa mandar el otro
        texto.
        """
        return self.is_pro

    @property
    def voice_enabled(self) -> bool:
        """El dictado por voz es Pro.

        Es el único derecho de esta lista que el backend **no puede hacer cumplir**: la voz
        corre entera en el navegador (Web Speech API) y lo único que llega acá es el formulario
        que llenó. O sea que esto le dice al frontend qué ofrecer, no qué permitir. Y está
        bien: lo que la voz ahorra es la parte reversible del camino —llenar campos—, mientras
        que emitir, que es lo irreversible, pasa igual por `can_emit`.
        """
        return self.is_pro


def start_trial(db: Session, user_id: uuid.UUID) -> Subscription:
    """Le da a una cuenta recién creada sus `TRIAL_DAYS` de Pro."""
    return subscription_crud.create_trialing(
        db, user_id, current_period_end=datetime.now(UTC) + timedelta(days=TRIAL_DAYS)
    )


def is_pro(subscription: Subscription | None, now: datetime | None = None) -> bool:
    """¿Esta suscripción da acceso Pro en este instante?

    Se compara en Python y no en SQL, al revés que el vencimiento de las sesiones y de los
    tokens. Allá la comparación va en el `WHERE` para que la fila vencida ni siquiera se
    traiga; acá la fila se trae siempre —el endpoint de la suscripción devuelve sus campos, y
    la pantalla muestra la fecha— así que un filtro en SQL solo agregaría una segunda consulta
    para contestar algo que ya está en memoria. El riesgo que motivaba aquella regla, mezclar
    un `datetime` naive con uno aware, no existe: la columna es `timezone=True`.

    **La gracia se suma solo en los dos estados en los que un cobro puede llegar tarde.** Un
    trial que se acaba se acaba —diez días más serían cuarenta de trial, no treinta—, y al que
    dio de baja darle diez días de yapa sería pagarle por irse.
    """
    if subscription is None:
        return False
    now = now or datetime.now(UTC)
    if subscription.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE):
        return now < subscription.current_period_end + timedelta(days=PAST_DUE_GRACE_DAYS)
    return now < subscription.current_period_end


def _month_start(now: datetime) -> datetime:
    """El primer instante del mes en curso, en hora argentina."""
    local = now.astimezone(_ARGENTINA)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def count_invoices_this_month(db: Session, user_id: uuid.UUID, now: datetime) -> int:
    """Cuántos comprobantes emitió el usuario en el mes calendario en curso.

    **Se cuenta por `created_at` y no por `invoices.date`.** La fecha del comprobante la elige
    el usuario dentro de la ventana que ARCA permite (±10 días), así que contar por ella
    dejaría esquivar el límite fechando para atrás — y peor, haría que elegir una fecha legítima
    del mes pasado devolviera cupo de este mes. El límite mide uso del servicio, no el
    calendario fiscal; el que mide el calendario fiscal es ARCA y no nosotros.

    No hay contador guardado. El `COUNT` sale de un índice que ya existe y es siempre correcto;
    una columna acumulada habría que rebobinarla cada mes y podría desincronizarse de las filas
    que dice contar — la misma regla de no guardar lo deducible.

    Scopeado por join contra `fiscal_identities`, igual que el resto de las lecturas de
    `invoices`: la tabla no lleva `user_id`.
    """
    return db.execute(
        select(func.count())
        .select_from(Invoice)
        .join(FiscalIdentity, Invoice.fiscal_identity_id == FiscalIdentity.id)
        .where(FiscalIdentity.user_id == user_id, Invoice.created_at >= _month_start(now))
    ).scalar_one()


def count_fiscal_identities(db: Session, user_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count())
        .select_from(FiscalIdentity)
        .where(FiscalIdentity.user_id == user_id)
    ).scalar_one()


def entitlements(db: Session, user_id: uuid.UUID) -> Entitlements:
    """Todo lo que hay que saber del plan de este usuario, en una sola pasada.

    Una cuenta sin fila de suscripción se trata como Free y se loguea. No se le abre un trial
    acá: `start_trial` corre en el registro y la migración le dio uno a cada cuenta que existía,
    así que llegar sin fila significa que algo se rompió — y un trial nuevo cada vez que se
    consulta convertiría ese bug en una prueba gratis infinita. Free es el default seguro.
    """
    subscription = subscription_crud.get_for_user(db, user_id)
    if subscription is None:
        logger.warning(
            "El usuario %s no tiene fila de suscripción; se lo trata como Free.", user_id
        )

    pro = is_pro(subscription)
    return Entitlements(
        is_pro=pro,
        status=subscription.status if subscription else None,
        current_period_end=subscription.current_period_end if subscription else None,
        invoices_used=count_invoices_this_month(db, user_id, datetime.now(UTC)),
        invoices_limit=None if pro else FREE_MONTHLY_INVOICES,
        fiscal_identities_used=count_fiscal_identities(db, user_id),
        fiscal_identities_limit=None if pro else FREE_FISCAL_IDENTITIES,
    )


# --- Los dos mensajes de bloqueo -------------------------------------------------------
#
# Escritos una sola vez y usados en dos lugares cada uno: el que corta la acción y el que la
# anuncia antes de que el usuario la intente (`blocked_reason` del preview, el aviso del alta
# de identidad fiscal). Duplicarlos haría que el cartel y el error terminen diciendo cosas
# distintas sobre el mismo límite.


def invoice_limit_detail() -> str:
    return (
        f"Con el plan Free podés emitir {FREE_MONTHLY_INVOICES} comprobantes por mes y ya "
        "usaste todos. El contador se reinicia el 1° del mes que viene; para emitir sin "
        "límite, pasate a Pro."
    )


def fiscal_identity_limit_detail() -> str:
    return (
        f"Con el plan Free podés tener {FREE_FISCAL_IDENTITIES} identidad fiscal. Para "
        "facturar con varios CUIT, pasate a Pro."
    )


def email_text_detail() -> str:
    return (
        "Escribir el texto del mail con el que se manda cada factura es del plan Pro. Con el "
        "plan Free se manda el texto de FactuMov, que lleva el número del comprobante, el "
        "emisor y el importe."
    )


def check_can_customize_email(db: Session, user_id: uuid.UUID) -> None:
    """Levanta `PlanLimitReachedError` si el plan no permite escribir el texto del mail.

    **Solo corta la escritura**, y lo llama el router únicamente cuando el body trae un texto:
    borrarlo —mandarlo en `null` o en blanco— se permite siempre. Es la salida que necesita un
    ex-Pro que quiere sacarse de encima un texto que ya no puede editar, y además nunca puede
    empeorar nada: lo que deja en su lugar es el mail por default.
    """
    if not entitlements(db, user_id).custom_email_enabled:
        raise PlanLimitReachedError(email_text_detail())


def check_can_emit(db: Session, user_id: uuid.UUID) -> None:
    """Levanta `PlanLimitReachedError` si el usuario ya gastó el cupo del mes.

    Se chequea contra la base y no contra un `Entitlements` que traiga el router, porque este
    es el punto en el que la respuesta tiene consecuencias: dos emisiones en vuelo a la vez
    podrían pasar las dos si el cupo se leyera antes. No es un candado —el que quiera forzar
    la carrera puede colarse una— y no hace falta que lo sea: el daño de un comprobante de más
    en un mes es cero, y el precio de serializar la emisión detrás de un lock de cuota sería
    real.
    """
    entitled = entitlements(db, user_id)
    if not entitled.can_emit:
        raise PlanLimitReachedError(invoice_limit_detail())


def check_can_add_fiscal_identity(db: Session, user_id: uuid.UUID) -> None:
    """Levanta `PlanLimitReachedError` si el Free ya tiene su identidad fiscal.

    **Solo bloquea el alta.** Un Pro que se dio de baja con tres identidades cargadas las
    conserva y las puede seguir usando: bajar de plan nunca borra datos, y elegir cuál de las
    tres sobrevive no es una decisión que le corresponda tomar a la app. Lo que ese usuario sí
    tiene de nuevo es el tope mensual de comprobantes, que es donde el Free aprieta de verdad.
    """
    entitled = entitlements(db, user_id)
    if not entitled.can_add_fiscal_identity:
        raise PlanLimitReachedError(fiscal_identity_limit_detail())
