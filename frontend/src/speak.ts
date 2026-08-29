/**
 * La app contestando en voz alta lo que entendió.
 *
 * Es la otra mitad del dictado: si uno le habla al celular para no tener que tipear, tener que
 * **leer** la respuesta le devuelve la mitad del trabajo que venía a ahorrar — con el teléfono
 * en el bolsillo, manejando, o con el papel en la otra mano. Así que lo que se entendió se
 * muestra escrito **y** se dice; lo escrito no se va, porque es lo que queda para revisar
 * antes de emitir.
 *
 * `speechSynthesis` es el mismo Web Speech API que ya usa el dictado, del otro lado: gratis,
 * instalado, sin tocar el servidor y sin mandar nada a ningún lado — al revés que el
 * reconocimiento, esto **no** sale del dispositivo, porque la voz la sintetiza el sistema.
 *
 * **Se puede apagar y se recuerda apagado.** Que la app conteste hablando es lo que uno quiere
 * cuando dicta y lo último que quiere en una oficina con gente al lado, y esas dos situaciones
 * son la misma persona en dos momentos del día.
 */

/** El texto que se dice se arma acá, así que el mes se escribe con una sola grafía. La lista
 *  de `speech.ts` acepta "septiembre" y "setiembre" porque escucha; esta elige una. */
const MONTHS = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
]

const STORAGE_KEY = 'factumov.hablar'

export const speechOutputSupported =
  typeof window !== 'undefined' && 'speechSynthesis' in window

/**
 * Si la preferencia no está guardada, la app habla.
 *
 * El default es hablar y no callar porque esto contesta **a un dictado**: el que apretó el
 * micrófono ya habló en voz alta, así que una respuesta hablada no lo expone a nada que no se
 * haya expuesto solo. Al revés —callado por default— la funcionalidad no existiría para el
 * que no sabe que hay que prenderla.
 *
 * El `try` no es decorativo: `localStorage` **tira** y no devuelve `null` en Safari con la
 * navegación privada. Sin esto, la grilla de modelos no renderiza.
 */
function stored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== 'no'
  } catch {
    return true
  }
}

let enabled = speechOutputSupported && stored()

export function speaks(): boolean {
  return enabled
}

export function setSpeaks(value: boolean) {
  enabled = value
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? 'si' : 'no')
  } catch {
    // Sin dónde guardarlo la preferencia vale para esta pantalla y se olvida al recargar, que
    // es mejor que romper el botón.
  }
}

/** Callarse ya. Apagar la voz en la mitad de una frase tiene que cortar esa frase. */
export function hush() {
  if (speechOutputSupported) window.speechSynthesis.cancel()
}

/** Si ya se desbloqueó la voz en este gesto del usuario. Ver `armSpeech`. */
let armed = false

/**
 * Lo que hay que llamar **desde el toque del usuario**, antes de abrir el micrófono.
 *
 * Hace dos cosas, las dos por el mismo motivo —que la voz llega después, cuando ya no hay
 * ningún gesto a mano—:
 *
 * 1. **Corta lo que estuviera diciendo.** Si no, el micrófono que se está por abrir escucha a
 *    la app terminando la frase anterior y la transcribe como si fuera el usuario.
 * 2. **Desbloquea la síntesis.** iOS exige que el primer `speak()` de la página salga de un
 *    gesto; el nuestro sale de un callback del reconocedor, que no lo es. Una frase muda en el
 *    momento del toque paga esa entrada una sola vez.
 */
export function armSpeech() {
  if (!speechOutputSupported) return
  hush()
  if (armed || !enabled) return
  const silent = new SpeechSynthesisUtterance(' ')
  silent.volume = 0
  window.speechSynthesis.speak(silent)
  armed = true
}

/**
 * Decir algo. No hace nada si la voz está apagada o el navegador no la tiene.
 *
 * `cancel()` antes de cada frase: las que se dicen acá **se pisan, no se encolan**. Dictar tres
 * veces seguidas tiene que contestar lo último que se entendió, no una fila de tres respuestas
 * de las cuales las dos primeras ya no son ciertas.
 *
 * El `lang` se pide y las voces no se enumeran a propósito: `getVoices()` devuelve vacío hasta
 * que el navegador las carga —de forma asincrónica, y en Chrome la primera vez llega tarde—,
 * así que elegir una a mano significaría o esperar un evento o hablar en inglés la primera vez.
 * Pidiendo el idioma, la elige el sistema y siempre hay una.
 */
export function say(text: string) {
  if (!enabled || !speechOutputSupported || text === '') return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'es-AR'
  window.speechSynthesis.speak(utterance)
}

/**
 * `2026-08-15` → "15 de agosto". Con el año solo si no es el de hoy.
 *
 * `formatDate` no sirve para esto: "15/08/2026" lo lee "quince barra cero ocho barra dos mil
 * veintiséis", que es exactamente lo que uno no quiere escuchar cuando lo que está
 * confirmando es una fecha. El año se dice solo cuando cambia porque en una factura casi
 * siempre es el corriente, y repetirlo en cada respuesta alarga todas para el caso raro — pero
 * cuando cambia hay que decirlo, que es justo cuando el dictado pudo haber entendido otra cosa.
 */
export function spokenDate(iso: string, today: Date): string {
  const [year, month, day] = iso.split('-').map(Number)
  const name = MONTHS[month - 1] ?? ''
  const suffix = year === today.getFullYear() ? '' : ` de ${year}`
  return `${day} de ${name}${suffix}`
}
