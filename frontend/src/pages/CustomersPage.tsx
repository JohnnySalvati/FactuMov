import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  CONDICION_IVA_LABELS,
  CondicionIva,
  DOC_TYPE_LABELS,
  DocType,
  type Customer,
  type TaxpayerLookup,
} from '../api/types'
import { DeleteButton } from '../components/DeleteButton'
import { Notice } from '../components/Notice'
import { useResource } from '../hooks/useResource'

export function CustomersPage() {
  const fetcher = useCallback(() => api.get<Customer[]>('/customers'), [])
  const { data, error, loading, reload } = useResource(fetcher)

  // El id a editar viaja en la URL — ver el comentario largo en `FiscalIdentitiesPage`: es lo
  // que hace que el "mantener apretado" sobre el cliente de un modelo sea un link común.
  const [params, setParams] = useSearchParams()
  const editingId = params.get('editar')
  const editing = data?.find((customer) => customer.id === editingId)

  useEffect(() => {
    if (editingId !== null) window.scrollTo({ top: 0 })
  }, [editingId])

  function stopEditing() {
    setParams({}, { replace: true })
  }

  return (
    <div className="page">
      <h1>Clientes</h1>
      <p className="page-intro">
        A quiénes les facturás. Si tenés el CUIT, traelo del padrón de ARCA y se completa
        solo.
      </p>

      <CustomerForm
        key={editing?.id ?? 'nuevo'}
        editing={editing}
        onSaved={() => {
          stopEditing()
          reload()
        }}
        onCancel={stopEditing}
      />

      <div className="card">
        <h2>Tu cartera</h2>
        <Notice kind="error">{error}</Notice>
        {loading && <p className="muted">Cargando…</p>}
        {data && data.length === 0 && <p className="empty">Todavía no cargaste ninguno.</p>}
        {data && data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Documento</th>
                <th>Condición IVA</th>
                <th>Domicilio</th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {data.map((customer) => (
                <tr key={customer.id} className={customer.id === editingId ? 'editing' : ''}>
                  <td data-label="Nombre">{customer.name}</td>
                  <td data-label="Documento" className="mono">
                    {DOC_TYPE_LABELS[customer.doc_type]} {customer.doc_number}
                  </td>
                  <td data-label="Condición IVA">
                    {CONDICION_IVA_LABELS[customer.condicion_iva]}
                  </td>
                  <td data-label="Domicilio" className="muted">
                    {customer.address ?? '—'}
                  </td>
                  <td className="actions">
                    <button
                      className="icon"
                      title={`Editar ${customer.name}`}
                      aria-label={`Editar ${customer.name}`}
                      onClick={() => setParams({ editar: customer.id })}
                    >
                      ✏️
                    </button>
                    <DeleteButton
                      title={`Eliminar ${customer.name}`}
                      onDelete={async () => {
                        await api.delete<void>(`/customers/${customer.id}`)
                        if (customer.id === editingId) stopEditing()
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

/** Alta y edición en el mismo formulario — ver `FiscalIdentityForm`. */
function CustomerForm({
  editing,
  onSaved,
  onCancel,
}: {
  editing?: Customer
  onSaved: () => void
  onCancel: () => void
}) {
  const [docType, setDocType] = useState<DocType>(editing?.doc_type ?? DocType.CUIT)
  const [docNumber, setDocNumber] = useState(editing?.doc_number ?? '')
  const [name, setName] = useState(editing?.name ?? '')
  const [condicionIva, setCondicionIva] = useState<CondicionIva>(
    editing?.condicion_iva ?? CondicionIva.INSCRIPTO,
  )
  const [address, setAddress] = useState(editing?.address ?? '')
  const [email, setEmail] = useState(editing?.email ?? '')

  const [error, setError] = useState<string>()
  const [lookupNote, setLookupNote] = useState<string>()
  const [looking, setLooking] = useState(false)
  const [busy, setBusy] = useState(false)

  /**
   * Trae los datos del padrón y **prellena el formulario**, sin guardar nada.
   *
   * Que quede editable es el punto: el backend devuelve una propuesta, no un alta, y el
   * usuario tiene que poder corregirla antes de confirmar. Si esto guardara directo,
   * consultar dos veces el mismo CUIT dejaría dos clientes.
   */
  async function lookup() {
    const digits = docNumber.replace(/\D/g, '')
    setLooking(true)
    setError(undefined)
    setLookupNote(undefined)
    try {
      const taxpayer = await api.get<TaxpayerLookup>(`/customers/lookup/${digits}`)
      setDocType(taxpayer.doc_type)
      setDocNumber(taxpayer.doc_number)
      setName(taxpayer.name)
      setCondicionIva(taxpayer.condicion_iva)
      setAddress(taxpayer.address ?? '')
      setLookupNote(
        taxpayer.active
          ? 'Datos traídos del padrón. Revisalos antes de guardar.'
          : 'Ojo: en el padrón este CUIT figura con la clave inactiva.',
      )
    } catch (caught) {
      // 404 es "ARCA no tiene ese CUIT" y 502 es "no se pudo preguntar". Ninguno de los dos
      // impide cargar el cliente a mano, así que son avisos y no bloqueos.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo consultar el padrón.')
    } finally {
      setLooking(false)
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    const body = {
      name,
      condicion_iva: condicionIva,
      doc_type: docType,
      doc_number: docNumber.replace(/\D/g, ''),
      address: address.trim() || null,
      email: email.trim() || null,
    }
    try {
      if (editing) {
        await api.patch<Customer>(`/customers/${editing.id}`, body)
      } else {
        await api.post<Customer>('/customers', body)
        setDocNumber('')
        setName('')
        setAddress('')
        setEmail('')
        setLookupNote(undefined)
      }
      onSaved()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo guardar.')
    } finally {
      setBusy(false)
    }
  }

  // El padrón se consulta por CUIT y solo devuelve CUIT: con un DNI no hay nada que traer.
  const canLookup = docType === DocType.CUIT && docNumber.replace(/\D/g, '').length === 11

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <h2>{editing ? `Editar ${editing.name}` : 'Agregar un cliente'}</h2>

      <div className="row">
        <div className="narrow">
          <label htmlFor="c-doc-type">Documento</label>
          <select
            id="c-doc-type"
            value={docType}
            onChange={(e) => setDocType(Number(e.target.value) as DocType)}
          >
            {Object.entries(DOC_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="c-doc-number">Número</label>
          <input
            id="c-doc-number"
            required
            inputMode="numeric"
            value={docNumber}
            onChange={(e) => setDocNumber(e.target.value)}
          />
        </div>
        <button
          type="button"
          className="secondary"
          onClick={lookup}
          disabled={!canLookup || looking}
          title={
            docType === DocType.CUIT
              ? 'Trae nombre, domicilio y condición IVA del padrón'
              : 'El padrón solo se consulta por CUIT'
          }
        >
          {looking ? 'Consultando…' : 'Traer del padrón'}
        </button>
      </div>

      {lookupNote && (
        <Notice kind={lookupNote.startsWith('Ojo') ? 'warn' : 'ok'}>{lookupNote}</Notice>
      )}

      <div className="row">
        <div>
          <label htmlFor="c-name">Nombre o razón social</label>
          <input id="c-name" required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="c-condicion">Condición frente al IVA</label>
          <select
            id="c-condicion"
            value={condicionIva}
            onChange={(e) => setCondicionIva(Number(e.target.value) as CondicionIva)}
          >
            {Object.entries(CONDICION_IVA_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="row">
        <div>
          <label htmlFor="c-address">Domicilio (opcional)</label>
          <input id="c-address" value={address} onChange={(e) => setAddress(e.target.value)} />
        </div>
        <div>
          <label htmlFor="c-email">Email (opcional)</label>
          <input
            id="c-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
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
