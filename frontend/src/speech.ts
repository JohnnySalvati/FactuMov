/**
 * De lo que se escuchó a una fecha. Nada más que eso.
 *
 * Es una función pura y sin nada de React a propósito: el reconocimiento de voz solo se puede
 * probar hablándole a un celular, y si la interpretación viviera adentro del componente
 * también habría que hablarle al celular para probar que "treinta y uno de agosto" cae en el
 * día correcto. Separadas, lo único que hay que probar a mano es que el micrófono abra.
 *
 * **La gramática es cerrada y chica**, no un LLM: el vocabulario de una fecha entra en un
 * archivo. Un modelo entendería que le hablen suelto, pero cuesta por request, agrega un
 * segundo de latencia y puede devolver una fecha que nadie dijo — sobre un campo que termina
 * impreso en un comprobante fiscal. Cuando la gramática no alcance, el que llama muestra lo
 * que se escuchó y el usuario corrige a mano; nunca se adivina.
 */

import { isoDate } from './format'

/**
 * Los números hablados, a dígitos, antes de buscarles forma de fecha.
 *
 * Existe porque los motores no coinciden: Chrome en Android devuelve "15 de agosto" y Safari
 * en iOS suele devolver "quince de agosto". Normalizando primero, el resto del archivo ve
 * siempre dígitos y hay una sola forma de fecha que reconocer en vez de dos.
 *
 * **El orden importa**: las frases largas van antes que sus partes, o "treinta y uno" se
 * convierte en "30 y 1".
 */
const NUMERALS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\btreinta y uno\b/g, '31'],
  [/\btreinta\b/g, '30'],
  [/\bveintinueve\b/g, '29'],
  [/\bveintiocho\b/g, '28'],
  [/\bveintisiete\b/g, '27'],
  [/\bveintiseis\b/g, '26'],
  [/\bveinticinco\b/g, '25'],
  [/\bveinticuatro\b/g, '24'],
  [/\bveintitres\b/g, '23'],
  [/\bveintidos\b/g, '22'],
  [/\bveintiun[oa]?\b/g, '21'],
  [/\bveinte\b/g, '20'],
  [/\bdiecinueve\b/g, '19'],
  [/\bdieciocho\b/g, '18'],
  [/\bdiecisiete\b/g, '17'],
  [/\bdieciseis\b/g, '16'],
  [/\bquince\b/g, '15'],
  [/\bcatorce\b/g, '14'],
  [/\btrece\b/g, '13'],
  [/\bdoce\b/g, '12'],
  [/\bonce\b/g, '11'],
  [/\bdiez\b/g, '10'],
  [/\bnueve\b/g, '9'],
  [/\bocho\b/g, '8'],
  [/\bsiete\b/g, '7'],
  [/\bseis\b/g, '6'],
  [/\bcinco\b/g, '5'],
  [/\bcuatro\b/g, '4'],
  [/\btres\b/g, '3'],
  [/\bdos\b/g, '2'],
  [/\b(?:primero|primer|uno|una|un)\b/g, '1'],
]

/** "setiembre" no es un error de dictado: es la grafía habitual en Argentina. */
const MONTHS: ReadonlyArray<readonly [string, number]> = [
  ['enero', 1],
  ['febrero', 2],
  ['marzo', 3],
  ['abril', 4],
  ['mayo', 5],
  ['junio', 6],
  ['julio', 7],
  ['agosto', 8],
  ['septiembre', 9],
  ['setiembre', 9],
  ['octubre', 10],
  ['noviembre', 11],
  ['diciembre', 12],
]

const MONTH_ALTERNATION = MONTHS.map(([name]) => name).join('|')

/** `15 de agosto de 2026`, `15 agosto`, `1 de septiembre del 26`. */
const DAY_MONTH = new RegExp(
  `\\b(\\d{1,2})\\s+(?:de\\s+|del\\s+)?(${MONTH_ALTERNATION})\\b(?:\\s+(?:de\\s+|del\\s+)?(\\d{2,4})\\b)?`,
)

