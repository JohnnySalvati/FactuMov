import { Link } from 'react-router'

import { SubscriptionStatus } from '../api/types'
import { useSubscription } from '../subscription/useSubscription'

/**
 * A cuántos días del final se avisa que la prueba se termina.
 *
 * **Una semana, y no los treinta días enteros.** El aviso vive arriba de todas las pantallas,
 * así que mostrarlo desde el día uno lo convierte en una publicidad permanente del plan Pro y
 * en un renglón que el usuario deja de ver a la semana. Siete días es lo que hace que aparezca
 * cuando todavía se puede decidir sin apuro y que llegue a verlo el que abre la app una vez por
 * semana, que es la frecuencia de mucha gente que factura.
 */
const TRIAL_NOTICE_DAYS = 7

/**
 * Cuántos días le quedan a la prueba, redondeando para arriba.
 *
 * **Para arriba y no para abajo** porque el usuario cuenta días, no fracciones: a treinta horas
 * del final quedan dos días —hoy y mañana—, y un `floor` diría "1" el día entero de hoy y "0"
 * mañana. El cero no se muestra nunca: ver el llamador.
 */
function trialDaysLeft(end: string): number {
  return Math.ceil((new Date(end).getTime() - Date.now()) / 86_400_000)
}

/**
 * La franja de la barra: la prueba que se termina, o el cupo del Free que se agota.
 *
 * **Aparece antes de que el usuario choque el límite, y por eso vive en el layout.** El 402
 * llega recién al apretar "Emitir", que es el peor momento posible para enterarse: el
 * comprobante ya está armado y muchas veces el cliente está esperando. Un cartel en la barra
 * lo dice mientras todavía se puede decidir otra cosa.
 *
 * **No se muestra nada cuando no hay nada que decidir.** Es una franja arriba de todas las
 * pantallas de la app, así que el default tiene que ser invisible: un contador permanente
 * diciendo "1 de 5" sería una barra de publicidad del plan Pro en la pantalla que se abre cien
 * veces por semana. Son dos cortes y los dos son tardíos a propósito: el último comprobante
 * —que es cuando la información cambia lo que el usuario hace hoy— y la última semana de
 * prueba.
 *
 * **La prueba necesitaba su propio aviso** (2026-09-01) porque el del cupo no la cubre: durante
 * el trial la cuenta es Pro y `invoices_limit` viene en `null`, así que la franja no aparecía ni
 * una vez en los treinta días y el único camino a la pantalla del plan era el engranaje de
 * Ajustes. El día que la prueba se terminaba, el usuario se enteraba emitiendo.
 *
 * Tampoco aparece mientras no se sabe el plan, ni si la consulta falló: ver `error` en
 * `subscription/context.ts`. Avisar de un cupo que no se conoce es peor que no avisar.
 */
export function PlanBanner() {
  const { plan } = useSubscription()
  if (plan === undefined) return null

  // El `> 0` no es una guarda de más: una fila que sigue en `TRIALING` con la fecha pasada es
  // exactamente lo que se ve entre que la prueba vence y el usuario contrata —nadie reescribe
  // esa fila al vencer— y sin él la franja diría "último día" para siempre. Cuando eso pasa la
  // cuenta ya es Free, así que el chequeo de abajo la toma y muestra el cupo, que es lo que
  // corresponde.
  const daysLeft =
    plan.status === SubscriptionStatus.trialing && plan.current_period_end !== null
      ? trialDaysLeft(plan.current_period_end)
      : 0

  if (daysLeft > 0 && daysLeft <= TRIAL_NOTICE_DAYS) {
    return (
      <div className="plan-banner warn" role="status">
        <span>
          {daysLeft === 1
            ? 'Hoy es el último día de la prueba gratis.'
            : `Te quedan ${daysLeft} días de prueba gratis.`}
        </span>{' '}
        <Link to="/plan">Seguir con Pro</Link>
      </div>
    )
  }

  // El Pro tiene `invoices_limit` en `null`, que es "sin límite" y no cero: el orden de estos
  // dos chequeos es lo que evita que un `null` mal leído le muestre el cartel a quien paga.
  if (plan.invoices_limit === null) return null

  const left = plan.invoices_limit - plan.invoices_used
  if (left > 1) return null

  return (
    <div className={`plan-banner ${plan.can_emit ? 'warn' : 'error'}`} role="status">
      <span>
        {plan.can_emit
          ? `Te queda ${left} comprobante este mes con el plan Free.`
          : `Usaste los ${plan.invoices_limit} comprobantes del mes. El contador se reinicia el 1°.`}
      </span>{' '}
      <Link to="/plan">Ver tu plan</Link>
    </div>
  )
}
