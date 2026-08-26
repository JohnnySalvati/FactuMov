import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  CONDICION_IVA_LABELS,
  CondicionIva,
  type DelegationStatus,
  type FiscalIdentity,
} from '../api/types'
import { DeleteButton } from '../components/DeleteButton'
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

  /**
   * Cuál se está editando, en la URL y no en el estado del componente.
   *
   * Es lo que deja que el "mantener apretado" sobre la identidad fiscal de un modelo aterrice
   * directo en su formulario: la pantalla que abre el gesto es `/identidades?editar=<id>`, o
   * sea un link como cualquier otro. Con el id guardado en `useState` habría que inventar un
   * canal aparte para decirle a esta pantalla con qué fila arrancar.
   */
  const [params, setParams] = useSearchParams()
  const editingId = params.get('editar')
  const editing = data?.find((identity) => identity.id === editingId)

  // Al llegar desde el gesto, el formulario está arriba y la lista puede ser larga.
  useEffect(() => {
    if (editingId !== null) window.scrollTo({ top: 0 })
  }, [editingId])

  function stopEditing() {
    setParams({}, { replace: true })
  }

  return (
    <div className="page">
      <h1>Identidades fiscales</h1>
      <p className="page-intro">
        Los CUIT desde los que emitís. Cada uno necesita que lo autorices en ARCA antes de
        poder facturar.
      </p>

      <FiscalIdentityForm
        // El `key` hace que el formulario se remonte al cambiar de fila, y así toma los
        // valores iniciales de la que se está editando. La alternativa —un efecto que copie
        // la prop al estado— es el mismo resultado con un render de más y una forma conocida
        // de quedarse pisando lo que el usuario ya tipeó.
        key={editing?.id ?? 'nueva'}
        editing={editing}
        onSaved={() => {
          stopEditing()
          reload()
        }}
        onCancel={stopEditing}
      />

      <div className="card">
        <h2>Tus identidades</h2>
        <Notice kind="error">{error}</Notice>
        {loading && <p className="muted">Cargando…</p>}
        {data && data.length === 0 && <p className="empty">Todavía no cargaste ninguna.</p>}
        {data && data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>CUIT</th>
                <th>Condición IVA</th>
                <th>Delegación</th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {data.map((identity) => (
                <tr key={identity.id} className={identity.id === editingId ? 'editing' : ''}>
                  {/* `data-label` es lo que la tarjeta de celular muestra como nombre del
                      dato: en angosto no hay encabezado de columna a la vista. */}
                  <td data-label="Nombre">{identity.name}</td>
                  <td data-label="CUIT" className="mono">
                    {identity.tax_id}
                  </td>
                  <td data-label="Condición IVA">
                    {CONDICION_IVA_LABELS[identity.condicion_iva]}
                  </td>
                  <td data-label="Delegación" className="block">
                    <DelegationCell identity={identity} onVerified={reload} />
                  </td>
                  <td className="actions">
                    <button
                      className="icon"
                      title={`Editar ${identity.name}`}
                      aria-label={`Editar ${identity.name}`}
                      onClick={() => setParams({ editar: identity.id })}
                    >
                      ✏️
                    </button>
                    <DeleteButton
                      title={`Eliminar ${identity.name}`}
                      onDelete={async () => {
                        await api.delete<void>(`/fiscal-identities/${identity.id}`)
                        if (identity.id === editingId) stopEditing()
                        reload()
                      }}
                    />
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

/**
 * Alta y edición en el mismo formulario.
 *
 * Son los mismos seis campos y las mismas reglas: separarlos en dos componentes sería copiar
 * el formulario entero para cambiar el verbo HTTP y el texto del botón, y garantizar que
 * dentro de tres meses uno de los dos tenga un campo que el otro no.
 */
function FiscalIdentityForm({
  editing,
  onSaved,
  onCancel,
}: {
  editing?: FiscalIdentity
  onSaved: () => void
  onCancel: () => void
}) {
  const [name, setName] = useState(editing?.name ?? '')
  const [taxId, setTaxId] = useState(editing?.tax_id ?? '')
  const [condicionIva, setCondicionIva] = useState<CondicionIva>(
    editing?.condicion_iva ?? CondicionIva.INSCRIPTO,
  )
  const [address, setAddress] = useState(editing?.address ?? '')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    const body = {
      name,
      tax_id: taxId.replace(/\D/g, ''),
      condicion_iva: condicionIva,
      // Cadena vacía y "sin dato" no son lo mismo para una columna que admite NULL: mandar
      // `""` guardaría un domicilio vacío en vez de ninguno.
      address: address.trim() || null,
    }
    try {
      if (editing) {
        await api.patch<FiscalIdentity>(`/fiscal-identities/${editing.id}`, body)
      } else {
        await api.post<FiscalIdentity>('/fiscal-identities', body)
        setName('')
        setTaxId('')
        setAddress('')
      }
      onSaved()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo guardar.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <h2>{editing ? `Editar ${editing.name}` : 'Agregar una identidad fiscal'}</h2>
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
          {busy ? 'Guardando…' : editing ? 'Guardar cambios' : 'Agregar'}
        </button>
        {editing && (
          <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
            Cancelar
          </button>
        )}
      </div>
      <Notice kind="error">{error}</Notice>
    </form>
  )
}
