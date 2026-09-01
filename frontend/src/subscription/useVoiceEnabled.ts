import { useSubscription } from './useSubscription'

/**
 * Si esta cuenta tiene el dictado por voz, que es del plan Pro.
 *
 * **`true` mientras no se sabe.** Es el mismo criterio que `setVoiceAllowed` en `speak.ts`, y
 * está escrito una vez acá porque lo consultan los tres componentes de voz: el micrófono del
 * comando, el de cada campo de fecha y el interruptor de la respuesta hablada. Empezar en
 * `false` haría que el Pro viera desaparecer sus micrófonos en cada carga de la app hasta que
 * volviera el `GET /subscription` —y para siempre si esa consulta falla—, que es sacarle algo
 * que pagó por un problema de red. Al revés, el Free los ve medio segundo de más: la voz llena
 * el formulario y nada más, y lo irreversible —emitir— lo sigue cortando `can_emit` del lado
 * del backend.
 */
export function useVoiceEnabled(): boolean {
  const { plan } = useSubscription()
  return plan?.voice_enabled ?? true
}
