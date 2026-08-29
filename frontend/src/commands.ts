/**
 * De lo que se escuchó a un comando. Hoy hay uno solo: **emitir un modelo**.
 *
 * Es el paso siguiente del dictado de fechas, y llega ahora porque el paso anterior anda: el
 * micrófono abre y entrega en iPad, en Android y en la computadora. Hasta que eso no estuvo
 * probado, construirle un comando encima era construir sobre algo que podía no existir.
 *
 * **Sigue siendo una gramática cerrada y no un LLM**, por el mismo motivo que las fechas: el
 * vocabulario entra en un archivo, no cuesta por request, no agrega latencia y —sobre todo—
 * no puede devolver un modelo que nadie nombró. Lo que sí cambia respecto de una fecha es que
 * acá hay dos cosas que entender en la misma frase, el modelo y sus fechas, así que el texto
 * se parte en cláusulas por palabras clave y cada pedazo se manda a `parseSpokenDate`.
 *
 * **El comando no emite: deja lista la pantalla de confirmación.** Emitir le pide el CAE a
 * ARCA y no se puede deshacer; la voz llena el formulario y el botón lo sigue apretando el
 * dedo. Es la misma regla que ya tenía el micrófono de las fechas, y es la que hace que
 * entender mal sea una molestia y no una factura equivocada. Lo que el comando ahorra es la
 * parte reversible del camino: encontrar el modelo en la grilla, entrar, tocar "Emitir" y
 * cargar tres fechas en el selector nativo de un celular.
 */

import { isoDate } from './format'
import { mentionsMonth, normalizeSpoken, parseSpokenDate } from './speech'

/** Las fechas que puede llevar una emisión. Todas opcionales: lo que no se dijo no se toca. */
export interface SpokenDates {
  /** La del comprobante. */
  date?: string
  /** El período facturado y el vencimiento del pago, que ARCA exige solo en servicios. */
  from_date?: string
  to_date?: string
  due_date?: string
}

export interface EmitCommand {
  /** El nombre del modelo tal como se escuchó, ya normalizado. Puede ser `''`. */
  name: string
  dates: SpokenDates
  /**
   * Las cláusulas de fecha que se dijeron y **no** se entendieron, por su palabra ("desde").
   *
   * Existe porque el silencio sería la peor respuesta: si "desde el treinta y dos de agosto"
   * se descartara sin decir nada, la pantalla de emisión aparecería con el período del mes en
   * curso puesto por default y nada distinguiría eso de haber entendido bien.
   */
  unclear: string[]
}

/**
 * Con qué empieza un comando.
 *
 * `emit\w*` cubre "emitir", "emití", "emitime" y "emitila"; `factur\w*`, "facturar",
 * "facturame" y "factura". Un verbo suelto al principio y no una frase exacta: el motor
 * devuelve lo que se dijo, y nadie dice dos veces la misma forma.
 */
const VERB = /^(?:emit\w*|emis\w*|factur\w*)\b/

/**
 * El relleno entre el verbo y el nombre. "emitir **el modelo** alquiler" nombra al alquiler.
 *
 * Se saca repetido (`+`) para que "emitime la factura de luz" llegue a "luz". No es riesgoso
 * que se coma un artículo que sea parte del nombre real: `matchTemplate` compara por
 * inclusión y por palabras, no por igualdad.
 */
const FILLER = /^(?:(?:me|la|el|los|las|un|una|de|del|modelo|factura|comprobante)\s+)+/

/**
 * Las palabras que abren una cláusula de fecha, y a qué campo va cada una.
 *
 * **El vocabulario es corto a propósito.** Cada palabra que se agrega acá es una palabra que
 * deja de poder estar en el nombre de un modelo: la cláusula corta la frase, así que un
 * "hasta" de más convertiría a "Cuota hasta diciembre" en el modelo "cuota". Por eso no está
 * "al" —que aparece en "Servicio al cliente"— aunque "del 1 al 31" sea como se habla.
 */
const CLAUSES: ReadonlyArray<{ word: RegExp; field: keyof SpokenDates; label: string }> = [
  { word: /(?:con\s+)?fecha(?:\s+(?:del?\s+)?comprobante)?/, field: 'date', label: 'fecha' },
  { word: /(?:periodo\s+)?desde/, field: 'from_date', label: 'desde' },
  { word: /hasta/, field: 'to_date', label: 'hasta' },
  {
    word: /(?:vence|vencen|vencimiento)(?:\s+del?\s+pago)?/,
    field: 'due_date',
    label: 'vencimiento',
  },
]

/** Las cuatro alternativas en un solo barrido, para poder ordenarlas por dónde aparecieron. */
const ANY_CLAUSE = new RegExp(CLAUSES.map(({ word }) => `\\b(?:${word.source})\\b`).join('|'), 'g')

