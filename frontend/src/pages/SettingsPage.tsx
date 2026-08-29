import { useCallback, useState } from 'react'
import { Link } from 'react-router'

import { ApiError, api } from '../api/client'
import type {
  Balance360RegisterPendingResult,
  Balance360Settings,
} from '../api/types'
import { useAuth } from '../auth/useAuth'
import { Notice } from '../components/Notice'
import { formatDate } from '../format'
import { useResource } from '../hooks/useResource'

/**
 * Los ajustes de la cuenta. Hoy tienen una sola sección: la conexión con Balance360.
 *
 * Es una pantalla de ajustes y no "la pantalla de Balance360" aunque hoy sean lo mismo, y la
 * diferencia está en el acceso: se llega por un engranaje en la barra, que es donde cualquiera
 * busca lo que es de la cuenta y no de los datos. Un ítem que dijera "Balance360" obligaría a
 * saber qué es antes de entrar, y a mover todo el día que aparezca el segundo ajuste.
 *
 * **Una sola conexión por usuario y ningún selector de CUIT.** Del otro lado el token *es* un
 * usuario: Balance360 deduce a qué entidad va cada comprobante buscando el CUIT del emisor
 * entre las entidades de las que ese usuario es miembro. Así que un token cubre todas las
 * identidades fiscales, y pedir una conexión por CUIT sería pedir N veces la misma credencial
 * para que el ruteo lo siga haciendo el CUIT igual.
 *
 * **Se piden mail y contraseña de Balance360, y el token no se ve nunca.** Antes había que
 * pegar uno, que alguien tenía que emitir por ssh contra el servidor de la otra app: conectar
 * dependía de quien administra la VM, y el secreto llegaba por chat o por mail. Ahora el
 * backend lo pide por el usuario y guarda lo que vuelve.
 *
 * La contraseña vive en el estado de este componente hasta que se manda, y se borra apenas
 * contesta el backend. No se guarda de ningún lado —ni acá, ni en la base— y por eso el
 * formulario nunca puede mostrarla de vuelta: lo que la pantalla dice es qué token quedó
 * puesto, con los últimos cuatro caracteres.
 */
