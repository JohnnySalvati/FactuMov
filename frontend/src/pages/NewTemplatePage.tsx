import { useCallback, useRef, useState, type ChangeEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  isCuit,
  IvaAliquot,
  type Customer,
  type CustomerCreate,
  type FiscalIdentity,
  type InvoiceTemplate,
  type InvoiceTemplateDraft,
} from '../api/types'
import { MissingCustomer, MissingIssuer } from '../components/MissingParty'
import { Notice } from '../components/Notice'
import { TemplateEditor } from '../components/TemplateEditor'
import {
  emptyForm,
  formVoucherType,
  fromDecimal,
  newLine,
  priceIncludesIva,
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
    const input = event.target
    const file = input.files?.[0]
    if (file === undefined) return

    setReading(true)
    setError(undefined)
    try {
      // Los bytes se leen **acá**, antes de armar el request. Un `File` recién elegido no es
      // memoria: es un puntero a algo que el sistema todavía tiene que ir a buscar, y cuando ese
      // algo lo sirve un proveedor de la nube —Google Drive en el selector de Android— la
      // lectura puede fallar o devolver un archivo vacío. Pasándole el `File` directo al
      // `fetch`, esa falla revienta adentro del `fetch` y llega como "no se pudo conectar con el
      // servidor": un mensaje que manda al usuario a mirar la red cuando el problema es el
      // archivo. Leyéndolo antes, el error aparece donde ocurre.
      const bytes = await file.arrayBuffer().catch(() => undefined)
      if (bytes === undefined || bytes.byteLength === 0) {
        setError(
          'No se pudo leer ese archivo. Si lo elegiste desde Google Drive o de otra nube, ' +
            'bajalo al teléfono primero y volvé a intentar.',
        )
        return
      }

      const imported = await api.upload<InvoiceTemplateDraft>(
        '/invoice-templates/import',
        new Blob([bytes], { type: 'application/pdf' }),
        file.name,
      )
      setDraft(imported)
      setForm(fromDraft(imported))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo leer el archivo.')
    } finally {
      setReading(false)
      // El input se limpia siempre: sin esto, elegir el mismo archivo dos veces seguidas no
      // dispara `change` y el botón parece roto. Va acá y no antes de subir porque en algunos
      // navegadores limpiarlo suelta la referencia al archivo que todavía estamos por leer.
      input.value = ''
    }
  }

  /**
   * Deja elegido en el formulario el cliente recién dado de alta.
   *
   * El `reload` no es opcional: sin él el picker no conoce al cliente nuevo y el campo se ve
   * vacío aunque el id ya esté puesto, porque el nombre en pantalla sale de la lista de
   * opciones.
   *
   * **El draft no se toca a propósito.** Es lo que decide si la tarjeta sigue en pantalla, y
   * la tarjeta tiene algo que decir *después* de crear: qué cliente se dio de alta y con los
   * datos de quién. Actualizarlo acá haría desaparecer el aviso en el mismo instante en que
   * pasa a ser útil — el alta se volvería invisible, que es justo lo que no puede ser cuando
   * la hace la app sola.
   */
  function customerCreated(created: Customer) {
    setForm((current) => (current ? { ...current, customer_id: created.id } : current))
    customers.reload()
  }

  /** Lo mismo para la identidad fiscal que se creó desde el CUIT que emitió el PDF. */
  function issuerCreated(created: FiscalIdentity) {
    setForm((current) => (current ? { ...current, fiscal_identity_id: created.id } : current))
    identities.reload()
  }

  async function save() {
    if (form === undefined) return
    const voucherType = formVoucherType(form, identities.data ?? [], customers.data ?? [])
    const problem = validate(form, voucherType)
    if (problem !== undefined) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(undefined)
    try {
      await api.post<InvoiceTemplate>('/invoice-templates', toPayload(form, voucherType))
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
   *
   * Desde que el alta pasa por el padrón esto **ya no es el camino principal sino el de
   * respaldo**: es con lo que se da de alta un cliente con DNI, que no está en el padrón, o uno
   * con CUIT cuando ARCA no contesta.
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

  /**
   * ¿Hay un receptor en el PDF que la cartera no tiene y que se pueda resolver desde acá?
   *
   * Con un CUIT siempre se puede: aunque el parser haya leído mal el nombre, el padrón lo trae.
   * Sin CUIT hace falta que el PDF haya traído el alta completa. Si no se da ninguna de las dos,
   * el cartel no aparece: no tendría ningún botón abajo.
   */
  const missingCustomer =
    draft !== undefined &&
    draft.customer_id === null &&
    (pendingCustomer !== undefined || isCuit(draft.customer.doc_type, draft.customer.doc_number))

  return (
    <div className="page">
      <Link className="back" to="/">
        ← Modelos
      </Link>
      <h1>Nuevo modelo</h1>

      {noIdentities && (
        <Notice kind="warn">
          Todavía no cargaste ninguna identidad fiscal, y un modelo necesita saber desde qué
          CUIT emitís. <Link to="/identidades/nueva">Cargá la primera</Link> y volvé.
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
              <MissingIssuer taxId={draft.issuer_tax_id} onCreated={issuerCreated} />
            )}

          {missingCustomer && draft !== undefined && (
            <MissingCustomer
              draft={draft.customer}
              fallback={pendingCustomer}
              onCreated={customerCreated}
            />
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
    pos: draft.pos !== null ? String(draft.pos) : blank.pos,
    concepto: draft.concepto,
    lines:
      draft.lines.length > 0
        ? draft.lines.map((line) =>
            newLine({
              description: line.description ?? '',
              quantity: line.quantity !== null ? fromDecimal(line.quantity) : '1',
              unit_price: line.unit_price !== null ? fromDecimal(line.unit_price) : '',
              // En qué columna cae el precio que trajo el PDF lo dice la letra **de ese PDF**,
              // que el parser leyó y el draft trae. No la del par emisor/cliente que se termine
              // eligiendo acá: si la factura importada era una A, ese precio es neto aunque el
              // receptor todavía no esté en la cartera y no haya letra que deducir. Poniéndolo
              // en la columna equivocada, al guardar quedaría un 21% corrido.
              price_includes_iva: priceIncludesIva(draft.voucher_type ?? undefined),
              iva_aliquot: line.iva_aliquot ?? IvaAliquot.standard,
            }),
          )
        : blank.lines,
  }
}