/** `15/8`, `15/8/2026`, `15-8-26`. Día primero, que es como se escribe acá. */
const NUMERIC = /\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b/

/** Un día suelto: "el quince", "el 31". */
const BARE_DAY = /\b(\d{1,2})\b/

/** Las fechas que se dicen sin nombrar nada: "hoy", "fin de mes". */
const RELATIVE = /\bhoy\b|\bayer\b|\banteayer\b|\bmanana\b|\bfin (?:de|del) mes\b|\bultimo dia\b/

/**
 * ¿El texto dice **de qué mes** habla?
 *
 * Lo pregunta `commands.ts` para el caso "desde el 1 hasta el 31 de agosto", donde una de las
 * dos puntas del período nombra el mes y la otra no. La que no lo nombra tiene que tomarlo de
 * la que sí — resuelta por su cuenta caería en el mes más cercano a hoy, que el 28 de agosto
 * es septiembre, y el período saldría al revés.
 *
 * "Hoy" y "fin de mes" cuentan como que lo dicen: no nombran un mes pero tampoco dejan nada
 * librado al contexto, ya son una fecha entera.
 */
export function mentionsMonth(heard: string): boolean {
  const text = normalizeSpoken(heard)
  return (
    new RegExp(`\\b(?:${MONTH_ALTERNATION})\\b`).test(text) ||
    NUMERIC.test(text) ||
    RELATIVE.test(text)
  )
}

const MS_PER_DAY = 86_400_000

/**
 * Deja el texto en minúsculas, sin acentos y con los números en dígitos.
 *
 * Se exporta porque `commands.ts` necesita **la misma** normalización antes de partir la
 * frase en cláusulas: si buscara "desde" sobre el texto crudo, no lo encontraría en un motor
 * que devuelve "Desde" con mayúscula, y el nombre del modelo que quedara de un lado se
 * compararía contra los nombres guardados con otro criterio que el de acá. Es idempotente
 * —minúsculas, acentos y numerales ya convertidos no cambian— así que volver a pasarla sobre
 * un pedazo ya normalizado, como hace `parseSpokenDate` con cada cláusula, no cuesta nada.
 *
 * Los acentos se sacan con `NFD` + borrar los diacríticos, y no con una tabla de reemplazos:
 * lo que llega del reconocedor puede venir acentuado o no según el motor, y comparar contra
 * "diciembre" tiene que funcionar igual en los dos casos.
 */
export function normalizeSpoken(heard: string): string {
  let text = heard
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    // Todo lo que no es letra, dígito, barra o guion se vuelve un espacio: así el punto final
    // que agrega el dictado no queda pegado al año.
    .replace(/[^a-z0-9/-]+/g, ' ')
    .trim()
  for (const [pattern, digits] of NUMERALS) text = text.replace(pattern, digits)
  return text
}

/**
 * Arma la fecha y **rechaza las que no existen**.
 *
 * `new Date(2026, 1, 31)` no falla: devuelve el 3 de marzo en silencio. Sin esta
 * verificación, dictar "treinta y uno de febrero" cargaría una fecha plausible y equivocada
 * en un comprobante, que es peor que no entender nada.
 */
function build(day: number, month: number, year: number): string | undefined {
  const date = new Date(year, month - 1, day)
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return undefined
  }
  return isoDate(date)
}

/**
 * El año que no se dijo.
 *
 * Casi nunca se dice, así que hay que elegirlo: se toma el que deja la fecha más cerca de hoy.
 * La regla se nota una sola vez por año, y es justo cuando importa — "31 de diciembre" dictado
 * el 2 de enero es del año pasado, y "2 de enero" dictado el 30 de diciembre es del que viene.
 * Con el año en curso a secas, las dos caen a doce meses de distancia.
 */
