import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'

import { ApiError, api } from '../api/client'
import type { MessageResponse } from '../api/types'
import { Notice } from '../components/Notice'

/**
 * "Olvidé mi contraseña": pide la dirección y dispara el mail con el link.
 *
 * Gemela de `RegisterPage`, y por el mismo motivo de fondo: el backend contesta 202 con el
 * mismo cuerpo exista o no la cuenta, para no delatar qué direcciones están registradas. Esta
 * pantalla tiene que respetarlo — dice que se mandó un mail, sin afirmar que había una cuenta.
 */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string>()
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      await api.post<MessageResponse>('/auth/forgot-password', { email })
      setDone(true)
    } catch (caught) {
      // El 503 de "no pudimos mandarte el mail" llega acá con su texto, que ya explica que
      // es un problema nuestro y no de la cuenta. Repetirlo tal cual es lo correcto: antes
      // ese caso era un 202 alegre y el usuario esperaba un mail que no iba a llegar nunca.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo pedir el link.')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <div className="centered">
        <h1>Revisá tu casilla</h1>
        <div className="card">
          <Notice kind="ok">
            Si hay una cuenta con <strong>{email}</strong>, te mandamos un mail con un link
            para elegir una contraseña nueva. El link vence en una hora.
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
      <h1>Olvidé mi contraseña</h1>
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
          <p className="muted" style={{ fontSize: '0.82rem', margin: '0.3rem 0 0' }}>
            Te mandamos un link para elegir una contraseña nueva.
          </p>
        </div>
        <Notice kind="error">{error}</Notice>
        <button type="submit" disabled={busy}>
          {busy ? 'Mandando…' : 'Mandarme el link'}
        </button>
      </form>
      <p className="muted">
        ¿Te acordaste? <Link to="/login">Entrá</Link>.
      </p>
    </div>
  )
}
