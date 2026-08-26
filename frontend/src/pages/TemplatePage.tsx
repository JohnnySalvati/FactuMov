import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router'

import { ApiError, api } from '../api/client'
import type { Customer, FiscalIdentity, InvoiceTemplate } from '../api/types'
import { Notice } from '../components/Notice'
import { TemplateEditor } from '../components/TemplateEditor'
import {
  fromDecimal,
  newLine,
  toPayload,
  validate,
  type TemplateForm,
} from '../forms/templateForm'
import { useResource } from '../hooks/useResource'

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
    voucher_type: template.voucher_type,
    pos: String(template.pos),
    concepto: template.concepto,
    // Vienen ordenadas por `position`: lo declara el `order_by` de la relación en el modelo.
    lines: template.lines.map((line) =>
      newLine({
        description: line.description,
        quantity: fromDecimal(line.quantity),
        unit_price: fromDecimal(line.unit_price),
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
  const [loadError, setLoadError] = useState<string>()

  useEffect(() => {
    let cancelled = false
    api
      .get<InvoiceTemplate>(`/invoice-templates/${id}`)
      .then((template) => {
        if (!cancelled) setForm(fromTemplate(template))
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

  async function save() {
    if (form === undefined) return
    const problem = validate(form)
    if (problem !== undefined) {
      setError(problem)
      setSaved(false)
      return
    }
    setBusy(true)
    setError(undefined)
    setSaved(false)
    try {
      await api.patch<InvoiceTemplate>(`/invoice-templates/${id}`, toPayload(form))
      setSaved(true)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo guardar.')
    } finally {
      setBusy(false)
    }
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
          onSubmit={save}
          submitLabel="Guardar cambios"
          busy={busy}
          error={error}
        />
      )}
    </div>
  )
}
