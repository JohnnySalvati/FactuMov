import { useCallback, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router'

import { ApiError, api } from '../api/client'
import type { EmitRequest, Invoice, InvoicePreview } from '../api/types'
import { Notice } from '../components/Notice'
import { money } from '../format'
import { useResource } from '../hooks/useResource'

/**
 * La pantalla de confirmación de la emisión.
 *
 * **Existe porque emitir es irreversible.** Con `ARCA_ENV=prod`, apretar el botón deja un
 * comprobante con validez legal a nombre de un CUIT real, y no hay forma de deshacerlo desde
 * la app: se anula con una nota de crédito, que FactuMov no emite. Un botón "Emitir" directo
 * en la pantalla del modelo, al lado de "Guardar cambios", habría sido un dedo mal apoyado en
 * un celular.
 *
 * Por eso es una pantalla aparte y no un `window.confirm`: hay que mostrar la letra, el
 * destinatario y el importe exacto, y eso no entra en un diálogo del sistema — que además
 * bloquea el hilo, no se puede estilar, y en algunos navegadores queda suprimido si el
 * usuario marcó "no mostrar más", o sea que la confirmación desaparece sin que nadie se
 * entere. Es la misma decisión que se tomó para el borrado de las tarjetas.
 *
 * Los importes salen del `preview` del backend y no de la cuenta del editor. Las dos dan lo
 * mismo hoy; la diferencia es que este número es el que se va a declarar.
 */
export function EmitPage() {
  const { id } = useParams()
  return id ? <EmitScreen key={id} id={id} /> : <Navigate to="/" replace />
}

/** El primer y el último día del mes en curso, y hoy, en el `YYYY-MM-DD` que espera la API. */
function defaultPeriod() {
  const now = new Date()
  const iso = (value: Date) => value.toISOString().slice(0, 10)
  return {
    from_date: iso(new Date(now.getFullYear(), now.getMonth(), 1)),
    to_date: iso(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
    due_date: iso(now),
  }
}

function EmitScreen({ id }: { id: string }) {
  const fetcher = useCallback(
    () => api.get<InvoicePreview>(`/invoice-templates/${id}/preview`),
    [id],
  )
  const preview = useResource(fetcher)
  const navigate = useNavigate()

  const [period, setPeriod] = useState(defaultPeriod)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    // El guard no es decorativo: sin él, un segundo submit mientras el primero está en vuelo
    // emite dos facturas. El `disabled` del botón cubre el click, pero no el Enter en un
    // campo del formulario.
    if (busy) return
    setBusy(true)
    setError(undefined)
    const body: EmitRequest = preview.data?.needs_service_dates ? period : {}
    try {
      const invoice = await api.post<Invoice>(`/invoice-templates/${id}/emit`, body)
      // `replace` para que el "atrás" del navegador no vuelva a la pantalla de confirmar una
      // emisión que ya ocurrió.
      navigate(`/facturas/${invoice.id}`, { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo emitir.')
      setBusy(false)
    }
  }

  const data = preview.data

  return (
    <div className="page">
      <Link className="back" to={`/modelos/${id}`}>
        ← Modelo
      </Link>
      <h1>Emitir</h1>

      <Notice kind="error">{preview.error ?? error}</Notice>
      {preview.loading && data === undefined && <p className="muted">Cargando…</p>}

      {data !== undefined && (
        <form className="card stack" onSubmit={onSubmit}>
          <dl className="summary">
            <div>
              <dt>Comprobante</dt>
              <dd>
                Factura {data.voucher_type} — punto de venta {data.pos}
              </dd>
            </div>
            <div>
              <dt>Emite</dt>
              <dd>
                {data.issuer_name} <span className="muted">({data.issuer_tax_id})</span>
              </dd>
            </div>
            <div>
              <dt>A</dt>
              <dd>
                {data.customer_name} <span className="muted">({data.customer_doc_number})</span>
              </dd>
            </div>
            <div>
              <dt>Total</dt>
              <dd className="amount">{money.format(Number(data.total))}</dd>
            </div>
          </dl>

          {data.needs_service_dates && (
            <>
              {/* Solo para servicios: ARCA exige el período facturado y el vencimiento del
                  pago, y los rechaza si falta alguno. Vienen con el mes en curso puesto,
                  que es lo que se factura el 99% de las veces. */}
              <div className="row">
                <div>
                  <label htmlFor="from_date">Período desde</label>
                  <input
                    id="from_date"
                    type="date"
                    required
                    value={period.from_date}
                    onChange={(e) => setPeriod({ ...period, from_date: e.target.value })}
                  />
                </div>
                <div>
                  <label htmlFor="to_date">Hasta</label>
                  <input
                    id="to_date"
                    type="date"
                    required
                    value={period.to_date}
                    onChange={(e) => setPeriod({ ...period, to_date: e.target.value })}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="due_date">Vencimiento del pago</label>
                <input
                  id="due_date"
                  type="date"
                  required
                  value={period.due_date}
                  onChange={(e) => setPeriod({ ...period, due_date: e.target.value })}
                />
              </div>
            </>
          )}

          {data.blocked_reason !== null ? (
            <Notice kind="warn">{data.blocked_reason}</Notice>
          ) : (
            <Notice kind="warn">
              Esto le pide el CAE a ARCA y <strong>no se puede deshacer</strong>. Para dejar sin
              efecto una factura emitida hace falta una nota de crédito, que se hace en el sitio
              de ARCA.
            </Notice>
          )}

          <button type="submit" disabled={busy || data.blocked_reason !== null}>
            {busy ? 'Emitiendo…' : `Emitir factura ${data.voucher_type}`}
          </button>
        </form>
      )}
    </div>
  )
}
