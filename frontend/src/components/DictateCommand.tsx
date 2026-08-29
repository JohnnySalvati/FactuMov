import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { needsServiceDates, type Concepto } from '../api/types'
import { emitPath, matchTemplate, monthDates, parseSpokenCommand } from '../commands'
import { useSpeechInput } from '../hooks/useSpeechInput'
import { armSpeech, say } from '../speak'
import { SpeakToggle } from './SpeakToggle'

interface Props {
  /**
   * El `concepto` viaja además del nombre porque el comando decide con él: un mes dicho a
   * secas es un período, y un período solo existe en una factura de servicios. La grilla ya lo
   * tiene cargado, así que preguntarlo no cuesta un request.
   */
  templates: ReadonlyArray<{ id: string; name: string; concepto: Concepto }>
}

/**
 * Lo último que **no** salió, para poder contarlo en una sola línea de estado.
 *
 * No tiene caso "salió bien": cuando sale bien la app cambia de pantalla, esta se desmonta y
 * la confirmación de lo que se entendió es la pantalla de emisión, que muestra —y lee en voz
 * alta— el modelo, el destinatario, el importe y las fechas cargadas.
 */
type Outcome =
  | { kind: 'not-a-command' }
  | { kind: 'none' }
  | { kind: 'many'; names: string[] }
  | { kind: 'unclear'; labels: string[] }
  /**
   * Se dijo un mes, pero el modelo es de productos y una factura de productos no lleva período.
   *
   * **No se navega igual ignorando el mes**, que sería lo cómodo: el mes es la mitad de lo que
   * se pidió, y la pantalla de emisión de un modelo de productos no tiene dónde mostrarlo — no
   * habría nada raro que ver antes de apretar el botón. Contestarlo es lo que hace que se
   * entienda que el modelo está cargado como productos, que es lo que hay que arreglar.
   */
  | { kind: 'month-on-products'; name: string }

/**
 * Lo mismo que dice la pantalla, dicho para el oído.
 *
 * Está acá al lado del texto escrito y no en el `commands.ts` para que las dos versiones se
 * lean juntas: son la misma respuesta, y la que se desactualice va a ser la que quede lejos.
 * Lo que cambia entre una y otra es la forma —hablando no se puede decir «lo que se escuchó»
 * entre comillas, y una lista se enumera distinto— pero nunca el contenido: si la voz dijera
 * menos que la pantalla, confiar en el oído sería peor que leer.
 */
function outcomeAloud(outcome: Outcome): string {
  switch (outcome.kind) {
    case 'not-a-command':
      return 'Eso no es un comando. Empezá diciendo emitir.'
    case 'none':
      return 'No encontré ningún modelo que se llame así.'
    case 'many':
      return (
        `Hay más de un modelo que coincide: ${outcome.names.join(', ')}. ` +
        'Decí el nombre completo.'
      )
    case 'unclear':
      return `No entendí la fecha de ${outcome.labels.join(', ni la de ')}.`
    case 'month-on-products':
      return (
        `${outcome.name} está cargado como productos, así que no lleva período. ` +
        'Repetí sin el mes, o cambiá el modelo a servicios.'
      )
  }
}

/**
 * "Emitir alquiler mensual desde el 1 de agosto hasta el 31, vence el 10 de septiembre." O,
 * más corto y más parecido a como se pide de verdad una factura de servicios, **"emitir
 * alquiler de agosto"**: el mes dice el período entero y las cuatro fechas salen de él.
 *
 * Vive en la grilla de modelos porque es la pantalla que se abre cien veces por semana y es
 * de donde arranca el recorrido que el comando ahorra: buscar la tarjeta entre veinte,
 * entrar, tocar "Emitir" y cargar tres fechas en el selector nativo del celular. Dicho de una
 * vez, eso queda en una frase y un botón.
 *
 * **No emite: lleva a la pantalla de confirmación con todo puesto.** Ver `commands.ts` — es
 * la misma regla que ya tenía el micrófono de las fechas, y la que hace que entender mal sea
 * una molestia y no una factura equivocada.
 *
 * **Contesta hablando** lo que no salió, además de escribirlo: el que dictó para no tipear
 * tampoco quiere tener que leer. Lo que sí salió no se dice acá — lo lee entera la pantalla de
 * emisión, que es la que conoce el comprobante completo. Se puede apagar con el botón de al
 * lado — ver `speak.ts`.
 *
 * Es un botón ancho y no el cuadradito de `DictateDate` porque acá el micrófono no acompaña a
 * ningún campo: es la acción de la pantalla, y en un celular tiene que poder tocarse sin
 * apuntar. Por eso también dice qué hace en vez de mostrar solo el ícono.
 */