/** A qué cláusula corresponde un texto que ya matcheó `ANY_CLAUSE`. */
function clauseOf(matched: string) {
  return CLAUSES.find(({ word }) => new RegExp(`^(?:${word.source})$`).test(matched))
}

/**
 * Lo que se escuchó → un comando, o `undefined` si no empieza por un verbo de emisión.
 *
 * `undefined` no es un error: es "esto no era un comando". El que llama lo muestra —"se
 * escuchó «hola» y no es un comando"— en vez de dejar la pantalla quieta, que es el final que
 * no le dice al usuario si el micrófono no escuchó o si la app se colgó.
 *
 * `today` viaja por parámetro hasta `parseSpokenDate` por lo mismo que allá: es lo que permite
 * probar "vence mañana" sin que el resultado dependa del día en que se corra la prueba.
 */
export function parseSpokenCommand(heard: string, today: Date): EmitCommand | undefined {
  const text = normalizeSpoken(heard)
  if (!VERB.test(text)) return undefined

  const rest = text.replace(VERB, '').trim()

  // Dónde arranca y dónde termina cada palabra clave. Se recorre una sola vez y en orden, así
  // que el corte del nombre y el de cada cláusula salen de la misma lista.
  const marks: { start: number; end: number; field: keyof SpokenDates; label: string }[] = []
  ANY_CLAUSE.lastIndex = 0
  for (let found = ANY_CLAUSE.exec(rest); found !== null; found = ANY_CLAUSE.exec(rest)) {
    const clause = clauseOf(found[0])
    if (clause === undefined) continue
    marks.push({
      start: found.index,
      end: found.index + found[0].length,
      field: clause.field,
      label: clause.label,
    })
  }

  const name = (marks[0] === undefined ? rest : rest.slice(0, marks[0].start))
    .replace(FILLER, '')
    .trim()

  const dates: SpokenDates = {}
  const unclear = new Set<string>()
  // De qué cláusula salió cada fecha, que es lo que después permite preguntarle si nombró el
  // mes. Se guarda el texto y no un booleano porque la última repetición pisa a la anterior.
  const said: Partial<Record<keyof SpokenDates, string>> = {}
  marks.forEach((mark, index) => {
    const clause = rest.slice(mark.end, marks[index + 1]?.start ?? rest.length)
    const date = parseSpokenDate(clause, today)
    // **La última vez que se dijo una fecha gana.** Repetir una palabra clave es como se
    // corrige hablando —"desde el 1, no, desde el 2"—, y la corrección va después. De ahí
    // también el `delete`: si el primer intento no se entendió y el segundo sí, no quedó nada
    // sin entender.
    if (date === undefined) {
      unclear.add(mark.label)
    } else {
      dates[mark.field] = date
      said[mark.field] = clause
      unclear.delete(mark.label)
    }
  })

  resolvePeriod(dates, said, unclear)
  return { name, dates, unclear: [...unclear] }
}

/**
 * El período, que es la única fecha que se dice en dos pedazos y hay que leer junta.
 *
 * "Desde el 1 hasta el 31 de agosto" nombra el mes una sola vez, y así es como se habla. Cada
 * punta resuelta por su cuenta no puede acertar: `parseSpokenDate` no ve más que "el 1" y le
 * pone el mes más cercano a hoy, que el 28 de agosto es septiembre — el período saldría del 1
 * de septiembre al 31 de agosto, al revés y sin que nada lo dijera. Así que **la punta que no
 * nombra el mes lo toma de la que sí**.
 *
 * Corre solo sobre `desde`/`hasta` y no sobre las otras dos fechas a propósito: son las únicas
 * dos que forman un par. "Vence el 10", dicho el 28 de agosto, quiere decir el 10 de
 * septiembre aunque el período facturado sea agosto, y ahí la regla del mes más cercano es la
 * que acierta.
 *
 * Lo que **no** hace es adivinar cuando no hay de dónde: si ninguna de las dos nombró el mes y
 * el período queda invertido, las dos vuelven a "no se entendió" y el usuario lo repite. Un
 * período dado vuelta que la app corrige sola es una factura de servicios declarada con otro
 * período, y eso lo lee ARCA, no el usuario.
 */
