import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import { Notice } from '../components/Notice'
import { useAuth } from '../auth/useAuth'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      await login(email, password)
      // `replace` y no `push`: sin eso, el "atrás" del navegador vuelve al login estando ya
      // logueado, que es una pantalla sin sentido.
      navigate('/identidades', { replace: true })
    } catch (caught) {
      // El backend contesta el **mismo** 401 para email desconocido, contraseña incorrecta y
      // cuenta sin confirmar, a propósito: distinguirlos le diría a un atacante si esa
      // dirección existe. Repetir su texto tal cual es lo correcto — inventar acá un "revisá
      // tu casilla" reabriría el oráculo que el backend cierra.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo iniciar sesión.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="centered">
      <h1>Entrar a FactuMov</h1>
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
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <Notice kind="error">{error}</Notice>
        <button type="submit" disabled={busy}>
          {busy ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
      <p className="muted">
        ¿No tenés cuenta? <Link to="/registro">Creá una</Link>.
      </p>
    </div>
  )
}