export function DictateCommand({ templates }: Props) {
  const navigate = useNavigate()
  const [heard, setHeard] = useState<string>()
  const [outcome, setOutcome] = useState<Outcome>()

  /** Contar lo que pasó por los dos canales a la vez. Es el único lugar que fija un `Outcome`. */
  const report = (next: Outcome) => {
    setOutcome(next)
    say(outcomeAloud(next))
  }

  const speech = useSpeechInput((spoken) => {
    setHeard(spoken)
    const today = new Date()
    const command = parseSpokenCommand(spoken, today)
    if (command === undefined) return report({ kind: 'not-a-command' })
    // Las fechas se revisan **antes** que el modelo: si algo no se entendió no hay que
    // navegar, y da igual de qué modelo se trate. Al revés, una fecha perdida terminaría en
    // la pantalla de emisión disfrazada del default del mes en curso.
    if (command.unclear.length > 0) return report({ kind: 'unclear', labels: command.unclear })

    const match = matchTemplate(command.name, templates)
    if (match.kind === 'none') return report({ kind: 'none' })
    if (match.kind === 'many') return report({ kind: 'many', names: match.names })

    // El mes recién se puede resolver acá, que es donde se sabe de qué modelo se habla: son
    // cuatro fechas de período y el período lo pide ARCA solo en servicios. Por eso el parser
    // devuelve el mes crudo y la traducción ocurre después de encontrar el modelo.
    const { month } = command
    if (month !== undefined && !needsServiceDates(match.template.concepto)) {
      return report({ kind: 'month-on-products', name: match.template.name })
    }
    const dates = month === undefined ? command.dates : monthDates(month)

    // **Acá no se dice nada**, aunque haya con qué: lo que se entendió lo lee la pantalla de
    // emisión, entera y recién cuando la tiene. Un resumen dicho desde acá diría solo lo que
    // se dictó —ni el emisor, ni el cliente, ni el importe, ni las fechas que la app pone
    // sola— y encima le pisaría el arranque a la lectura buena: `say` cancela lo anterior,
    // así que dos respuestas seguidas son una respuesta cortada al medio.
    navigate(emitPath(match.template.id, dates))
  })

  // Los errores del micrófono también se dicen: "no se escuchó nada" es justo el caso en que
  // el usuario está esperando una respuesta que no va a llegar, y sin voz solo la ve quien
  // estaba mirando la pantalla. El efecto corre cuando cambia el error y no en cada render.
  useEffect(() => {
    if (speech.error !== undefined) say(speech.error)
  }, [speech.error])

  if (!speech.supported) return null

  return (
    <div className="voice-command">
      <div className="with-mic">
        {/* `type="button"` por costumbre y no por necesidad —acá no hay ningún `<form>` que
            pueda enviarse— pero el día que esto entre en uno, el default de `submit` sería el
            peor lugar posible para descubrirlo. */}
        <button
          type="button"
          className="mic wide"
          aria-pressed={speech.listening}
          onClick={() => {
            if (speech.listening) return speech.stop()
            // Desde el toque, que es lo que iOS pide para poder hablar después, y lo que
            // corta la respuesta anterior antes de abrir el micrófono — si no, lo primero que
            // escucharía es a la app terminando la frase.
            armSpeech()
            speech.start()
          }}
        >
          {speech.listening ? '■ Escuchando…' : '🎤 Emitir por voz'}
        </button>
        <SpeakToggle />
      </div>

      <p className="mic-status" aria-live="polite">
        {speech.error !== undefined ? (
          <span className="mic-error">{speech.error}</span>
        ) : speech.listening ? (
          'Decí «emitir» y el nombre del modelo.'
        ) : outcome === undefined ? (
          <>
            Decí «emitir alquiler de agosto» para el mes entero, o «emitir alquiler» y agregale
            «con fecha ayer» o «desde el 1 de agosto hasta el 31, vence el 10 de septiembre».
          </>
        ) : (
          <span className="mic-error">
            {outcome.kind === 'not-a-command' ? (
              <>Se escuchó «{heard}» y no es un comando. Empezá por «emitir».</>
            ) : outcome.kind === 'unclear' ? (
              <>
                Se escuchó «{heard}» y no se entendió la fecha de «
                {outcome.labels.join('», «')}».
              </>
            ) : outcome.kind === 'month-on-products' ? (
              <>
                Se escuchó «{heard}» y «{outcome.name}» está cargado como productos, así que no
                lleva período. Repetí sin el mes, o cambiá el modelo a servicios.
              </>
            ) : outcome.kind === 'many' ? (
              <>
                Se escuchó «{heard}» y hay más de un modelo que coincide:{' '}
                {outcome.names.join(', ')}. Decí el nombre completo.
              </>
            ) : (
              <>Se escuchó «{heard}» y no hay ningún modelo que se llame así.</>
            )}
          </span>
        )}
      </p>
    </div>
  )
}
