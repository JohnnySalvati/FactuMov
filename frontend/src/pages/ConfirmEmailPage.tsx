import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ApiError, api } from '../api/client'
import type { MessageResponse } from '../api/types'
import { Notice } from '../components/Notice'

type Status = 'working' | 'ok' | 'failed'

/**
 * Donde aterriza el link del mail: `/confirmar-email?token=…`.
 *
 * La ruta la fija `APP_BASE_URL` + `_CONFIRMATION_PATH` del backend. Si se le cambia el
 * nombre acá hay que cambiarlo allá, o los mails ya enviados apuntan a una pantalla que no
 * existe.
 *
 * **No abre sesión.** El backend podría devolver una cookie al confirmar y sería mejor UX,
 * pero ese token vivió 24 horas en una casilla de mail: convertirlo en sesión dejaría
 * adentro a cualquiera con acceso a ese mensaje. Por eso termina mandando al login.
 */
export function ConfirmEmailPage() {
  const [params] = useSearchParams()
  const token = params.get('token')
  // El link sin token se resuelve en el estado inicial y no adentro del efecto: es algo que
  // ya se sabe al primer render, y decidirlo con un `setState` en el efecto sería un render
  // de más para mostrar algo que nunca fue a la red.
  const [status, setStatus] = useState<Status>(token ? 'working' : 'failed')
  const [error, setError] = useState<string | undefined>(
    token ? undefined : 'El link no trae token. Copialo entero desde el mail.',
  )
  // El token es de un solo uso: el segundo POST da 400. En desarrollo, el StrictMode de React
  // monta cada componente dos veces a propósito, así que sin este guard la confirmación
  // andaría y la pantalla mostraría igual "el link no es válido".
  const sent = useRef(false)

  useEffect(() => {
    if (!token || sent.current) return
    sent.current = true

    api
      .post<MessageResponse>('/auth/confirm', { token })
      .then(() => setStatus('ok'))
      .catch((caught: unknown) => {
        // Token desconocido, vencido, ya usado y de un usuario dado de baja son el mismo 400
        // del lado del backend, porque el remedio de los cuatro es pedir uno nuevo.
        setError(caught instanceof ApiError ? caught.detail : 'No se pudo confirmar.')
        setStatus('failed')
      })
  }, [token])

  return (
    <div className="centered">
      <h1>Confirmar email</h1>
      <div className="card">
        {status === 'working' && <p className="muted">Confirmando…</p>}
        {status === 'ok' && (
          <Notice kind="ok">
            Listo, tu dirección quedó confirmada. Ya podés entrar con tu contraseña.
          </Notice>
        )}
        {status === 'failed' && <Notice kind="error">{error}</Notice>}
      </div>
      <p className="muted">
        <Link to="/login">Ir a entrar</Link>
      </p>
    </div>
  )
}
