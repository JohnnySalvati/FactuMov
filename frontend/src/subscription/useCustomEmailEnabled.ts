import { useSubscription } from './useSubscription'

/**
 * Si el modelo puede tener su propio texto de mail, que es del plan Pro.
 *
 * **`true` mientras no se sabe**, igual que `useVoiceEnabled` y por el mismo motivo: empezar en
 * `false` haría que el Pro viera el aviso de "esto es Pro" sobre algo que paga, en cada carga
 * de la app y para siempre si el `GET /subscription` falla. Al revés, el Free ve los dos campos
 * habilitados medio segundo de más y, si llegara a escribir algo en ese lapso, el backend
 * contesta 402 al guardar con el texto que explica por qué — o sea que lo peor que pasa es un
 * error claro, que es mucho mejor que esconderle una función a quien la compró.
 *
 * A diferencia de la voz, acá el backend **sí** puede hacer cumplir el límite, y lo hace dos
 * veces: no deja guardar el texto y no lo usa al enviar. Esto solo decide qué ofrece la
 * pantalla.
 */
export function useCustomEmailEnabled(): boolean {
  const { plan } = useSubscription()
  return plan?.custom_email_enabled ?? true
}
