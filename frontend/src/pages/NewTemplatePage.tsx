import { useCallback, useRef, useState, type ChangeEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  IvaAliquot,
  VoucherType,
  type Customer,
  type CustomerCreate,
  type FiscalIdentity,
  type InvoiceTemplate,
  type InvoiceTemplateDraft,
} from '../api/types'
import { Notice } from '../components/Notice'
import { TemplateEditor } from '../components/TemplateEditor'
import {
  emptyForm,
  fromDecimal,
  newLine,
  toPayload,
  validate,
  type TemplateForm,
} from '../forms/templateForm'
import { useResource } from '../hooks/useResource'

/**
 * Un modelo nuevo, por las dos puertas: importando un PDF o cargándolo a mano.
 *
 * El PDF es la puerta principal —es la funcionalidad que da nombre al proyecto— pero no puede
 * ser la única: hay un segundo layout de factura que el parser todavía no sabe leer, y un PDF
 * escaneado contesta 200 con el modelo vacío a propósito. Con una sola puerta, cualquiera de
 * esos dos casos es un callejón sin salida.
 */
export function NewTemplatePage() {
  const navigate = useNavigate()

  const identitiesFetcher = useCallback(() => api.get<FiscalIdentity[]>('/fiscal-identities'), [])
  const customersFetcher = useCallback(() => api.get<Customer[]>('/customers'), [])
  const identities = useResource(identitiesFetcher)
  const customers = useResource(customersFetcher)

  const [form, setForm] = useState<TemplateForm>()
  const [draft, setDraft] = useState<InvoiceTemplateDraft>()
  const [reading, setReading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  // El input de archivo va escondido y lo dispara un botón. El control nativo es de tamaño
  // fijo, no se puede estilar y en el celular queda como un botoncito de sistema al lado de
  // "Sin archivo seleccionado" — o sea, el objetivo más chico de una pantalla pensada para el
  // dedo. El `<input>` sigue existiendo y sigue siendo el que abre el selector.
  const fileInput = useRef<HTMLInputElement>(null)

  async function onFileChosen(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // El input se limpia siempre: sin esto, elegir el mismo archivo dos veces seguidas no
    // dispara `change` y el botón parece roto.
    event.target.value = ''
    if (file === undefined) return

    setReading(true)
    setError(undefined)
    try {
      const imported = await api.upload<InvoiceTemplateDraft>('/invoice-templates/import', file)
      setDraft(imported)
      setForm(fromDraft(imported))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo leer el archivo.')
    } finally {
      setReading(false)
    }
  }

  /** Da de alta el cliente que salió del PDF y lo deja elegido en el formulario. */
  async function createCustomerFromDraft(parsed: CustomerCreate) {
    setBusy(true)
    setError(undefined)
    try {
      const created = await api.post<Customer>('/customers', parsed)
      setForm((current) => (current ? { ...current, customer_id: created.id } : current))
      // Sin esto el picker no conoce al cliente recién creado y el campo se ve vacío aunque el
      // id ya esté puesto: la lista de opciones es la que pone el nombre en pantalla.
      customers.reload()
      setDraft((current) => (current ? { ...current, customer_id: created.id } : current))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo dar de alta el cliente.')
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    if (form === undefined) return
    const problem = validate(form)
    if (problem !== undefined) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(undefined)
    try {
      await api.post<InvoiceTemplate>('/invoice-templates', toPayload(form))
      // Vuelve a la grilla: la tarjeta nueva ahí es la confirmación de que se guardó, y es
      // además donde el usuario iba a ir igual.
      navigate('/')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo guardar.')
      setBusy(false)
    }
  }

  const noIdentities = identities.data !== undefined && identities.data.length === 0

  /**
   * El cliente que el PDF trajo y que todavía no está en la cartera, ya con la forma del alta.
   *
   * Se arma como objeto y no como un booleano `canCreateCustomer` porque un booleano no le
   * dice nada a TypeScript sobre los cuatro campos que acaba de chequear: la rama del ternario
   * sí los estrecha, y de paso queda un solo lugar donde se decide qué se manda.
   */
  const pendingCustomer: CustomerCreate | undefined =
    draft !== undefined &&
    draft.customer_id === null &&
    draft.customer.name !== null &&
    draft.customer.doc_type !== null &&
    draft.customer.doc_number !== null &&
    draft.customer.condicion_iva !== null
      ? {
          name: draft.customer.name,
          condicion_iva: draft.customer.condicion_iva,
          doc_type: draft.customer.doc_type,
          doc_number: draft.customer.doc_number,
          address: draft.customer.address,
          email: null,
        }
      : undefined

  return (
    <div className="page">
      <Link className="back" to="/">
        ← Modelos
      </Link>
      <h1>Nuevo modelo</h1>

      {noIdentities && (
        <Notice kind="warn">
          Todavía no cargaste ninguna identidad fiscal, y un modelo necesita saber desde qué
          CUIT emitís. <Link to="/identidades">Cargá la primera</Link> y volvé.
        </Notice>
      )}

      {form === undefined && (
        <div className="card stack">
          <h2>¿De dónde salen los datos?</h2>
          <p className="muted" style={{ margin: 0 }}>
            Si tenés el PDF de una factura que ya emitiste, subilo y se completa casi todo.
          </p>

          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden-file"
            onChange={onFileChosen}
          />
          <button type="button" onClick={() => fileInput.current?.click()} disabled={reading}>
            {reading ? 'Leyendo el PDF…' : '📄 Importar una factura en PDF'}
          </button>

          <button type="button" className="secondary" onClick={() => setForm(emptyForm())}>
            Empezar en blanco
          </button>

          <Notice kind="error">{error}</Notice>
        </div>
      )}

      {form !== undefined && (
        <>
          {draft !== undefined && draft.lines.length === 0 && (
            <Notice kind="warn">
              No pude leer las líneas de ese PDF. Puede ser un escaneo, o un formato de factura
              que todavía no sé leer. Cargá el detalle a mano; el resto de lo que sí salió ya
              está puesto.
            </Notice>
          )}

          {draft !== undefined &&
            draft.fiscal_identity_id === null &&
            draft.issuer_tax_id !== null && (
              <Notice kind="warn">
                El PDF lo emitió el CUIT <strong className="mono">{draft.issuer_tax_id}</strong>,
                que no está entre tus identidades fiscales.{' '}
                <Link to="/identidades">Cargalo</Link> o elegí otro más abajo.
              </Notice>
            )}

          {pendingCustomer !== undefined && (
            <Notice kind="warn">
              El cliente <strong>{pendingCustomer.name}</strong> (
              <span className="mono">{pendingCustomer.doc_number}</span>) todavía no está en tu
              cartera.{' '}
              <button
                className="link"
                onClick={() => createCustomerFromDraft(pendingCustomer)}
                disabled={busy}
              >
                Darlo de alta con estos datos
              </button>
            </Notice>
          )}

          {draft !== undefined && (
            <Notice kind="ok">
              Poné un nombre para reconocer el modelo: el PDF no lo trae, lo elegís vos.
            </Notice>
          )}

          <TemplateEditor
            value={form}
            onChange={setForm}
            fiscalIdentities={identities.data ?? []}
            customers={customers.data ?? []}
            onSubmit={save}
            submitLabel="Guardar el modelo"
            busy={busy}
            error={error}
          />
        </>
      )}
    </div>
  )
}

/**
 * Draft → formulario.
 *
 * Casi todo el draft es opcional: el endpoint contesta 200 con todo en `null` cuando el PDF es
 * ilegible, en vez de tirar error, justamente para que la pantalla ofrezca carga manual. Acá
 * cada `null` se traduce al mismo valor por defecto que tendría un modelo empezado en blanco.
 */
function fromDraft(draft: InvoiceTemplateDraft): TemplateForm {
  const blank = emptyForm()
  return {
    // El backend no manda nombre a propósito: el PDF no lo trae y lo elige el usuario.
    name: draft.name ?? '',
    fiscal_identity_id: draft.fiscal_identity_id,
    customer_id: draft.customer_id,
    voucher_type: draft.voucher_type ?? VoucherType.C,
    pos: draft.pos !== null ? String(draft.pos) : blank.pos,
    concepto: draft.concepto,
    lines:
      draft.lines.length > 0
        ? draft.lines.map((line) =>
            newLine({
              description: line.description ?? '',
              quantity: line.quantity !== null ? fromDecimal(line.quantity) : '1',
              unit_price: line.unit_price !== null ? fromDecimal(line.unit_price) : '',
              iva_aliquot: line.iva_aliquot ?? IvaAliquot.standard,
            }),
          )
        : blank.lines,
  }
}
