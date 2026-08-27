import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  CONDICION_IVA_LABELS,
  CondicionIva,
  DOC_TYPE_LABELS,
  DocType,
  type Customer,
  type TaxpayerLookup,
} from '../api/types'
import { Notice } from '../components/Notice'

/**
 * Un cliente: `/clientes/nuevo` para el alta y `/clientes/:id` para la edición.
 *
 * Misma forma que `FiscalIdentityPage` — ver ahí por qué el alta y la edición comparten
 * componente y por qué el id va en el path.
 */
export function CustomerPage() {
  const { id } = useParams()
  return <CustomerScreen key={id ?? 'nuevo'} id={id} />
}

function CustomerScreen({ id }: { id?: string }) {
  const navigate = useNavigate()

  const [customer, setCustomer] = useState<Customer | null>(null)
  const [loading, setLoading] = useState(id !== undefined)
  const [loadError, setLoadError] = useState<string>()

  useEffect(() => {
    if (id === undefined) return
    let cancelled = false
    api
      .get<Customer>(`/customers/${id}`)
      .then((found) => {
        if (cancelled) return
        setCustomer(found)
        setLoading(false)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setLoadError(caught instanceof ApiError ? caught.detail : 'No se pudo cargar el cliente.')
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id])

  return (
    <div className="page">
      <Link className="back" to="/clientes">
        &larr; Clientes
      </Link>
      <h1>{customer?.name ?? 'Nuevo cliente'}</h1>

      <Notice kind="error">{loadError}</Notice>
      {loading && <p className="muted">Cargando…</p>}

      {!loading && loadError === undefined && (
        <CustomerForm
          editing={customer ?? undefined}
          onCreated={() => navigate('/clientes')}
          onUpdated={setCustomer}
        />
      )}
    </div>
  )
}

function CustomerForm({
  editing,
  onCreated,
  onUpdated,
}: {
  editing?: Customer
  onCreated: () => void
  onUpdated: (customer: Customer) => void
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
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  function edited() {
    setSaved(false)
  }

  /**
   * Trae los datos del padrón y **prellena el formulario**, sin guardar nada.
   *
   * Que quede editable es el punto: el backend devuelve una propuesta, no un alta, y el usuario
   * tiene que poder corregirla antes de confirmar. Si esto guardara directo, consultar dos veces
   * el mismo CUIT dejaría dos clientes.
   */
  async function lookup() {
    const digits = docNumber.replace(/\D/g, '')
    setLooking(true)
    setError(undefined)
    setLookupNote(undefined)
    setSaved(false)
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
    setSaved(false)
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
        onUpdated(await api.patch<Customer>(`/customers/${editing.id}`, body))
        setSaved(true)
      } else {
        await api.post<Customer>('/customers', body)
        onCreated()
      }
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
      <div className="row">
        <div className="narrow">
          <label htmlFor="c-doc-type">Documento</label>
          <select
            id="c-doc-type"
            value={docType}
            onChange={(event) => {
              edited()
              setDocType(Number(event.target.value) as DocType)
            }}
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
            onChange={(event) => {
              edited()
              setDocNumber(event.target.value)
            }}
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

      <div>
        <label htmlFor="c-name">Nombre o razón social</label>
        <input
          id="c-name"
          required
          value={name}
          onChange={(event) => {
            edited()
            setName(event.target.value)
          }}
        />
      </div>

      <div className="row">
        <div>
          <label htmlFor="c-condicion">Condición frente al IVA</label>
          <select
            id="c-condicion"
            value={condicionIva}
            onChange={(event) => {
              edited()
              setCondicionIva(Number(event.target.value) as CondicionIva)
            }}
          >
            {Object.entries(CONDICION_IVA_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="c-email">Email (opcional)</label>
          <input
            id="c-email"
            type="email"
            value={email}
            onChange={(event) => {
              edited()
              setEmail(event.target.value)
            }}
          />
        </div>
      </div>

      <div>
        <label htmlFor="c-address">Domicilio (opcional)</label>
        <input
          id="c-address"
          value={address}
          onChange={(event) => {
            edited()
            setAddress(event.target.value)
          }}
        />
      </div>

      <Notice kind="error">{error}</Notice>
      {saved && <Notice kind="ok">Guardado.</Notice>}

      <button type="submit" disabled={busy}>
        {busy ? 'Guardando…' : editing ? 'Guardar cambios' : 'Crear el cliente'}
      </button>
    </form>
  )
}
