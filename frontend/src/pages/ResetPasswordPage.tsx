import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ApiError, api } from '../api/client'
import type { MessageResponse } from '../api/types'
import { Notice } from '../components/Notice'

/** El mismo mínimo que valida el schema del backend, igual que en el registro: avisa antes
 *  de mandar, no reemplaza al 422. */
const PASSWORD_MIN_LENGTH = 10

/**
 * Donde aterriza el link del mail de reset: `/restablecer-password?token=…`.
 *
 * La ruta la fija `APP_BASE_URL` + `_PASSWORD_RESET_PATH` del backend. Cambiarle el nombre
 * acá sin cambiarlo allá deja apuntando a la nada los mails ya enviados.
 *
 * A diferencia de `ConfirmEmailPage`, **no postea sola al montar**: acá falta un dato que
 * solo puede dar el usuario. El token se manda recién con el submit, así que el token de un
 * solo uso no se quema por abrir el link — ni por el doble montaje de StrictMode, que es lo
 * que aquella pantalla tiene que esquivar con un `useRef`.
 *
 * **No abre sesión**, por lo mismo que la confirmación no la abre: el token vivió en una
 * casilla de mail. Termina mandando al login con la contraseña nueva.
 */
export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string>()
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!token) return
    setBusy(true)
    setError(undefined)
    try {
      await api.post<MessageResponse>('/auth/reset-password', { token, password })
      setDone(true)
    } catch (caught) {
      // Token desconocido, vencido, ya usado y de un usuario dado de baja son el mismo 400
      // del lado del backend, porque el remedio de los cuatro es pedir un link nuevo.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo cambiar la contraseña.')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <div className="centered">
        <h1>Contraseña cambiada</h1>
        <div className="card">
          <Notice kind="ok">
            Listo. Cerramos todas las sesiones que estaban abiertas, así que entrá de nuevo
            con la contraseña nueva.
          </Notice>
        </div>
        <p className="muted">
          <Link to="/login">Ir a entrar</Link>
        </p>
      </div>
    )
  }

  return (
    <div className="centered">
      <h1>Elegí una contraseña nueva</h1>
      {token ? (
        <form className="card stack" onSubmit={onSubmit}>
          <div>
            <label htmlFor="password">Contraseña nueva</label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={PASSWORD_MIN_LENGTH}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="muted" style={{ fontSize: '0.82rem', margin: '0.3rem 0 0' }}>
              Mínimo {PASSWORD_MIN_LENGTH} caracteres. Mejor una frase larga que algo corto y
              raro.
            </p>
          </div>
          <Notice kind="error">{error}</Notice>
          <button type="submit" disabled={busy}>
            {busy ? 'Guardando…' : 'Cambiar la contraseña'}
          </button>
        </form>
      ) : (
        <div className="card">
          <Notice kind="error">
            El link no trae token. Copialo entero desde el mail, o pedí uno nuevo.
          </Notice>
        </div>
      )}
      <p className="muted">
        ¿El link venció? <Link to="/olvide-password">Pedí uno nuevo</Link>.
      </p>
    </div>
  )
}
