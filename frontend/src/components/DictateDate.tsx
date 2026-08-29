import { useState, type ReactNode } from 'react'

import { formatDate } from '../format'
import { useSpeechInput } from '../hooks/useSpeechInput'
import { parseSpokenDate } from '../speech'

interface Props {
  id: string
  label: string
  /** El `YYYY-MM-DD` que muestra el campo. */
  value: string
  min?: string
  max?: string
  /** El texto de ayuda del campo, si tiene. Va entre el campo y el estado del dictado. */
  hint?: ReactNode
  onChange: (value: string) => void
}

/**
 * Un campo de fecha con un micrófono al lado.
 *
 * Fue por dónde empezó el dictado, y no por un comando hablado: es el único campo editable de
 * la pantalla de emisión, y tipear una fecha en el selector nativo de un celular es justo lo
 * que más molesta. Cerrado el spike —abre y entrega en iPad, Android y computadora—, el
 * comando existe y vive en `DictateCommand`; esto quedó como lo que corrige a mano una fecha
 * que el comando no dijo o entendió distinto.
 *
 * **El micrófono llena el campo y nada más.** No emite, no manda el formulario y no toca
 * ningún otro campo. Emitir le pide el CAE a ARCA y no se puede deshacer, así que lo que la
 * voz puede hacer es dejar el formulario listo con lo que entendió escrito en pantalla; el
 * botón lo aprieta el dedo. Con eso, entender mal es una molestia y no una factura
 * equivocada.
 *
 * Vive en un componente y no repetido en cada campo por lo mismo que `TileGrid`: adentro hay
 * estado, un hook con su limpieza y tres mensajes de estado. Copiado cuatro veces, la próxima
 * corrección arregla un campo y deja tres rotos.
 */
export function DictateDate({ id, label, value, min, max, hint, onChange }: Props) {
  // Lo que se escuchó **y** en qué fecha cayó, juntos y no en dos estados. El mensaje tiene que
  // seguir diciendo la verdad después de que el usuario corrija el campo a mano: leyendo el
  // `value` del input diría "se escuchó «hoy» → 03/09/2026", que es un dictado que no ocurrió.
  const [last, setLast] = useState<{ heard: string; date?: string }>()

  const speech = useSpeechInput((heard) => {
    const date = parseSpokenDate(heard, new Date())
    setLast({ heard, date })
    if (date !== undefined) onChange(date)
  })

  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <div className="with-mic">
        <input
          id={id}
          type="date"
          required
          value={value}
          min={min}
          max={max}
          onChange={(event) => onChange(event.target.value)}
        />
        {speech.supported && (
          // `type="button"` **no es opcional**: el default de un `<button>` adentro de un
          // `<form>` es `submit`, y el formulario de esta pantalla emite una factura con CAE.
          // Sin esto, apretar el micrófono emitiría.
          <button
            type="button"
            className="mic"
            aria-label={`Dictar ${label.toLowerCase()}`}
            aria-pressed={speech.listening}
            onClick={speech.listening ? speech.stop : speech.start}
          >
            {speech.listening ? '■' : '🎤'}
          </button>
        )}
      </div>
      {hint}
      {/* `aria-live` para que el lector de pantalla anuncie lo que se escuchó: el resto de la
          confirmación es que el campo cambió solo, que es justo lo que no se ve sin mirar. */}
      <p className="mic-status" aria-live="polite">
        {speech.error !== undefined ? (
          <span className="mic-error">{speech.error}</span>
        ) : speech.listening ? (
          'Escuchando…'
        ) : last === undefined ? null : last.date !== undefined ? (
          <>
            Se escuchó «{last.heard}» → {formatDate(last.date)}.
          </>
        ) : (
          <span className="mic-error">
            Se escuchó «{last.heard}» y no se entendió una fecha. Probá «hoy», «el 15» o «15 de
            agosto».
          </span>
        )}
      </p>
    </div>
  )
}
