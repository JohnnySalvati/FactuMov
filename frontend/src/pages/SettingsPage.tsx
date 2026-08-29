import { useCallback, useState } from 'react'
import { Link } from 'react-router'

import { ApiError, api } from '../api/client'
import type {
  Balance360RegisterPendingResult,
  Balance360Settings,
} from '../api/types'
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
 * El campo del token está siempre vacío al abrir, incluso con la cuenta conectada. No es un
 * descuido: el token no vuelve nunca del backend —lo único que vuelve es su pista— así que
 * mostrarlo sería mostrar un valor falso. Lo que la pantalla dice es cuál está guardado.
 */
export function SettingsPage() {
  const fetcher = useCallback(() => api.get<Balance360Settings>('/balance360'), [])
  const settings = useResource(fetcher)
  const data = settings.data
  const connection = data?.connection ?? null

  const [baseUrl, setBaseUrl] = useState('')
  const [token, setToken] = useState('')
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
        api_token: token,
        auto_register: autoRegister,
      })
      setToken('')
      setOk('Conectado. Balance360 aceptó el token.')
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
      setToken('')
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
                enteremos.
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
              Token de API
              {/* `type="password"` para que no quede a la vista de nadie que mire la pantalla
                  mientras se pega. Es un secreto que da acceso de escritura a la contabilidad. */}
              <input
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder={connection !== null ? 'Pegá uno nuevo para reemplazarlo' : 'b360_…'}
                autoComplete="off"
                required
              />
            </label>
            <p className="totals-note" style={{ margin: 0 }}>
              El token se genera en el servidor de Balance360, una sola vez por integración.
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
              {saving ? 'Probando el token…' : connection !== null ? 'Reemplazar' : 'Conectar'}
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
