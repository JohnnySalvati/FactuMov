import { useState } from 'react'
import { Link } from 'react-router'

import { ApiError, api } from '../api/client'
import { SubscriptionStatus, type Subscription } from '../api/types'
import { Notice } from '../components/Notice'
import { formatTimestamp } from '../format'
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
 * los dos avisos de límite y la barra de arriba, y en cuanto exista el checkout de Mercado
 * Pago va a crecer con la elección del plan y el medio de pago. Una sección adentro de otra
 * pantalla no se puede linkear desde un cartel de error sin mandar al usuario a buscarla.
 *
 * **No pide los datos: los lee del contexto.** Es la misma respuesta que ya usan la barra, los
 * micrófonos y el alta de identidad fiscal — ver `SubscriptionProvider`.
 */
export function PlanPage() {
  const { plan, error, reload } = useSubscription()

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

  return (
    <div className="page">
      <h1>Tu plan</h1>

      <Notice kind="error">{error}</Notice>
      {plan === undefined && error === undefined && <p className="muted">Cargando…</p>}

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
            <Notice kind="warn">
              El último cobro no entró. Seguís con Pro unos días más mientras se reintenta; si no
              se acredita, la cuenta pasa a Free. Lo que ya emitiste no se toca.
            </Notice>
          )}

          {plan.status === SubscriptionStatus.canceled && plan.is_pro && (
            <Notice kind="warn">
              Ya diste de baja la suscripción, así que no se renueva. Tenés Pro hasta el{' '}
              {periodEnd(plan)}.
            </Notice>
          )}

          {!plan.is_pro && (
            <div className="card stack">
              <h2 className="plan-heading">Qué agrega Pro</h2>
              <ul className="plan-features">
                <li>
                  <strong>Comprobantes sin límite.</strong> Con Free son {plan.invoices_limit} por
                  mes.
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
              {/* Sin botón de pago todavía: el checkout de Mercado Pago es su propia unidad, y
                  un botón que no cobra es peor que ninguno — manda a un callejón sin salida
                  justo al que quería pagar. Cuando exista, reemplaza a este párrafo. */}
              <p className="totals-note">
                El pago todavía no está abierto. Cuando lo esté se contrata desde acá. Nada de lo
                que ya emitiste queda atrás de la suscripción: son comprobantes fiscales que
                estás obligado a conservar, y se siguen viendo y descargando siempre.
              </p>
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
