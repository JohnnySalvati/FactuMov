import { useState } from 'react'
import { useNavigate } from 'react-router'

import { emitPath, matchTemplate, parseSpokenCommand } from '../commands'
import { useSpeechInput } from '../hooks/useSpeechInput'

interface Props {
  templates: ReadonlyArray<{ id: string; name: string }>
}

/**
 * Lo último que **no** salió, para poder contarlo en una sola línea de estado.
 *
 * No tiene caso "salió bien": cuando sale bien la app cambia de pantalla, esta se desmonta y
 * la confirmación de lo que se entendió es la pantalla de emisión, que muestra el modelo, el
 * destinatario, el importe y las fechas cargadas. Un cartel verde acá lo vería nadie.
 */
type Outcome =
  | { kind: 'not-a-command' }
  | { kind: 'none' }
  | { kind: 'many'; names: string[] }
  | { kind: 'unclear'; labels: string[] }

/**
 * "Emitir alquiler mensual desde el 1 de agosto hasta el 31, vence el 10 de septiembre."
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
 * Es un botón ancho y no el cuadradito de `DictateDate` porque acá el micrófono no acompaña a
 * ningún campo: es la acción de la pantalla, y en un celular tiene que poder tocarse sin
 * apuntar. Por eso también dice qué hace en vez de mostrar solo el ícono.
 */
export function DictateCommand({ templates }: Props) {
  const navigate = useNavigate()
  const [heard, setHeard] = useState<string>()
  const [outcome, setOutcome] = useState<Outcome>()

  const speech = useSpeechInput((spoken) => {
    setHeard(spoken)
    const command = parseSpokenCommand(spoken, new Date())
    if (command === undefined) {
      setOutcome({ kind: 'not-a-command' })
      return
    }
    // Las fechas se revisan **antes** que el modelo: si algo no se entendió no hay que
    // navegar, y da igual de qué modelo se trate. Al revés, una fecha perdida terminaría en
    // la pantalla de emisión disfrazada del default del mes en curso.
    if (command.unclear.length > 0) {
      setOutcome({ kind: 'unclear', labels: command.unclear })
      return
    }
    const match = matchTemplate(command.name, templates)
    if (match.kind === 'none') {
      setOutcome({ kind: 'none' })
      return
    }
    if (match.kind === 'many') {
      setOutcome({ kind: 'many', names: match.names })
      return
    }
    navigate(emitPath(match.id, command.dates))
  })

  if (!speech.supported) return null

  return (
    <div className="voice-command">
      {/* `type="button"` por costumbre y no por necesidad —acá no hay ningún `<form>` que
          pueda enviarse— pero el día que esto entre en uno, el default de `submit` sería el
          peor lugar posible para descubrirlo. */}
      <button
        type="button"
        className="mic wide"
        aria-pressed={speech.listening}
        onClick={speech.listening ? speech.stop : speech.start}
      >
        {speech.listening ? '■ Escuchando…' : '🎤 Emitir por voz'}
      </button>

      <p className="mic-status" aria-live="polite">
        {speech.error !== undefined ? (
          <span className="mic-error">{speech.error}</span>
        ) : speech.listening ? (
          'Decí «emitir» y el nombre del modelo.'
        ) : outcome === undefined ? (
          <>
            Decí «emitir alquiler», y si querés agregale «con fecha ayer» o «desde el 1 de
            agosto hasta el 31, vence el 10 de septiembre».
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
