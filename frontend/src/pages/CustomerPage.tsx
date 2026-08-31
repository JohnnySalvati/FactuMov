import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  CONDICION_IVA_LABELS,
  CondicionIva,
  DOC_TYPE_LABELS,
  DocType,
  isCuit,
  type Customer,
  type TaxpayerLookup,
} from '../api/types'
import { Notice } from '../components/Notice'
import { useRegisterUnsavedChanges } from '../unsaved/hooks'

/**
 * Los campos tal como viajan al backend, ya normalizados. Es lo que se manda al guardar y —el
 * mismo objeto— lo que se compara contra el cliente guardado para saber si hay cambios: así un
 * "Foo@X.com " que el servidor devuelve como "foo@x.com" no queda marcado como cambio después
 * de guardar.
 */
function toBody(fields: {
  docType: DocType
  docNumber: string
  name: string
  condicionIva: CondicionIva
  address: string
  email: string
  ccEmails: string[]
}) {
  return {
    name: fields.name.trim(),
    condicion_iva: fields.condicionIva,
    doc_type: fields.docType,
    doc_number: fields.docNumber.replace(/\D/g, ''),
    address: fields.address.trim() || null,
    email: fields.email.trim().toLowerCase() || null,
    cc_emails: cleanCcEmails(fields.ccEmails, fields.email),
  }
}

/** Minúsculas, sin espacios, sin vacíos, sin repetir y sin el destinatario principal — la
 *  misma limpieza que hace el backend, replicada acá para que la detección de cambios no vea
 *  un cambio donde el servidor no guardó ninguno. */
function cleanCcEmails(list: readonly string[], primary: string): string[] {
  const seen = new Set<string>()
  const main = primary.trim().toLowerCase()
  if (main) seen.add(main)
  const out: string[] = []
  for (const raw of list) {
    const address = raw.trim().toLowerCase()
    if (address && !seen.has(address)) {
      seen.add(address)
      out.push(address)
    }
  }
  return out
}

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
  // El CC de las facturas de este cliente. Una lista de inputs y no un campo con comas: en el
  // celular, separar direcciones con comas se escribe y se corrige mal. El tope de 5 es el
  // mismo que valida el backend.
  const [ccEmails, setCcEmails] = useState<string[]>(editing?.cc_emails ?? [])

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

  const body = toBody({ docType, docNumber, name, condicionIva, address, email, ccEmails })

  // ¿Hay algo distinto de lo guardado? Solo tiene sentido en la edición: en el alta no hay
  // contra qué comparar, y el botón "Crear el cliente" aparece igual. Se compara el payload
  // ya normalizado, así deshacer un cambio a mano —o guardar— vuelve a dar `false`.
  const savedBody = editing
    ? toBody({
        docType: editing.doc_type,
        docNumber: editing.doc_number,
        name: editing.name,
        condicionIva: editing.condicion_iva,
        address: editing.address ?? '',
        email: editing.email ?? '',
        ccEmails: editing.cc_emails,
      })
    : null
  const dirty = savedBody !== null && JSON.stringify(body) !== JSON.stringify(savedBody)

  /** Guarda y **rechaza si no se pudo**: el guard de navegación lo necesita para no dejar
   *  salir con cambios que no entraron. La edición se queda en la pantalla; el alta navega. */
  async function persist() {
    setBusy(true)
    setError(undefined)
    setSaved(false)
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
      throw caught
    } finally {
      setBusy(false)
    }
  }

  // Solo la edición registra el guard: el alta navega sola al terminar, y `/clientes/nuevo`
  // queda afuera del gesto de deslizar. `persist` cambia de identidad en cada tecla, pero el
  // hook se queda con la última.
  useRegisterUnsavedChanges(dirty, persist)

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    // El guard además del botón que no está: sin botón de submit, un `<form>` se envía igual
    // apretando Enter en un campo, y ese PATCH sin cambios dejaría "Guardado." sobre un
    // guardado que no ocurrió.
    if (editing && !dirty) return
    void persist().catch(() => {
      // El error ya quedó en pantalla; el `catch` es solo para no dejar una promesa colgada.
    })
  }

  const canLookup = isCuit(docType, docNumber.replace(/\D/g, ''))

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

      {/* Email y CC al final, juntos: son la misma pregunta —a qué casillas se le entrega la
          factura— y no un dato de identificación como el documento o la condición IVA. El CC
          va pegado abajo del email porque solo tiene sentido con el email cargado. */}
      <div className="stack">
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

        {ccEmails.map((addr, index) => (
          // key por índice: la lista tiene uno o dos renglones y quitar uno es raro. Los
          // inputs son controlados, así que el valor lo pone siempre React.
          <div className="cc-row" key={index}>
            <input
              id={`c-cc-${index}`}
              type="email"
              value={addr}
              placeholder="Con copia a…"
              aria-label={`Dirección en copia ${index + 1}`}
              onChange={(event) => {
                edited()
                setCcEmails(ccEmails.map((v, i) => (i === index ? event.target.value : v)))
              }}
            />
            <button
              type="button"
              className="icon"
              aria-label={`Quitar la dirección en copia ${index + 1}`}
              title="Quitar"
              onClick={() => {
                edited()
                setCcEmails(ccEmails.filter((_, i) => i !== index))
              }}
            >
              🗑
            </button>
          </div>
        ))}

        {ccEmails.length < 5 && (
          // `link` y no `secondary`: un botón full-width acá se confunde con "Guardar
          // cambios" justo debajo. Este es un "agregar un renglón más", no una acción del
          // formulario.
          <button
            type="button"
            className="link"
            style={{ alignSelf: 'flex-start' }}
            onClick={() => {
              edited()
              setCcEmails([...ccEmails, ''])
            }}
          >
            + Agregar dirección en copia
          </button>
        )}

        <span className="field-hint">
          Las direcciones en copia reciben cada factura que se le manda a este cliente.
        </span>
      </div>

      <Notice kind="error">{error}</Notice>
      {saved && <Notice kind="ok">Guardado.</Notice>}

      {/* En la edición el botón aparece recién cuando hay algo que guardar: un formulario
          abierto y no tocado no tiene nada que guardar, y ofrecerlo igual le pregunta al
          usuario si quiere guardar unos cambios que no hizo. Es la misma decisión que el
          editor de modelos. En el alta aparece siempre — todo lo que cargaste es "algo para
          guardar". */}
      {(!editing || dirty) && (
        <button type="submit" disabled={busy}>
          {busy ? 'Guardando…' : editing ? 'Guardar cambios' : 'Crear el cliente'}
        </button>
      )}
    </form>
  )
}