export function SettingsPage() {
  const fetcher = useCallback(() => api.get<Balance360Settings>('/balance360'), [])
  const settings = useResource(fetcher)
  const data = settings.data
  const connection = data?.connection ?? null

  const { user } = useAuth()

  const [baseUrl, setBaseUrl] = useState('')
  // El mail arranca con el de la cuenta de FactuMov porque en la práctica suele ser el mismo,
  // pero es un valor por defecto y no un supuesto: son dos aplicaciones y dos cuentas, así que
  // el campo se ve, se puede cambiar, y el texto de abajo aclara de cuál se trata.
  const [email, setEmail] = useState(user?.email ?? '')
  const [password, setPassword] = useState('')
  const [autoRegisterChoice, setAutoRegisterChoice] = useState<boolean>()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()
  const [ok, setOk] = useState<string>()

  // La dirección arranca con la que ya está guardada, si la hay; el token nunca. Reemplazar
  // el token es la operación más frecuente de esta pantalla —es lo que hay que hacer cuando
  // se lo revoca del otro lado— y tener que volver a tipear la URL para eso sería fricción
  // gratis. El `??` no alcanza: `baseUrl` es estado y no se recalcula cuando llega la carga.
  const url = baseUrl || connection?.base_url || ''
  // Lo mismo con la casilla: mientras el usuario no la toque, vale lo que está guardado.
  const autoRegister = autoRegisterChoice ?? connection?.auto_register ?? true

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    setError(undefined)
    setOk(undefined)
    try {
      await api.put<Balance360Settings>('/balance360', {
        base_url: url,
        email,
        password,
        auto_register: autoRegister,
      })
      // Lo primero que pasa cuando sale bien: la contraseña se va del estado. No hace falta
      // más —el token ya está guardado del otro lado del request— y dejarla puesta la
      // expondría a cualquier cosa que después lea este componente.
      setPassword('')
      setOk('Conectado. Balance360 emitió un token para FactuMov.')
      settings.reload()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo guardar la conexión.')
    } finally {
      setSaving(false)
    }
  }

  async function disconnect() {
    setError(undefined)
    setOk(undefined)
    try {
      await api.delete<void>('/balance360')
      setPassword('')
      setBaseUrl('')
      settings.reload()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo desconectar.')
    }
  }

  async function registerPending() {
    setError(undefined)
    setOk(undefined)
    try {
      const result = await api.post<Balance360RegisterPendingResult>(
        '/balance360/register-pending',
        undefined,
      )
      setOk(
        result.attempted === 0
          ? 'No había facturas pendientes de registrar.'
          : `Se registraron ${result.registered} de ${result.attempted}.` +
              (result.failed > 0 ? ' Las que fallaron dicen por qué en su pantalla.' : ''),
      )
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo registrar.')
    }
  }

  return (
    <div className="page">
      <h1>Ajustes</h1>
      <h2>Balance360</h2>
      <p className="muted">
        Con la cuenta conectada, cada factura que emitas acá queda cargada en Balance360 como
        comprobante <strong>impago</strong>: el cobro se registra allá cuando ocurre, que es
        otro hecho y con otra fecha.
      </p>

      <Notice kind="error">{settings.error}</Notice>
      {settings.loading && data === undefined && <p className="muted">Cargando…</p>}

      {data !== undefined && !data.available && (
        <Notice kind="warn">
          Este servidor no tiene configurada la integración: le falta la clave con la que se
          cifran los tokens. Todo lo demás de FactuMov anda igual.
        </Notice>
      )}

      {data !== undefined && data.available && (
        <>
          {connection !== null && (
            <div className="card">
              <dl className="summary">
                <div>
                  <dt>Conectado a</dt>
                  <dd className="mono">{connection.base_url}</dd>
                </div>
                <div>
                  <dt>Token</dt>
                  {/* La pista y no el token: lo único que hace falta es poder distinguir cuál
                      está guardado de uno nuevo. */}
                  <dd className="mono">…{connection.token_hint}</dd>
                </div>
                <div>
                  <dt>Última vez que anduvo</dt>
                  <dd>
                    {connection.verified_at !== null
                      ? formatDate(connection.verified_at.slice(0, 10))
                      : 'nunca'}
                  </dd>
                </div>
              </dl>
              {/* "Anduvo", no "es válido": el token se puede revocar del otro lado sin que nos
                  enteremos, así que lo único cierto es que en esa fecha funcionaba. */}
              <p className="totals-note">
                Lo pueden haber revocado en Balance360 después de esa fecha sin que nos
                enteremos. Si eso pasó, volvé a conectar acá abajo y se emite uno nuevo.
              </p>
            </div>
          )}

          <form className="card stack" onSubmit={save}>
            <label>
              Dirección de Balance360
              <input
                type="url"
                value={url}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://balance360.example"
                required
              />
            </label>

            <label>
              Tu mail en Balance360
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="vos@ejemplo.com"
                autoComplete="off"
                required
              />
            </label>

            <label>
              Tu contraseña de Balance360
              {/* `autoComplete="off"`: es la contraseña de **otra** app, y dejar que el
                  navegador la guarde asociada a este sitio la volvería a ofrecer en el login
                  de FactuMov, que es donde no va. */}
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={connection !== null ? 'Para reemplazar el token' : ''}
                autoComplete="off"
                required
              />
            </label>
            <p className="totals-note" style={{ margin: 0 }}>
              Es la cuenta con la que entrás a Balance360, que puede no ser la de acá. La
              contraseña se usa una sola vez para pedir un token y <strong>no se guarda</strong>:
              lo que queda guardado es el token, que podés revocar en Balance360 cuando quieras.
            </p>

            <label className="checkbox">
              <input
                type="checkbox"
                checked={autoRegister}
                onChange={(event) => setAutoRegisterChoice(event.target.checked)}
              />
              Registrar automáticamente al emitir
            </label>

            <button type="submit" disabled={saving}>
              {saving ? 'Conectando…' : connection !== null ? 'Reemplazar' : 'Conectar'}
            </button>

            <Notice kind="error">{error}</Notice>
            <Notice kind="ok">{ok}</Notice>
          </form>

          {connection !== null && (
            <div className="card stack">
              <button className="secondary" onClick={registerPending}>
                Registrar las que quedaron pendientes
              </button>
              {/* Solo las que entraron al circuito y no llegaron: las emitidas antes de
                  conectar la cuenta no son "pendientes", nunca tuvieron que registrarse. */}
              <p className="totals-note" style={{ margin: 0 }}>
                Reintenta las facturas que se emitieron con la cuenta conectada y no llegaron.
                Las de antes de conectarla se registran una por una desde{' '}
                <Link to="/facturas">su pantalla</Link>.
              </p>
              <button className="secondary" onClick={disconnect}>
                Desconectar
              </button>
              <p className="totals-note" style={{ margin: 0 }}>
                Desconectar no borra nada de lo que ya se registró en Balance360.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
