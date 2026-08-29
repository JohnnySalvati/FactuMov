import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Un dictado por vez, contra el reconocedor que ya trae el navegador.
 *
 * **Web Speech API y no un servicio de transcripción propio.** La alternativa era grabar con
 * `MediaRecorder`, subir el audio y transcribirlo en el backend: anda parejo en todos lados,
 * pero cuesta por minuto, agrega un endpoint y suma latencia. Esto es gratis, no toca el
 * servidor y ya está instalado. Lo que se paga a cambio es que el soporte no es parejo — de
 * ahí `supported`, de ahí `trace`, y de ahí que este hook sea un spike y no todavía una
 * funcionalidad.
 *
 * En Chrome y en Safari el audio **sale del dispositivo**: lo transcriben los servidores de
 * Google y de Apple. No es distinto de dictarle al teclado del sistema, pero conviene tenerlo
 * escrito antes de que alguien dicte el nombre de un cliente.
 */

/**
 * `lib.dom` trae los eventos del Web Speech API (`SpeechRecognitionEvent`, el enum de errores)
 * pero **no la clase**, porque la especificación sigue en borrador y el nombre real en
 * Chrome/Safari es `webkitSpeechRecognition`. Se declara acá lo mínimo que se usa, en vez de
 * castear a `any`: el `any` se propagaría a `event.results` y ahí es donde de verdad importa
 * que el tipo esté puesto.
 */
interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
  onend: (() => void) | null
  onstart: (() => void) | null
  onaudiostart: (() => void) | null
  onsoundstart: (() => void) | null
  onspeechstart: (() => void) | null
  onspeechend: (() => void) | null
  onsoundend: (() => void) | null
  onaudioend: (() => void) | null
  onnomatch: (() => void) | null
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
}

/**
 * El constructor, resuelto una sola vez.
 *
 * El nombre sin prefijo va primero porque es el que va a quedar; hoy el que existe es el
 * `webkit`. Que sea `undefined` es un resultado válido y no un error: Firefox no implementa
 * nada de esto.
 */
const Recognition: SpeechRecognitionConstructor | undefined =
  typeof window === 'undefined'
    ? undefined
    : (window.SpeechRecognition ?? window.webkitSpeechRecognition)

/**
 * Cuándo cerrar por las nuestras.
 *
 * **Safari en iPad abre el micrófono y no lo cierra nunca**: el punto naranja queda prendido,
 * no llega ningún resultado y la sesión no termina sola (visto el 2026-08-28 en producción).
 * Sin estos dos relojes el usuario se queda con el micrófono abierto hasta que se acuerda de
 * apagarlo a mano, que es la peor forma posible de fallar.
 *
 * Primero `stop()`, que le pide al motor que **finalice y entregue** lo que venía escuchando;
 * si ni eso lo cierra, `abort()`, que corta a lo bruto. Los dos números son generosos a
 * propósito: dictar "treinta y uno de agosto" y dudar en el medio tiene que entrar.
 */
const FINALIZE_AFTER_MS = 9_000
const GIVE_UP_AFTER_MS = 14_000

/**
 * Los códigos del navegador, en castellano y diciendo qué hacer.
 *
 * Vale la pena distinguirlos: "no se escuchó nada" se arregla hablando de nuevo y "no diste
 * permiso" se arregla en la configuración del navegador, y con un único "no se pudo" el
 * usuario prueba diez veces lo que no va a andar nunca.
 */
function describe(code: SpeechRecognitionErrorCode): string | undefined {
  switch (code) {
    // El usuario cortó, o se desmontó la pantalla. No es una falla que haya que contarle.
    case 'aborted':
      return undefined
    case 'no-speech':
      return 'No se escuchó nada.'
    case 'not-allowed':
    case 'service-not-allowed':
      return 'El navegador no dio permiso para usar el micrófono.'
    case 'audio-capture':
      return 'No se encontró un micrófono.'
    case 'network':
      return 'El dictado necesita conexión: no se pudo llegar al servicio de reconocimiento.'
    case 'language-not-supported':
      return 'Este dispositivo no reconoce español.'
    default:
      return 'No se pudo escuchar.'
  }
}

export interface SpeechInput {
  /** `false` si el navegador no tiene el API. El que llama no debería dibujar el botón. */
  supported: boolean
  listening: boolean
  error?: string
  /** "Terminé de hablar": finaliza y entrega. No es lo mismo que abandonar. */
  stop: () => void
  start: () => void
  /**
   * Qué eventos emitió el motor, con el momento en que llegaron.
   *
   * **Es la razón de ser del spike.** En el iPad no hay consola que mirar desde Windows —la
   * inspección remota de Safari pide una Mac—, así que la única forma de saber dónde muere el
   * dictado es que la pantalla lo cuente. Con la traza se distingue "el micrófono nunca se
   * abrió" de "se abrió y no detectó voz" de "detectó voz y el servicio no devolvió nada", que
   * son tres problemas distintos con el mismo síntoma.
   */
  trace: string[]
}

/**
 * `onHeard` recibe el texto crudo, sin interpretar. Interpretarlo es de `parseSpokenDate`.
 *
 * Se guarda en una ref y no en las dependencias de `start`: el que llama la va a definir en
 * línea, así que cambia de identidad en cada render, y con eso en el `useCallback` `start`
 * también cambiaría en cada render. Acá eso no sería solo ruido — `start` viaja al `onClick`
 * de un botón que se puede apretar en cualquier momento.
 */
