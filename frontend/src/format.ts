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
