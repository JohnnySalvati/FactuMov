import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  BillingInterval,
  SubscriptionStatus,
  type CheckoutStart,
  type PlanOffer,
  type Subscription,
} from '../api/types'
import { Notice } from '../components/Notice'
import { formatTimestamp, money } from '../format'
import { useResource } from '../hooks/useResource'
import { useSubscription } from '../subscription/useSubscription'

/**
 * Cómo se llama el estado de la fila para el que la mira.
 *
 * Los nombres del enum son del proveedor de pagos —`past_due`, `trialing`— y no de nadie que
 * use la app. Traducirlos acá y no en el backend es lo mismo que se hace con `CondicionIva`:
 * el JSON lleva el valor y la pantalla lleva la palabra.
 */
const STATUS_LABELS: Record<SubscriptionStatus, string> = {
  [SubscriptionStatus.trialing]: 'Prueba gratis',
  [SubscriptionStatus.active]: 'Activa',
  [SubscriptionStatus.past_due]: 'Falló el último cobro',
  [SubscriptionStatus.canceled]: 'Dada de baja',
}

/**
 * Qué significa la fecha del período según en qué estado esté la cuenta.
 *
 * **Es una sola columna que quiere decir cuatro cosas**, y por eso el rótulo cambia en vez de
 * decir "current period end" en castellano: para el que está en prueba es cuándo se termina,
 * para el que paga es cuándo se le vuelve a cobrar, y para el que se dio de baja es hasta
 * cuándo le queda lo que ya pagó. La misma fecha con el rótulo equivocado le hace creer al que
 * se dio de baja que le van a cobrar de nuevo.
 *
 * Y no dice hasta cuándo hay **acceso**: cuando un cobro falla, el backend suma sus días de
 * gracia después de esta fecha. Esos días no se nombran acá a propósito — son una constante
 * comercial que vive en `services/subscription.py` y que se va a cambiar, y una copia en el
 * frontend es una copia que va a quedar vieja sin que nadie se entere.
 */
function periodLabel(plan: Subscription): string {
  switch (plan.status) {
    case SubscriptionStatus.trialing:
      return plan.is_pro ? 'La prueba termina el' : 'La prueba terminó el'
    case SubscriptionStatus.active:
      return 'Se renueva el'
    case SubscriptionStatus.past_due:
      return 'Estaba paga hasta el'
    case SubscriptionStatus.canceled:
      return plan.is_pro ? 'Seguís con Pro hasta el' : 'Terminó el'
    default:
      return 'Hasta el'
  }
}

/**
 * Los botones que abren el checkout de Mercado Pago.
 *
 * **Pide los precios con su propio `useResource` y no desde el contexto del plan.** Es el caso
 * que `SubscriptionProvider` no cubre a propósito: el plan de la cuenta lo leen seis lugares en
 * cada sesión, y la lista de precios la mira solo quien está mirando esta caja. Montada acá
 * adentro, la consulta ocurre cuando la caja se muestra y no cuando se abre la app.
 *
 * **Lo que el botón hace es irse de la SPA.** El checkout lo hostea Mercado Pago —así FactuMov
 * nunca ve un número de tarjeta— así que esto es un `location.href` y no un `navigate`: el
 * destino es otro dominio. Y por eso `busy` no se apaga cuando la llamada sale bien: el
 * navegador ya se está yendo, y devolverle el estado normal a los botones sería un parpadeo
 * ofreciendo otra vez algo que ya se está haciendo.
 *
 * **Volver de ahí no hace Pro a nadie.** Quien activa la cuenta es el webhook, que llega por
 * atrás y puede tardar unos segundos; el regreso solo trae un `?pago=listo` que la pantalla usa
 * para explicarlo — ver `PlanPage`.
 */
