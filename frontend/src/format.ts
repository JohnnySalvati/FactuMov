/**
 * Cómo se muestran los números y las fechas. Nada más que eso.
 *
 * `money` vivía en `forms/templateForm.ts` mientras el único que mostraba importes era el
 * editor. Con las facturas emitidas pasó a usarlo media app, y un formateador de moneda
 * importado desde un módulo que se llama "el formulario del modelo" es una pista falsa para
 * el que lo lee después.
 *
 * Archivo propio y no dentro de una pantalla, además, por Fast Refresh: solo recarga en
 * caliente un módulo que exporta componentes y nada más — el mismo motivo por el que el
 * contexto de sesión vive en tres archivos y por el que `templateForm.ts` está separado del
 * editor.
 */

export const money = new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS' })

/**
 * `2026-08-27` → `27/08/2026`.
 *
 * Se parte el string a mano en vez de pasarlo por `new Date`. No es purismo: el constructor
 * lee la forma `YYYY-MM-DD` como **UTC**, y al mostrarla en hora local argentina (UTC-3) la
 * corre un día para atrás. La factura emitida el 1° se mostraría como del 31 del mes anterior
 * — un error de un día en un comprobante fiscal, causado por un formateo.
 */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-')
  return `${day}/${month}/${year}`
}

/**
 * Una fecha local → el `YYYY-MM-DD` que esperan la API y el `<input type="date">`.
 *
 * Se arma a mano y no con `toISOString()`, que devuelve **UTC**: en Argentina (UTC-3), de las
 * 21:00 en adelante allá ya es el día siguiente, así que una factura emitida un jueves a la
 * noche saldría propuesta con fecha del viernes. Es el mismo error de un día que `formatDate`
 * evita en la dirección contraria, y acá pega sobre la fecha de un comprobante fiscal.
 */
export function isoDate(value: Date): string {
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
}

/**
 * Un instante ISO con hora (`2026-09-30T02:15:00Z`) → `29/09/2026`, en hora local.
 *
 * Es el complemento de `formatDate`, y la diferencia entre las dos no es de estilo: aquella
 * recibe una **fecha sin hora** —la del comprobante, que es un día y no un momento— y por eso
 * la parte a mano sin dejar que ninguna zona horaria la mueva. Esto recibe un **momento**
 * —cuándo se verificó algo, hasta cuándo llega el período pagado— que ocurrió en un instante
 * y que hay que mostrar en la hora del que mira. Cortar el string en los diez primeros
 * caracteres, que es lo que se hacía antes en los ajustes, lo muestra en UTC: de las 21 en
 * adelante en Argentina eso ya es el día siguiente, y el cartel adelanta un día.
 */
export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleDateString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}
