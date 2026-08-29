import { useState } from 'react'

import { armSpeech, hush, say, setSpeaks, speaks, speechOutputSupported } from '../speak'

/**
 * El interruptor de la voz de la app. Prendido, contesta hablando lo que entendió.
 *
 * **Uno solo y global**, acá al lado del micrófono del comando. La alternativa era repetirlo
 * junto a cada campo que se puede dictar, y en la pantalla de emisión eso son cuatro botones
 * de silencio para una sola preferencia — cuatro lugares donde apagarla y cuatro donde
 * descubrir que estaba apagada en otro lado. La contra conocida es que para cambiarla desde la
 * pantalla de emisión hay que volver a la grilla; se paga cuando se cambia de opinión, que es
 * bastante menos seguido que dictar.
 *
 * Prenderla **dice que quedó prendida**, y no es un adorno: es la única prueba de que el
 * dispositivo puede hablar. Además ocurre dentro del toque del usuario, que es donde iOS
 * permite el primer `speak()` de la página.
 */
export function SpeakToggle() {
  const [on, setOn] = useState(speaks)

  if (!speechOutputSupported) return null

  return (
    <button
      type="button"
      className="mic"
      aria-pressed={on}
      aria-label={on ? 'La app contesta hablando: apagar' : 'La app contesta hablando: prender'}
      title={on ? 'Te contesta hablando' : 'No te contesta hablando'}
      onClick={() => {
        const next = !on
        setSpeaks(next)
        setOn(next)
        if (next) {
          armSpeech()
          say('Listo, te contesto hablando.')
        } else {
          hush()
        }
      }}
    >
      {on ? '🔊' : '🔇'}
    </button>
  )
}
