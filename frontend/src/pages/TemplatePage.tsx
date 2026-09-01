import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router'

import { ApiError, api } from '../api/client'
import type { Customer, FiscalIdentity, InvoiceTemplate } from '../api/types'
import { Notice } from '../components/Notice'
import { TemplateEditor } from '../components/TemplateEditor'
import {
  formVoucherType,
  fromDecimal,
  newLine,
  priceIncludesIva,
  toPayload,
  validate,
  type TemplateForm,
} from '../forms/templateForm'
import { useResource } from '../hooks/useResource'
import { useRegisterUnsavedChanges } from '../unsaved/hooks'

export function TemplatePage() {
  const { id } = useParams()
  // El `key` fuerza a remontar cuando cambia el id. `useResource` avisa en su docstring que no
  // resetea el estado al cambiar de recurso, y acá además hay un formulario cargado con los
  // datos del modelo anterior: sin el remonte, entrar a otro modelo mostraría el de antes.
  return id ? <TemplateScreen key={id} id={id} /> : <Navigate to="/" replace />
}

function fromTemplate(template: InvoiceTemplate): TemplateForm {
  return {
    name: template.name,
    fiscal_identity_id: template.fiscal_identity_id,
    customer_id: template.customer_id,
    // `voucher_type` viene en la respuesta pero no entra al formulario: se deduce de las dos
    // condiciones frente al IVA, así que sembrarlo sería guardar una copia que puede quedar
    // vieja apenas el usuario cambie de cliente.
    pos: String(template.pos),
    concepto: template.concepto,
    // `null` es "el mail de FactuMov" y en el formulario eso es el campo vacío, que es lo que
    // el editor dibuja con el texto por default de placeholder. Sembrarlo con ese texto haría
    // que reabrir un modelo que nadie tocó lo convirtiera en uno con texto propio — y bastaría
    // con guardar cualquier otro cambio para congelarle una copia del mail de la app.
    email_subject: template.email_subject ?? '',
    email_body: template.email_body ?? '',
    // Vienen ordenadas por `position`: lo declara el `order_by` de la relación en el modelo.
    lines: template.lines.map((line) =>
      newLine({
        description: line.description,
        quantity: fromDecimal(line.quantity),
        unit_price: fromDecimal(line.unit_price),
        // El precio guardado está en la convención de la letra con la que se guardó, y es esa
        // la columna en la que se lo muestra: en una A es el neto, en una B o una C es el que
        // trae el IVA adentro. Sembrarlo siempre en la misma columna sería mostrar un precio
        // distinto del que se cargó en la mitad de los modelos.
        price_includes_iva: priceIncludesIva(template.voucher_type),
        iva_aliquot: line.iva_aliquot,
      }),
    ),
  }
}

