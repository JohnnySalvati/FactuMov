import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'

import { ApiError, api } from '../api/client'
import type { MessageResponse } from '../api/types'
import { Notice } from '../components/Notice'

/** El mismo mínimo que valida el schema del backend. Repetirlo acá es para avisar antes de
 *  mandar, no para reemplazar esa validación: el 422 sigue siendo la que manda. */
const PASSWORD_MIN_LENGTH = 10

export function RegisterPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string>()
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      await api.post<MessageResponse>('/auth/register', { email, password })
      setDone(true)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo crear la cuenta.')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    // El backend contesta 202 con el mismo cuerpo exista o no la dirección, para no delatar
    // qué emails están registrados. Esta pantalla tiene que respetar eso: dice que se mandó
    // un mail, sin afirmar que se creó una cuenta.
    return (
      <div className="centered">
        <h1>Revisá tu casilla</h1>
        <div className="card">
          <Notice kind="ok">
            Te mandamos un mail a <strong>{email}</strong> con un link para confirmar la
            dirección. El link vence en 24 horas.
          </Notice>
          <p className="muted" style={{ marginBottom: 0 }}>
            Si no llega, mirá el correo no deseado.
          </p>
        </div>
        <p className="muted">
          <Link to="/login">Volver a entrar</Link>
        </p>
      </div>
    )
  }

  return (
    <div className="centered">
      <h1>Crear cuenta</h1>
      <form className="card stack" onSubmit={onSubmit}>
        <div>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="password">Contraseña</label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={PASSWORD_MIN_LENGTH}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {/* Sin reglas de composición: el backend no las pide y NIST las desaconseja desde
              2017 porque empujan a `Password1!`. Lo único que se exige es largo. */}
          <p className="muted" style={{ fontSize: '0.82rem', margin: '0.3rem 0 0' }}>
            Mínimo {PASSWORD_MIN_LENGTH} caracteres. Mejor una frase larga que algo corto y
            raro.
          </p>
        </div>
        <Notice kind="error">{error}</Notice>
        <button type="submit" disabled={busy}>
          {busy ? 'Creando…' : 'Crear cuenta'}
        </button>
      </form>
      <p className="muted">
        ¿Ya tenés cuenta? <Link to="/login">Entrá</Link>.
      </p>
    </div>
  )
}