function SubscribeBox() {
  const fetcher = useCallback(() => api.get<PlanOffer>('/subscription/plans'), [])
  const { data: offer, error } = useResource(fetcher)

  // Cuál de los dos botones se apretó, y no un booleano: es lo que deja poner "Abriendo…" en
  // el que se tocó sin apagar los dos.
  const [busy, setBusy] = useState<BillingInterval>()
  const [failure, setFailure] = useState<string>()

  async function subscribe(interval: BillingInterval) {
    if (busy !== undefined) return
    setBusy(interval)
    setFailure(undefined)
    try {
      const start = await api.post<CheckoutStart>('/subscription/checkout', { interval })
      window.location.href = start.init_point
    } catch (caught) {
      setFailure(caught instanceof ApiError ? caught.detail : 'No se pudo abrir el pago.')
      setBusy(undefined)
    }
  }

  // Mientras no se sepa, no se ofrece nada. Un botón de pago que todavía no sabe el precio es
  // peor que esperar medio segundo.
  if (offer === undefined) {
    return <p className="totals-note">{error ?? 'Cargando los precios…'}</p>
  }

  if (!offer.available) {
    return (
      <p className="totals-note">
        El pago no está disponible en este servidor todavía. Nada de lo que ya emitiste queda
        atrás de la suscripción: son comprobantes fiscales que estás obligado a conservar, y se
        siguen viendo y descargando siempre.
        {/* El motivo nombra la variable de entorno que falta. No es texto para el cliente, y
            por eso va en letra chica: el único que puede hacer algo con eso es quien
            administra el servidor, y esconderlo lo dejaría adivinando. */}
        <br />
        <small className="muted">{offer.unavailable_reason}</small>
      </p>
    )
  }

  return (
    <>
      <Notice kind="error">{failure}</Notice>
      <div className="row">
        <button type="button" onClick={() => subscribe(BillingInterval.monthly)} disabled={busy !== undefined}>
          {busy === BillingInterval.monthly ? 'Abriendo…' : `Por mes · ${price(offer.monthly_price)}`}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => subscribe(BillingInterval.yearly)}
          disabled={busy !== undefined}
        >
          {busy === BillingInterval.yearly ? 'Abriendo…' : `Por año · ${price(offer.yearly_price)}`}
        </button>
      </div>
      {/* Los dos meses bonificados se dicen con todas las letras: es la única razón por la que
          alguien elegiría el anual, y esconderla en la resta de dos números es perderla. */}
      <p className="totals-note">
        El plan anual sale como diez meses: dos vienen bonificados. Se paga con tarjeta o con
        dinero en cuenta a través de Mercado Pago, y se puede dar de baja cuando quieras — el
        período que ya pagaste se termina de usar.
      </p>
    </>
  )
}

/**
 * Un importe que llegó como string, listo para mostrar.
 *
 * Los precios viajan como texto porque del otro lado son `Decimal` — la regla de siempre en
 * esta API. El `Number` de acá no la rompe: es para pintar, no para operar, y lo único que se
 * hace con el resultado es escribirlo en un botón.
 */
function price(amount: string): string {
  return money.format(Number(amount))
}

/** "3 de 5" para el Free, "3" para el Pro: la ausencia de límite se lee en la ausencia. */
function usage(used: number, limit: number | null): string {
  return limit === null ? String(used) : `${used} de ${limit}`
}

/** La fecha del período, o un texto que la reemplaza. El `null` solo lo tiene la cuenta rota. */
function periodEnd(plan: Subscription): string {
  return plan.current_period_end !== null
    ? formatTimestamp(plan.current_period_end)
    : 'fin del período'
}

/**
 * El plan de la cuenta: en qué estado está, cuánto del cupo lleva usado y cómo darse de baja.
 *
 * **Existe para que chocar un límite deje de ser un 402 crudo.** Los dos gates del backend
 * contestan con un texto que dice "pasate a Pro", y hasta esta pantalla ese texto era una
 * pared: no había ningún lugar donde ver qué plan se tiene, cuánto queda ni qué cambia al
 * pasarse. Es la contraparte de `GET /subscription`, que devuelve los permisos ya resueltos
 * justamente para que la pantalla no tenga que deducir nada.
 *
 * **Ruta propia y no una sección más de Ajustes**, aunque hoy se llegue desde ahí. Ajustes es
 * la configuración que uno toca una vez; esto es el estado comercial de la cuenta, lo linkean
 * los dos avisos de límite y la barra de arriba, y es además donde se contrata: los precios y
 * los dos botones del checkout viven en `SubscribeBox`. Una sección adentro de otra pantalla no
 * se puede linkear desde un cartel de error sin mandar al usuario a buscarla.
 *
 * **No pide los datos: los lee del contexto.** Es la misma respuesta que ya usan la barra, los
 * micrófonos y el alta de identidad fiscal — ver `SubscriptionProvider`.
 */