function resolvePeriod(
  dates: SpokenDates,
  said: Partial<Record<keyof SpokenDates, string>>,
  unclear: Set<string>,
) {
  const { from_date: from, to_date: to } = dates
  if (from === undefined || to === undefined) return

  const fromNames = mentionsMonth(said.from_date ?? '')
  const toNames = mentionsMonth(said.to_date ?? '')
  if (fromNames !== toNames) {
    const borrowed = fromNames ? inMonthOf(to, from) : inMonthOf(from, to)
    const field = fromNames ? 'to_date' : 'from_date'
    if (borrowed === undefined) {
      // "Hasta el 31" con el período en febrero: ese día no existe en ese mes. Es el mismo
      // criterio que el 31 de febrero de `parseSpokenDate` — no entender es una respuesta.
      delete dates[field]
      unclear.add(fromNames ? 'hasta' : 'desde')
      return
    }
    dates[field] = borrowed
  }

  const { from_date: start, to_date: end } = dates
  if (start !== undefined && end !== undefined && start > end) {
    delete dates.from_date
    delete dates.to_date
    unclear.add('desde')
    unclear.add('hasta')
  }
}

/** El día de `iso`, pero en el mes de `anchor`. `undefined` si ese día no existe ahí. */
function inMonthOf(iso: string, anchor: string): string | undefined {
  const day = Number(iso.slice(8, 10))
  const year = Number(anchor.slice(0, 4))
  const month = Number(anchor.slice(5, 7))
  const date = new Date(year, month - 1, day)
  return date.getMonth() === month - 1 ? isoDate(date) : undefined
}

export type TemplateMatch =
  /** El nombre viaja con el id porque es lo que la app repite en voz alta al confirmar: lo que
   *  hay que oír es el nombre **guardado**, no el que se entendió. Si se dijo "alquiler" y el
   *  modelo se llama "Alquiler cochera", eso es exactamente lo que hay que enterarse. */
  | { kind: 'one'; id: string; name: string }
  | { kind: 'none' }
  /** Más de un modelo coincide. Se devuelven los nombres para poder mostrarlos. */
  | { kind: 'many'; names: string[] }

/**
 * El nombre que se escuchó → el modelo, **si no hay dudas**.
 *
 * Tres pasadas, de la más estricta a la más floja, y gana la primera que encuentre algo: el
 * nombre completo, el nombre contenido de un lado o del otro ("luz" adentro de "Factura de
 * luz"), y por último todas las palabras dichas presentes en el nombre en cualquier orden.
 * Están separadas para que una coincidencia exacta le gane siempre a una parcial: con
 * "Alquiler" y "Alquiler cochera" cargados, decir "alquiler" tiene que dar el primero y no
 * dos candidatos.
 *
 * **Empatar no es elegir.** Si quedan dos, se contesta `many` y el usuario repite con el
 * nombre completo. Adivinar acá llevaría a la pantalla de confirmación del modelo equivocado,
 * con el nombre correcto de otro cliente escrito arriba del botón de emitir.
 *
 * Las palabras de menos de tres letras se ignoran en la última pasada: "de", "la" y "el" están
 * en casi todos los nombres y harían coincidir a cualquiera con cualquiera.
 */
export function matchTemplate(
  spoken: string,
  templates: ReadonlyArray<{ id: string; name: string }>,
): TemplateMatch {
  if (spoken === '') return { kind: 'none' }

  const candidates = templates.map((template) => ({
    ...template,
    normalized: normalizeSpoken(template.name),
  }))
  const words = spoken.split(' ').filter((word) => word.length >= 3)

  const passes = [
    (name: string) => name === spoken,
    (name: string) => name.includes(spoken) || spoken.includes(name),
    (name: string) => words.length > 0 && words.every((word) => name.includes(word)),
  ]

  for (const matches of passes) {
    const found = candidates.filter((candidate) => matches(candidate.normalized))
    if (found.length === 1) return { kind: 'one', id: found[0]!.id, name: found[0]!.name }
    if (found.length > 1) return { kind: 'many', names: found.map((candidate) => candidate.name) }
  }
  return { kind: 'none' }
}

/**
 * La ruta de confirmación del modelo, con las fechas dictadas colgadas de la query.
 *
 * **Query y no estado del router.** El estado de `navigate` se pierde al recargar, y ahí la
 * pantalla volvería a los defaults sin decir nada: las fechas que se dictaron dejarían de
 * estar y ningún cartel lo mostraría. En la URL sobreviven, se leen antes de emitir y se
 * pueden corregir a mano. Los nombres van en castellano porque las rutas de esta app también.
 */
export function emitPath(id: string, dates: SpokenDates): string {
  const params = new URLSearchParams()
  const named: ReadonlyArray<readonly [string, string | undefined]> = [
    ['fecha', dates.date],
    ['desde', dates.from_date],
    ['hasta', dates.to_date],
    ['vence', dates.due_date],
  ]
  for (const [key, value] of named) if (value !== undefined) params.set(key, value)
  const query = params.toString()
  return `/modelos/${id}/emitir${query === '' ? '' : `?${query}`}`
}
