import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Un dictado por vez, contra el reconocedor que ya trae el navegador.
 *
 * **Web Speech API y no un servicio de transcripción propio.** La alternativa era grabar con
 * `MediaRecorder`, subir el audio y transcribirlo en el backend: anda parejo en todos lados,
 * pero cuesta por minuto, agrega un endpoint y suma latencia. Esto es gratis, no toca el
 * servidor y ya está instalado. Lo que se paga a cambio es que el soporte no es parejo — de
 * ahí `supported`, y de ahí que este hook sea un spike y no todavía una funcionalidad.
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
  typeof window === 'undefined' ? undefined : (window.SpeechRecognition ?? window.webkitSpeechRecognition)

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
  start: () => void
  stop: () => void
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
  const recognition = useRef<SpeechRecognitionLike>(null)
  const heardCallback = useRef(onHeard)
  // En un efecto y no directo en el cuerpo: asignar una ref durante el render es lo que
  // marca el linter, y con razón —en modo concurrente un render puede descartarse—. Acá
  // corre antes de que el usuario llegue a apretar nada.
  useEffect(() => {
    heardCallback.current = onHeard
  }, [onHeard])

  const stop = useCallback(() => {
    // `abort` y no `stop`: `stop` procesa lo que venía escuchando y puede terminar cargando
    // una fecha después de que el usuario apagó el micrófono.
    recognition.current?.abort()
  }, [])

  const start = useCallback(() => {
    if (Recognition === undefined || recognition.current !== null) return

    // Una instancia nueva por dictado, en vez de una sola guardada y reusada. Reusarla es
    // donde los navegadores se portan distinto: llamar `start()` sobre una que todavía no
    // terminó tira `InvalidStateError`, y el final no llega siempre por el mismo evento.
    // Creándola acá, cada dictado empieza sin estado heredado del anterior.
    const current = new Recognition()
    current.lang = 'es-AR'
    // Un solo resultado y final: esto dicta un campo, no transcribe una conversación. Con
    // `interimResults` habría que ir descartando versiones a medio escuchar.
    current.continuous = false
    current.interimResults = false
    current.maxAlternatives = 1

    current.onresult = (event) => {
      const heard = event.results[0]?.[0]?.transcript
      if (heard !== undefined) heardCallback.current(heard)
    }
    current.onerror = (event) => setError(describe(event.error))
    // `onend` llega siempre: después de un resultado, de un error y de un `abort`. Es el único
    // lugar donde conviene soltar la instancia, porque es el único por el que pasan los tres.
    current.onend = () => {
      recognition.current = null
      setListening(false)
    }

    try {
      current.start()
    } catch {
      // iOS puede rechazar el `start()` sin emitir ningún evento — típicamente cuando el
      // contexto no es seguro o la app corre instalada en la pantalla de inicio. Sin este
      // `catch` el botón se queda prendido para siempre y no dice nada.
      setError('No se pudo abrir el micrófono.')
      return
    }

    recognition.current = current
    setError(undefined)
    setListening(true)
  }, [])

  // Salir de la pantalla con el micrófono abierto lo dejaría escuchando y llamando a un
  // callback de un componente desmontado.
  useEffect(() => stop, [stop])

  return { supported: Recognition !== undefined, listening, error, start, stop }
}
