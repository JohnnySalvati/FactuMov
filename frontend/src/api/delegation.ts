/**
 * El rechequeo de la delegación desde el cliente: cuándo vale la pena preguntar y con qué
 * frecuencia como mucho.
 *
 * Estaba adentro de `FiscalIdentityPage`, donde la única pantalla que preguntaba era la de
 * detalle. Sale acá porque ahora también pregunta la grilla, y las dos tienen que compartir el
 * criterio: si cada una decide por su cuenta cuándo repreguntar, el presupuesto de ARCA lo
 * gasta la que se descuide.
 *
 * **La cuota que se está cuidando es la del certificado, no la del usuario.** El certificado es
 * uno solo para toda la app, así que un usuario dándole F5 a la grilla se la gasta a todos. De
 * ahí que acá haya dos frenos y no uno: `needsChecking` decide si el dato ya sirve, y
 * `checkedRecently` decide si ya preguntamos hace poco.
 */

import { api } from './client'
import type { DelegationStatus } from './types'

/** Cada cuánto vale la pena volver a preguntarle a ARCA por una delegación ya verificada.
 *
 *  No es un vencimiento: es cada cuánto se repregunta sola. La delegación se revoca del lado de
 *  ARCA sin avisarnos, y sin esto la app se enteraría recién con un rechazo al emitir — o sea
 *  en el peor momento posible. Una semana es holgado porque revocar no es frecuente, y el costo
 *  es una llamada por identidad por semana. */
export const STALE_AFTER_MS = 7 * 24 * 60 * 60 * 1000

/**
 * Piso entre dos consultas sobre la **misma** identidad, dentro de esta sesión de la SPA.
 *
 * `needsChecking` sola no alcanza desde que pregunta la grilla: una identidad sin verificar la
 * necesita *siempre*, así que entrar y salir de la lista diez veces son diez llamadas a ARCA
 * por cada CUIT sin delegar — y el limitador del backend es de 30 por hora, o sea que el propio
 * usuario se dejaría afuera. Cinco minutos es más corto que cualquier trámite en ARCA: nadie va
 * a autorizarnos y volver más rápido que eso.
 */
const MIN_INTERVAL_MS = 5 * 60 * 1000

/**
 * Cuándo se preguntó por última vez por cada identidad.
 *
 * A nivel de módulo y no en un `useRef`, que es lo que la hace útil: un ref se pierde al
 * desmontar, y desmontar es exactamente lo que pasa al navegar de la grilla al detalle y
 * volver. Vive lo que vive la pestaña; recargar la página la limpia, y eso está bien — una
 * recarga es alguien pidiendo datos frescos a propósito.
 */
const lastCheckedAt = new Map<string, number>()

/** ¿El dato que tenemos guardado todavía sirve, o hay que repreguntar? */
export function needsChecking(verifiedAt: string | null): boolean {
  return verifiedAt === null || Date.now() - new Date(verifiedAt).getTime() > STALE_AFTER_MS
}

/** ¿Ya le preguntamos a ARCA por esta identidad hace muy poco? */
export function checkedRecently(id: string): boolean {
  const at = lastCheckedAt.get(id)
  return at !== undefined && Date.now() - at < MIN_INTERVAL_MS
}

/**
 * Anota que acabamos de salir a ARCA por esta identidad.
 *
 * Es público porque `claim-delegation` también pregunta —verifica antes de anotar el aviso, ver
 * el router— y sale por el mismo certificado. Contarlo solo cuando el que pregunta es
 * `verify-delegation` haría que apretar «Ya delegué» no cuente para nada.
 */
export function markChecked(id: string): void {
  lastCheckedAt.set(id, Date.now())
}

/**
 * Le pregunta a ARCA por una identidad y devuelve lo que contestó.
 *
 * **Anota el intento antes de esperar la respuesta, no después.** Un 502 o un 429 también
 * cuentan: reintentar cada vez que se monta una pantalla contra un ARCA que no contesta es
 * justo lo que no hay que hacer, y con el 429 sería además pedirle al limitador que nos rechace
 * más rápido.
 */
export async function checkDelegation(id: string): Promise<DelegationStatus> {
  markChecked(id)
  return api.post<DelegationStatus>(`/fiscal-identities/${id}/verify-delegation`)
}