export function PlanPage() {
  const { plan, error, reload } = useSubscription()

  // El regreso del checkout de Mercado Pago (`back_url`). **No es la prueba de que se pagó**:
  // quien activa la cuenta es el webhook, que llega por atrás y puede tardar unos segundos, y
  // creerle a una query string sería dejar que cualquiera se haga Pro escribiéndola a mano. Lo
  // único que hace es volver a preguntar y explicar la espera.
  const [params] = useSearchParams()
  const justPaid = params.get('pago') === 'listo'

  useEffect(() => {
    if (justPaid) reload()
    // `reload` es estable (`useCallback` en el provider), así que esto corre una sola vez.
  }, [justPaid, reload])

  // Dar de baja se hace en dos toques, igual que eliminar una tarjeta en la grilla: primero se
  // pide, y recién ahí aparece el botón que lo hace con su nombre escrito. No es un
  // `window.confirm` por lo mismo que la emisión no lo es —ver `EmitPage`—: hay que explicar
  // qué pasa con el período ya pagado, y eso no entra en un diálogo del sistema.
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [cancelError, setCancelError] = useState<string>()

  async function cancel() {
    if (busy) return
    setBusy(true)
    setCancelError(undefined)
    try {
      await api.post<Subscription>('/subscription/cancel')
      setConfirming(false)
      // Se recarga el contexto y no se pisa su estado con lo que contestó el POST: el plan lo
      // leen seis lugares de la app, y dejar que esta pantalla escriba ahí directamente sería
      // el único lugar donde ese dato se puede tocar desde afuera del provider.
      reload()
    } catch (caught) {
      setCancelError(caught instanceof ApiError ? caught.detail : 'No se pudo dar de baja.')
    } finally {
      setBusy(false)
    }
  }

  // La baja solo se ofrece donde hay una renovación que frenar. En prueba no se cobra nada, y
  // el Free ya no tiene de qué darse de baja: en esos dos casos el botón contestaría "listo"
  // sin haber cambiado nada de lo que el usuario vino a cambiar. El endpoint igual los acepta
  // —es idempotente y no rompe nada— porque lo que no puede pasar es que la API tenga una
  // regla que solo esta pantalla conoce.
  const cancelable =
    plan !== undefined &&
    (plan.status === SubscriptionStatus.active || plan.status === SubscriptionStatus.past_due)

  // A quién se le ofrece contratar. **No es solo el Free**, que es lo que esta pantalla hacía
  // hasta ahora y dejaba sin ninguna forma de pagar a las dos únicas personas que estaban
  // pensando en hacerlo: el que está en la prueba —que es Pro, `is_pro` en `true`, y quiere no
  // quedarse sin nada cuando se termine— y el que se dio de baja y quiere volver.
  //
  // Los dos que no la ven son el `ACTIVE`, porque un segundo `preapproval` son dos débitos
  // automáticos por el mismo servicio y el backend lo rechaza con un 409, y el `PAST_DUE`, que
  // ya tiene su propia caja más arriba: ahí contratar es reemplazar la tarjeta que viene
  // fallando, y el texto tiene que decir eso y no "empezá con Pro".
  const offerable =
    plan !== undefined &&
    plan.status !== SubscriptionStatus.active &&
    plan.status !== SubscriptionStatus.past_due

  return (
    <div className="page">
      <h1>Tu plan</h1>

      <Notice kind="error">{error}</Notice>
      {plan === undefined && error === undefined && <p className="muted">Cargando…</p>}

      {justPaid && (
        <Notice kind={plan?.status === SubscriptionStatus.active ? 'ok' : 'warn'}>
          {plan?.status === SubscriptionStatus.active ? (
            'Listo: la suscripción quedó activa.'
          ) : (
            <>
              Volviste del pago. La confirmación la manda Mercado Pago y puede tardar unos
              segundos.{' '}
              <button type="button" className="link" onClick={reload}>
                Actualizar
              </button>
            </>
          )}
        </Notice>
      )}

      {plan !== undefined && (
        <>
          <div className="card">
            <dl className="summary">
              <div>
                <dt>Plan</dt>
                <dd>
                  <span className={`badge ${plan.is_pro ? 'ok' : 'pending'}`}>
                    {plan.is_pro ? 'Pro' : 'Free'}
                  </span>
                </dd>
              </div>
              {plan.status !== null && (
                <div>
                  <dt>Suscripción</dt>
                  <dd>{STATUS_LABELS[plan.status]}</dd>
                </div>
              )}
              {plan.current_period_end !== null && (
                <div>
                  <dt>{periodLabel(plan)}</dt>
                  <dd>{formatTimestamp(plan.current_period_end)}</dd>
                </div>
              )}
              <div>
                <dt>Comprobantes este mes</dt>
                <dd>{usage(plan.invoices_used, plan.invoices_limit)}</dd>
              </div>
              <div>
                <dt>Identidades fiscales</dt>
                <dd>{usage(plan.fiscal_identities_used, plan.fiscal_identities_limit)}</dd>
              </div>
            </dl>

            {/* El contador se reinicia por mes calendario y no a los treinta días del último
                comprobante: es la pregunta que sigue a "usaste 5 de 5". */}
            {plan.invoices_limit !== null && (
              <p className="totals-note">
                El contador de comprobantes se reinicia el 1° de cada mes.
              </p>
            )}
          </div>

          {plan.status === SubscriptionStatus.past_due && (
            <>
              <Notice kind="warn">
                El último cobro no entró. Seguís con Pro unos días más mientras se reintenta; si
                no se acredita, la cuenta pasa a Free. Lo que ya emitiste no se toca.
              </Notice>
              {/* Al que le falló el cobro se le ofrece contratar de nuevo, y a ningún otro Pro.
                  Es el caso en que la tarjeta se venció o se reemplazó: Mercado Pago reintenta
                  con la misma y va a fallar siempre. Contratar acá da de baja la autorización
                  anterior antes de crear la nueva —lo hace el backend— porque dos débitos
                  automáticos vivos serían dos cobros por el mismo servicio. */}
              <div className="card stack">
                <h2 className="plan-heading">Cambiar el medio de pago</h2>
                <p>
                  Si cambiaste de tarjeta, volvé a contratar con la nueva. Se da de baja la
                  anterior en el mismo momento, así que no se cobra dos veces.
                </p>
                <SubscribeBox />
              </div>
            </>
          )}

          {plan.status === SubscriptionStatus.canceled && plan.is_pro && (
            <Notice kind="warn">
              Ya diste de baja la suscripción, así que no se renueva. Tenés Pro hasta el{' '}
              {periodEnd(plan)}.
            </Notice>
          )}

          {offerable && (
            <div className="card stack">
              {plan.status === SubscriptionStatus.trialing ? (
                <>
                  <h2 className="plan-heading">Seguí con Pro cuando termine la prueba</h2>
                  {/* Contratar durante la prueba no la corta: el backend le manda a Mercado
                      Pago los días que faltan como `free_trial`, así que la autorización queda
                      hecha hoy y el primer cobro cae el día que la prueba se termina. Decirlo
                      acá es lo que hace que apretar el botón no parezca perder los días que
                      quedan — ver `_free_trial_days` en `services/mercadopago.py`. */}
                  <p>
                    Estás probando Pro hasta el {periodEnd(plan)}. Si contratás ahora no perdés
                    los días que te quedan: el primer cobro entra recién cuando la prueba se
                    termina, y de ahí en más no se corta nada.
                  </p>
                </>
              ) : plan.is_pro ? (
                <>
                  <h2 className="plan-heading">Volver a contratar</h2>
                  {/* El que se dio de baja y todavía tiene período pagado sí puede volver, pero
                      pagando desde ahora: el `free_trial` solo respeta la prueba, no el período
                      ya cobrado. Se avisa en vez de esconder el botón — el que quiere volver
                      tiene que poder, y el que no tiene apuro merece saber que conviene
                      esperar. */}
                  <p>
                    Contratar de nuevo reanuda la renovación. El cobro entra en el momento y no
                    espera al {periodEnd(plan)}, así que si no tenés apuro conviene hacerlo
                    cuando ese período se termine.
                  </p>
                </>
              ) : (
                <>
                  <h2 className="plan-heading">Qué agrega Pro</h2>
                  <ul className="plan-features">
                    <li>
                      <strong>Comprobantes sin límite.</strong> Con Free son{' '}
                      {plan.invoices_limit} por mes.
                    </li>
                    <li>
                      <strong>Varias identidades fiscales.</strong> Con Free es{' '}
                      {plan.fiscal_identities_limit}, así que se factura desde un solo CUIT.
                    </li>
                    <li>
                      <strong>Dictado por voz.</strong> Pedir la factura hablando, y que la app
                      conteste en voz alta.
                    </li>
                  </ul>
                </>
              )}
              <SubscribeBox />
            </div>
          )}

          {cancelable && (
            <div className="card stack">
              <Notice kind="error">{cancelError}</Notice>
              {confirming ? (
                <>
                  <p className="plan-confirm">
                    No se renueva más. Seguís con Pro hasta el{' '}
                    <strong>{periodEnd(plan)}</strong> — el período que ya pagaste se termina de
                    usar. Después la cuenta pasa a Free con sus límites, y no se borra nada: las
                    identidades fiscales, los modelos y las facturas quedan donde están.
                  </p>
                  <div className="row">
                    <button type="button" className="danger" onClick={cancel} disabled={busy}>
                      {busy ? 'Dando de baja…' : 'Confirmar la baja'}
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setConfirming(false)}
                      disabled={busy}
                    >
                      Volver
                    </button>
                  </div>
                </>
              ) : (
                <button type="button" className="secondary" onClick={() => setConfirming(true)}>
                  Dar de baja
                </button>
              )}
            </div>
          )}

          <p className="totals-note">
            <Link to="/ajustes">← Ajustes</Link>
          </p>
        </>
      )}
    </div>
  )
}
