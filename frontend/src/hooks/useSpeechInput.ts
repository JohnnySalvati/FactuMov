import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Un dictado por vez, contra el reconocedor que ya trae el navegador.
 *
 * **Web Speech API y no un servicio de transcripción propio.** La alternativa era grabar con
 * `MediaRecorder`, subir el audio y transcribirlo en el backend: anda parejo en todos lados,
 * pero cuesta por minuto, agrega un endpoint y suma latencia. Esto es gratis, no toca el
 * servidor y ya está instalado. Lo que se paga a cambio es que el soporte no es parejo — de
 * ahí `supported`, y de ahí que esto naciera como un spike. **El spike cerró el 2026-08-28:**
 * abre y entrega en iPad, en Android y en la computadora, así que el dictado dejó de ser una
 * prueba y pasó a ser una funcionalidad.
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
 * `QUIET_AFTER_MS` **se rearma con cada resultado**, así que mide silencio y no duración
 * total. Era un plazo fijo desde el arranque mientras esto solo dictaba una fecha —"treinta y
 * uno de agosto" entra en nueve segundos con tiempo de sobra—, pero un comando completo
 * ("emitir alquiler mensual desde el 1 de agosto hasta el 31, vence el 10 de septiembre") no
 * entra, y el plazo fijo cortaba al usuario en la mitad de la frase. Los parciales llegan
 * mientras se habla, así que rearmarlo con cada uno es lo que distingue "todavía está
 * hablando" de "se calló".
 *
 * `GIVE_UP_AFTER_MS` es absoluto y no se rearma, porque es justamente la red contra el caso en
 * que el motor no emite nada: es lo bruto después de lo prolijo — primero `stop()`, que le
 * pide al motor que **finalice y entregue**; si ni eso lo cierra, `abort()`.
 */
const QUIET_AFTER_MS = 8_000
const GIVE_UP_AFTER_MS = 30_000

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
}

/**
 * `onHeard` recibe el texto crudo, sin interpretar. Interpretarlo es de `parseSpokenDate` y de
 * `parseSpokenCommand`.
 *
 * Se guarda en una ref y no en las dependencias de `start`: el que llama la va a definir en
 * línea, así que cambia de identidad en cada render, y con eso en el `useCallback` `start`
 * también cambiaría en cada render. Acá eso no sería solo ruido — `start` viaja al `onClick`
 * de un botón que se puede apretar en cualquier momento.
 */
export function useSpeechInput(onHeard: (heard: string) => void): SpeechInput {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState<string>()
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

    // Una instancia nueva por dictado, en vez de una sola guardada y reusada. Reusarla es
    // donde los navegadores se portan distinto: llamar `start()` sobre una que todavía no
    // terminó tira `InvalidStateError`, y el final no llega siempre por el mismo evento.
    // Creándola acá, cada dictado empieza sin estado heredado del anterior.
    const current = new Recognition()
    current.lang = 'es-AR'
    // Un solo tramo: esto dicta un campo o un comando, no transcribe una conversación.
    current.continuous = false
    // **Los parciales sí, aunque solo interese el final.** Safari en iOS puede cerrar la
    // sesión sin emitir nunca un resultado final; guardando el último parcial queda algo que
    // entregar en `onend` en vez de nada. En Chrome no cambia el resultado: llega el final y
    // ese es el que gana. Son además los que rearman el reloj del silencio.
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

    /** El reloj del silencio, de cero. Se llama al arrancar y con cada parcial. */
    const armQuiet = () => {
      // Solo el primero de los dos: el de `GIVE_UP` es absoluto y rearmarlo lo volvería
      // infinito, que es justo el caso contra el que existe.
      if (timers.current[0] !== undefined) window.clearTimeout(timers.current[0])
      timers.current[0] = window.setTimeout(() => current.stop(), QUIET_AFTER_MS)
    }

    current.onresult = (event) => {
      const result = event.results[event.results.length - 1]
      const heard = result?.[0]?.transcript
      if (heard === undefined) return
      best = heard
      armQuiet()
      if (result?.isFinal === true) deliver()
    }

    current.onerror = (event) => {
      setError(describe(event.error))
    }

    // `onend` llega siempre: después de un resultado, de un error y de un `abort`. Es el
    // único lugar por el que pasan los tres, así que es donde se suelta la instancia — y
    // donde se entrega el último parcial si nunca llegó un final.
    current.onend = () => {
      clearTimers()
      deliver()
      recognition.current = null
      setListening(false)
    }

    setError(undefined)

    try {
      current.start()
    } catch {
      // iOS puede rechazar el `start()` sin emitir ningún evento — típicamente cuando el
      // contexto no es seguro. Sin este `catch` el botón se queda prendido para siempre y no
      // dice nada.
      setError('No se pudo abrir el micrófono.')
      return
    }

    recognition.current = current
    setListening(true)
    timers.current = [
      window.setTimeout(() => current.stop(), QUIET_AFTER_MS),
      window.setTimeout(() => current.abort(), GIVE_UP_AFTER_MS),
    ]
  }, [clearTimers])

  // Salir de la pantalla con el micrófono abierto lo dejaría escuchando y llamando a un
  // callback de un componente desmontado. Acá sí `abort`: nadie espera un resultado.
  useEffect(() => cancel, [cancel])

  return { supported: Recognition !== undefined, listening, error, start, stop }
}
