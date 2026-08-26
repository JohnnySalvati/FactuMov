import { useCallback, useState, type FormEvent } from 'react'

import { ApiError, api } from '../api/client'
import {
  CONDICION_IVA_LABELS,
  CondicionIva,
  type DelegationStatus,
  type FiscalIdentity,
} from '../api/types'
import { Notice } from '../components/Notice'
import { useResource } from '../hooks/useResource'

/** Consumidor final no puede emitir, y el backend lo rechaza con un 422. Se saca de la lista
 *  para no ofrecer una opción que siempre falla. */
const EMISOR_CONDICIONES = [
  CondicionIva.INSCRIPTO,
  CondicionIva.MONOTRIBUTO,
  CondicionIva.EXENTO,
] as const

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

export function FiscalIdentitiesPage() {
  const fetcher = useCallback(() => api.get<FiscalIdentity[]>('/fiscal-identities'), [])
  const { data, error, loading, reload } = useResource(fetcher)

  return (
    <div className="page">
      <h1>Identidades fiscales</h1>
      <p className="page-intro">
        Los CUIT desde los que emitís. Cada uno necesita que lo autorices en ARCA antes de
        poder facturar.
      </p>

      <NewFiscalIdentityForm onCreated={reload} />

      <div className="card">
        <h2>Tus identidades</h2>
        <Notice kind="error">{error}</Notice>
        {loading && <p className="muted">Cargando…</p>}
        {data && data.length === 0 && (
          <p className="empty">Todavía no cargaste ninguna.</p>
        )}
        {data && data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>CUIT</th>
                <th>Condición IVA</th>
                <th>Delegación</th>
              </tr>
            </thead>
            <tbody>
              {data.map((identity) => (
                <tr key={identity.id}>
                  <td>{identity.name}</td>
                  <td className="mono">{identity.tax_id}</td>
                  <td>{CONDICION_IVA_LABELS[identity.condicion_iva]}</td>
                  <td>
                    <DelegationCell identity={identity} onVerified={reload} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/**
 * El estado de la delegación y el botón para verificarla.
 *
 * `delegation_verified_at` dice "esto era verdad en esta fecha", no "esto es verdad": ARCA
 * permite revocar la delegación sin avisarnos. Por eso el botón sigue estando aunque ya esté
 * verificada, y la fecha se muestra siempre.
 */
function DelegationCell({
  identity,
  onVerified,
}: {
  identity: FiscalIdentity
  onVerified: () => void
}) {
  const [status, setStatus] = useState<DelegationStatus>()
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  async function verify() {
    setBusy(true)
    setError(undefined)
    try {
      const result = await api.post<DelegationStatus>(
        `/fiscal-identities/${identity.id}/verify-delegation`,
      )
      setStatus(result)
      // Solo hay algo nuevo que recargar cuando dio que sí: es el único caso en que el
      // backend escribió el timestamp.
      if (result.granted) onVerified()
    } catch (caught) {
      // El 502 es "no se pudo preguntar", que no es lo mismo que "no estás delegado" — eso
      // último llega como un 200 con `granted: false`. Mezclarlos haría que un ARCA caído se
      // vea como una delegación faltante, y el usuario iría a otorgar una que ya tiene.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo verificar.')
    } finally {
      setBusy(false)
    }
  }

  const verified = identity.delegation_verified_at

  return (
    <div className="stack" style={{ gap: '0.4rem' }}>
      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
        {verified ? (
          <span className="badge ok">Verificada</span>
        ) : (
          <span className="badge pending">Sin verificar</span>
        )}
        <button className="link" onClick={verify} disabled={busy}>
          {busy ? 'Consultando ARCA…' : 'Verificar'}
        </button>
      </div>

      {verified && <span className="muted">Última: {formatDate(verified)}</span>}

      {error && <Notice kind="error">{error}</Notice>}

      {status && !status.granted && (
        <Notice kind="warn">
          ARCA todavía no nos autorizó para este CUIT. Entrá a autorizarnos:
          <ol>
            <li>
              Entrá a <strong>arca.gob.ar</strong> con tu Clave Fiscal.
            </li>
            <li>Abrí «Administrador de Relaciones de Clave Fiscal».</li>
            <li>Elegí «Nueva Relación» y buscá Facturación Electrónica (WSFE).</li>
            <li>
              Como representante indicá el CUIT{' '}
              <strong className="mono">{status.delegate_tax_id}</strong> (FactuMov).
            </li>
            <li>Confirmá y volvé a apretar «Verificar».</li>
          </ol>
        </Notice>
      )}

      {status?.granted && <Notice kind="ok">Listo, ya podés emitir con este CUIT.</Notice>}
    </div>
  )
}

function NewFiscalIdentityForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState('')
  const [taxId, setTaxId] = useState('')
  const [condicionIva, setCondicionIva] = useState<CondicionIva>(CondicionIva.INSCRIPTO)
  const [address, setAddress] = useState('')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    try {
      await api.post<FiscalIdentity>('/fiscal-identities', {
        name,
        tax_id: taxId.replace(/\D/g, ''),
        condicion_iva: condicionIva,
        // Cadena vacía y "sin dato" no son lo mismo para una columna que admite NULL: mandar
        // `""` guardaría un domicilio vacío en vez de ninguno.
        address: address.trim() || null,
      })
      setName('')
      setTaxId('')
      setAddress('')
      onCreated()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo guardar.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <h2>Agregar una identidad fiscal</h2>
      <div className="row">
        <div>
          <label htmlFor="fi-name">Nombre o razón social</label>
          <input id="fi-name" required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="fi-tax-id">CUIT</label>
          {/* Los guiones se limpian al mandar: la columna guarda once dígitos, y hacer que el
              usuario los tipee sin guiones es pedirle que se adapte al esquema. */}
          <input
            id="fi-tax-id"
            required
            inputMode="numeric"
            placeholder="20-12345678-9"
            value={taxId}
            onChange={(e) => setTaxId(e.target.value)}
          />
        </div>
      </div>
      <div className="row">
        <div>
          <label htmlFor="fi-condicion">Condición frente al IVA</label>
          <select
            id="fi-condicion"
            value={condicionIva}
            onChange={(e) => setCondicionIva(Number(e.target.value) as CondicionIva)}
          >
            {EMISOR_CONDICIONES.map((value) => (
              <option key={value} value={value}>
                {CONDICION_IVA_LABELS[value]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="fi-address">Domicilio (opcional)</label>
          <input id="fi-address" value={address} onChange={(e) => setAddress(e.target.value)} />
        </div>
        <button type="submit" disabled={busy}>
          {busy ? 'Guardando…' : 'Agregar'}
        </button>
      </div>
      <Notice kind="error">{error}</Notice>
    </form>
  )
}