function nearestYear(day: number, month: number, today: Date): number {
  const distance = (year: number) =>
    Math.abs(new Date(year, month - 1, day).getTime() - today.getTime())
  const candidates = [today.getFullYear() - 1, today.getFullYear(), today.getFullYear() + 1]
  return candidates.reduce((best, year) => (distance(year) < distance(best) ? year : best))
}

/** Mismo criterio que `nearestYear` pero sobre el mes, para cuando solo se dijo el día. */
function nearestMonth(day: number, today: Date): { month: number; year: number } {
  const candidates = [-1, 0, 1].map((offset) => {
    const date = new Date(today.getFullYear(), today.getMonth() + offset, day)
    return { month: date.getMonth() + 1, year: date.getFullYear(), time: date.getTime() }
  })
  const best = candidates.reduce((a, b) =>
    Math.abs(b.time - today.getTime()) < Math.abs(a.time - today.getTime()) ? b : a,
  )
  return { month: best.month, year: best.year }
}

/** `26` → 2026. Un año de dos dígitos en una factura no puede ser 1926. */
function fullYear(spoken: string): number {
  const year = Number(spoken)
  return year < 100 ? 2000 + year : year
}

/**
 * Lo que se escuchó → `YYYY-MM-DD`, o `undefined` si no se entendió una fecha.
 *
 * `undefined` es una respuesta legítima y el que llama tiene que mostrarla: el peor final
 * posible es que el botón no haga nada visible y el usuario no sepa si el micrófono no
 * escuchó, si entendió otra cosa o si la app se colgó.
 *
 * `today` se recibe por parámetro en vez de leer el reloj adentro. Es lo que hace que "ayer" y
 * "el 31" se puedan probar sin depender del día en que se corra la prueba.
 */
export function parseSpokenDate(heard: string, today: Date): string | undefined {
  const text = normalizeSpoken(heard)
  if (text === '') return undefined

  // Se trunca a medianoche local antes de hacer cuentas: el `preview` y el `<input type="date">`
  // hablan de días, no de instantes, y "ayer" tiene que dar lo mismo dictado a las 9 que a las
  // 23. Local y no UTC por el mismo corrimiento de un día que documenta `isoDate`.
  const midnight = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const shifted = (days: number) => isoDate(new Date(midnight.getTime() + days * MS_PER_DAY))

  if (/\bhoy\b/.test(text)) return shifted(0)
  if (/\banteayer\b|\bantes de ayer\b/.test(text)) return shifted(-2)
  if (/\bayer\b/.test(text)) return shifted(-1)
  // "pasado mañana" pasa por `NUMERALS` sin tocarse, pero el "1" opcional cubre el caso de que
  // un motor devuelva "pasado un mañana".
  if (/\bpasado (?:1 )?manana\b/.test(text)) return shifted(2)
  if (/\bmanana\b/.test(text)) return shifted(1)

  // "fin de mes" y "último día del mes": el día 0 del mes siguiente es el último del actual.
  if (/\bfin (?:de|del) mes\b|\bultimo dia (?:de|del) mes\b/.test(text)) {
    return isoDate(new Date(midnight.getFullYear(), midnight.getMonth() + 1, 0))
  }

  const numeric = NUMERIC.exec(text)
  if (numeric) {
    const [, day, month, year] = numeric
    return build(
      Number(day),
      Number(month),
      year === undefined ? nearestYear(Number(day), Number(month), midnight) : fullYear(year),
    )
  }

  const dayMonth = DAY_MONTH.exec(text)
  if (dayMonth) {
    const [, day, name, year] = dayMonth
    const month = MONTHS.find(([candidate]) => candidate === name)?.[1]
    if (month === undefined) return undefined
    return build(
      Number(day),
      month,
      year === undefined ? nearestYear(Number(day), month, midnight) : fullYear(year),
    )
  }

  const bare = BARE_DAY.exec(text)
  if (bare) {
    const day = Number(bare[1])
    const { month, year } = nearestMonth(day, midnight)
    return build(day, month, year)
  }

  return undefined
}
