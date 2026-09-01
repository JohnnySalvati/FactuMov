import { Link } from 'react-router'

import { useSubscription } from '../subscription/useSubscription'

/**
 * El aviso de cupo: una franja abajo de la barra cuando al Free le queda poco o nada.
 *
 * **Aparece antes de que el usuario choque el límite, y por eso vive en el layout.** El 402
 * llega recién al apretar "Emitir", que es el peor momento posible para enterarse: el
 * comprobante ya está armado y muchas veces el cliente está esperando. Un cartel en la barra
 * lo dice mientras todavía se puede decidir otra cosa.
 *
 * **No se muestra nada cuando el cupo alcanza.** Es una franja arriba de todas las pantallas
 * de la app, así que el default tiene que ser invisible: un contador permanente diciendo "1 de
 * 5" sería una barra de publicidad del plan Pro en la pantalla que se abre cien veces por
 * semana. El corte es el último comprobante — que es cuando la información cambia lo que el
 * usuario hace hoy — y el cupo agotado.
 *
 * Tampoco aparece mientras no se sabe el plan, ni si la consulta falló: ver `error` en
 * `subscription/context.ts`. Avisar de un cupo que no se conoce es peor que no avisar.
 */
export function PlanBanner() {
  const { plan } = useSubscription()

  // El Pro tiene `invoices_limit` en `null`, que es "sin límite" y no cero: el orden de estos
  // dos chequeos es lo que evita que un `null` mal leído le muestre el cartel a quien paga.
  if (plan === undefined || plan.invoices_limit === null) return null

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