export function useSpeechInput(onHeard: (heard: string) => void): SpeechInput {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState<string>()
  const [trace, setTrace] = useState<string[]>([])
  const recognition = useRef<SpeechRecognitionLike>(null)
  const heardCallback = useRef(onHeard)
  const timers = useRef<number[]>([])

  // En un efecto y no directo en el cuerpo: asignar una ref durante el render es lo que
  // marca el linter, y con razón —en modo concurrente un render puede descartarse—. Acá
  // corre antes de que el usuario llegue a apretar nada.
  useEffect(() => {
    heardCallback.current = onHeard
  }, [onHeard])

  const clearTimers = useCallback(() => {
    for (const timer of timers.current) window.clearTimeout(timer)
    timers.current = []
  }, [])

  /** Abandonar sin entregar. Es para irse de la pantalla, no para el botón. */
  const cancel = useCallback(() => {
    clearTimers()
    recognition.current?.abort()
  }, [clearTimers])

  /**
   * "Terminé de hablar." `stop()` y no `abort()`, que es la diferencia entre finalizar y
   * tirar a la basura.
   *
   * Estaba al revés hasta el 2026-08-28, con el argumento de que `abort` evita que llegue una
   * fecha después de que el usuario apagó el micrófono. En iOS ese argumento se da vuelta:
   * **el motor no entrega nada hasta que se le pide finalizar**, así que `abort` garantizaba
   * exactamente el síntoma reportado — micrófono abierto, cuadrado apretado, nada capturado.
   * La molestia de una fecha que llega tarde es preferible a un dictado que no llega nunca.
   */
  const stop = useCallback(() => {
    clearTimers()
    recognition.current?.stop()
  }, [clearTimers])

  const start = useCallback(() => {
    if (Recognition === undefined || recognition.current !== null) return

    const startedAt = Date.now()
    const log = (event: string) =>
      setTrace((entries) => [...entries, `${((Date.now() - startedAt) / 1000).toFixed(1)}s  ${event}`])

    // Una instancia nueva por dictado, en vez de una sola guardada y reusada. Reusarla es
    // donde los navegadores se portan distinto: llamar `start()` sobre una que todavía no
    // terminó tira `InvalidStateError`, y el final no llega siempre por el mismo evento.
    // Creándola acá, cada dictado empieza sin estado heredado del anterior.
    const current = new Recognition()
    current.lang = 'es-AR'
    // Un solo tramo: esto dicta un campo, no transcribe una conversación.
    current.continuous = false
    // **Los parciales sí, aunque solo interese el final.** Safari en iOS puede cerrar la
    // sesión sin emitir nunca un resultado final; guardando el último parcial queda algo que
    // entregar en `onend` en vez de nada. En Chrome no cambia el resultado: llega el final y
    // ese es el que gana.
    current.interimResults = true
    current.maxAlternatives = 1

    // El mejor texto visto hasta ahora, y si ya se entregó. `delivered` existe porque el
    // final puede llegar por `onresult` y `onend` corre igual después: sin la guarda, un
    // dictado cargaría la fecha dos veces.
    let best: string | undefined
    let delivered = false
    const deliver = () => {
      if (delivered || best === undefined) return
      delivered = true
      heardCallback.current(best)
    }

    current.onstart = () => log('start — el motor arrancó')
    current.onaudiostart = () => log('audiostart — el micrófono está abierto')
    current.onsoundstart = () => log('soundstart — entra sonido')
    current.onspeechstart = () => log('speechstart — lo reconoce como voz')
    current.onspeechend = () => log('speechend — dejó de detectar voz')
    current.onsoundend = () => log('soundend')
    current.onaudioend = () => log('audioend — se cerró el micrófono')
    current.onnomatch = () => log('nomatch — escuchó algo y no lo entendió')

    current.onresult = (event) => {
      const result = event.results[event.results.length - 1]
      const heard = result?.[0]?.transcript
      if (heard === undefined) return
      best = heard
      log(`result ${result?.isFinal === true ? '(final)' : '(parcial)'}: "${heard}"`)
      if (result?.isFinal === true) deliver()
    }

    current.onerror = (event) => {
      log(`error: ${event.error}`)
      setError(describe(event.error))
    }

    // `onend` llega siempre: después de un resultado, de un error y de un `abort`. Es el
    // único lugar por el que pasan los tres, así que es donde se suelta la instancia — y
    // donde se entrega el último parcial si nunca llegó un final.
    current.onend = () => {
      log('end')
      clearTimers()
      deliver()
      recognition.current = null
      setListening(false)
    }

    // La traza y el error se limpian **antes** de arrancar: si se hiciera después, el reset
    // podría pisar lo que ya escribió un evento temprano.
    setError(undefined)
    setTrace([])

    try {
      current.start()
    } catch {
      // iOS puede rechazar el `start()` sin emitir ningún evento — típicamente cuando el
      // contexto no es seguro. Sin este `catch` el botón se queda prendido para siempre y no
      // dice nada.
      log('start() tiró una excepción')
      setError('No se pudo abrir el micrófono.')
      return
    }

    recognition.current = current
    setListening(true)
    timers.current = [
      window.setTimeout(() => {
        log(`sin cerrarse a los ${FINALIZE_AFTER_MS / 1000}s — pidiendo finalizar`)
        current.stop()
      }, FINALIZE_AFTER_MS),
      window.setTimeout(() => {
        log(`sigue abierto a los ${GIVE_UP_AFTER_MS / 1000}s — cortando`)
        current.abort()
      }, GIVE_UP_AFTER_MS),
    ]
  }, [clearTimers])

  // Salir de la pantalla con el micrófono abierto lo dejaría escuchando y llamando a un
  // callback de un componente desmontado. Acá sí `abort`: nadie espera un resultado.
  useEffect(() => cancel, [cancel])

  return { supported: Recognition !== undefined, listening, error, start, stop, trace }
}