function TemplateScreen({ id }: { id: string }) {
  const identitiesFetcher = useCallback(() => api.get<FiscalIdentity[]>('/fiscal-identities'), [])
  const customersFetcher = useCallback(() => api.get<Customer[]>('/customers'), [])
  const identities = useResource(identitiesFetcher)
  const customers = useResource(customersFetcher)

  // El modelo no va por `useResource` porque lo que hace falta no es el dato crudo sino el
  // formulario ya sembrado con él, y eso sería un `setState` derivado colgado de un efecto.
  // Cargarlo acá deja una sola fuente para el estado del formulario.
  const [form, setForm] = useState<TemplateForm>()
  // El formulario tal como está guardado en el servidor. Es contra esto que se decide si hay
  // cambios pendientes, y es a esto que vuelve "Descartar cambios".
  const [savedForm, setSavedForm] = useState<TemplateForm>()
  const [loadError, setLoadError] = useState<string>()

  useEffect(() => {
    let cancelled = false
    api
      .get<InvoiceTemplate>(`/invoice-templates/${id}`)
      .then((template) => {
        if (cancelled) return
        // **El mismo objeto para los dos**, no dos `fromTemplate(template)`. `newLine` le pone
        // a cada línea una `key` de un contador que avanza, así que dos siembras del mismo
        // modelo dan formularios con claves distintas y la comparación diría "hay cambios"
        // desde el primer render.
        const seeded = fromTemplate(template)
        setForm(seeded)
        setSavedForm(seeded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoadError(
            caught instanceof ApiError ? caught.detail : 'No se pudo cargar el modelo.',
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [id])

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [saved, setSaved] = useState(false)

  /**
   * Guarda el modelo y **rechaza si no se pudo** —validación o error del servidor—: el guard
   * de navegación lo llama al salir con cambios, y necesita saber si entraron para no dejar
   * navegar sobre lo que se perdería.
   */
  async function save() {
    if (form === undefined) return
    const voucherType = formVoucherType(form, identities.data ?? [], customers.data ?? [])
    const problem = validate(form, voucherType)
    if (problem !== undefined) {
      setError(problem)
      setSaved(false)
      throw new Error(problem)
    }
    setBusy(true)
    setError(undefined)
    setSaved(false)
    try {
      await api.patch<InvoiceTemplate>(`/invoice-templates/${id}`, toPayload(form, voucherType))
      // Lo que se acaba de mandar pasa a ser lo guardado, y con eso vuelve a aparecer
      // "Emitir esta factura". No se resiembra con la respuesta del PATCH: daría claves de
      // línea nuevas y dejaría el formulario marcado como cambiado apenas se guardó.
      setSavedForm(form)
      setSaved(true)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo guardar.')
      throw caught
    } finally {
      setBusy(false)
    }
  }

  /**
   * ¿Hay algo distinto de lo guardado?
   *
   * Se compara serializando y no campo por campo: `TemplateForm` son strings, enums y un
   * array de líneas, todos literales con las claves siempre en el mismo orden, así que
   * `JSON.stringify` es determinista acá. Una comparación a mano habría que acordarse de
   * ampliarla cada vez que el formulario gane un campo — y olvidarse significaría volver a
   * ofrecer emitir sobre cambios que se van a perder, que es justo el bug que esto cierra.
   *
   * Vuelve a dar `false` si el usuario deshace lo que hizo a mano: eso es correcto, porque en
   * ese caso ya no hay nada que guardar ni que descartar.
   */
  const dirty =
    form !== undefined && savedForm !== undefined && JSON.stringify(form) !== JSON.stringify(savedForm)

  // Salir del modelo con cambios sin guardar pide confirmar —links, botón "atrás" y el gesto
  // de deslizar—. `save` rechaza si no entró, así que "Guardar y salir" no navega sobre un
  // error. `discard` de abajo sigue siendo la salida deliberada; esto es para la accidental.
  useRegisterUnsavedChanges(dirty, save)

  function discard() {
    setForm(savedForm)
    setError(undefined)
    // El cartel de "Guardado." habla de un guardado que no ocurrió en este ciclo de edición.
    setSaved(false)
  }

  return (
    <div className="page">
      <Link className="back" to="/">
        ← Modelos
      </Link>
      <h1>{form?.name ?? 'Modelo'}</h1>

      <Notice kind="error">{loadError ?? identities.error ?? customers.error}</Notice>
      {saved && <Notice kind="ok">Guardado.</Notice>}

      {form === undefined && loadError === undefined && <p className="muted">Cargando…</p>}

      {form !== undefined && (
        <TemplateEditor
          value={form}
          onChange={(next) => {
            setForm(next)
            // El cartel de "Guardado" habla del estado anterior: en cuanto se toca algo deja
            // de ser cierto, y dejarlo puesto es la forma más barata de que alguien salga de
            // la pantalla creyendo que guardó.
            setSaved(false)
          }}
          fiscalIdentities={identities.data ?? []}
          customers={customers.data ?? []}
          // El `catch` vacío: `save` ahora rechaza para el guard, y sin esto el submit del
          // formulario dejaría una promesa colgada. El error ya se muestra en la pantalla.
          onSubmit={() => void save().catch(() => {})}
          submitLabel="Guardar cambios"
          // Sin cambios no hay nada que guardar, y el botón no aparece. Es la misma decisión
          // que la de más abajo con "Emitir": la pantalla ofrece la acción que corresponde al
          // estado en el que está, en vez de mostrarlas todas siempre y dejar que el usuario
          // adivine cuál tiene sentido ahora.
          canSubmit={dirty}
          busy={busy}
          error={error}
        />
      )}

      {form !== undefined && (
        <div className="card stack">
          {dirty ? (
            <>
              {/* Con cambios sin guardar, emitir **no se ofrece**. La pantalla de emisión le
                  pide el `preview` al servidor, así que emitiría el modelo guardado y no lo
                  que se está viendo; y al volver, esta pantalla se remonta y recarga del
                  backend, o sea que lo editado no se ignora: se pierde. Hasta el 2026-08-28
                  eso lo advertía un renglón de texto chico debajo de un botón verde grande,
                  que es poca defensa para una diferencia entre lo que se ve y lo que se
                  emite — y en un celular, ninguna. */}
              <button type="button" className="secondary" onClick={discard} disabled={busy}>
                Descartar cambios
              </button>
              <p className="totals-note" style={{ margin: 0 }}>
                Tenés cambios sin guardar. Se emite el modelo <strong>tal como está
                guardado</strong>, así que para emitir hay que resolverlos antes: guardalos
                con "Guardar cambios" o descartalos acá.
              </p>
            </>
          ) : (
            <>
              {/* Emitir es un link a otra pantalla y no un botón acá, y no es por prolijidad:
                  es lo único que separa "guardar cambios" de un acto irreversible contra
                  ARCA. Dos botones pegados en un celular es un dedo mal apoyado y una factura
                  de verdad. La pantalla de confirmación muestra letra, destinatario e
                  importe. */}
              <Link className="button-link" to={`/modelos/${id}/emitir`}>
                Emitir esta factura
              </Link>
              <p className="totals-note" style={{ margin: 0 }}>
                Te muestra qué se va a emitir antes de pedirle el CAE a ARCA.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
