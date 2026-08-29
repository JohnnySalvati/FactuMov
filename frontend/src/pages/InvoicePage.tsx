import { useCallback, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  BALANCE360_STATUS_LABELS,
  CONCEPTO_LABELS,
  IVA_ALIQUOT_LABELS,
  type Invoice,
} from '../api/types'
import { Notice } from '../components/Notice'
import { formatDate, money } from '../format'
import { useResource } from '../hooks/useResource'

/**
 * Una factura emitida. **Solo lectura, y eso es todo el diseño de la pantalla.**
 *
 * No hay ningún campo editable ni botón de guardar, porque no hay nada que se pueda corregir:
 * lo que está acá es lo que ARCA autorizó. Los datos del emisor y del receptor son los que
 * vinieron **copiados** en la factura y no los de las fichas actuales — si el cliente cambió
 * de domicilio el mes pasado, esta pantalla sigue mostrando el que salió impreso, que es lo
 * correcto.
 *
 * La excepción es el mail, que sale de la ficha del cliente tal como está hoy: no se imprime
 * ni viaja a ARCA, es a dónde entregar el PDF. Por eso cargarlo después de emitir alcanza para
 * que el botón de mandar aparezca — antes se copiaba al emitir y la factura quedaba sin
 * dirección para siempre. Lo que sí es un hecho congelado es `sent_to`: a qué casilla salió.
 */
export function InvoicePage() {
  const { id } = useParams()
  return id ? <InvoiceScreen key={id} id={id} /> : <Navigate to="/facturas" replace />
}

function InvoiceScreen({ id }: { id: string }) {
  const fetcher = useCallback(() => api.get<Invoice>(`/invoices/${id}`), [id])
  const invoice = useResource(fetcher)
  const data = invoice.data

  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string>()
  const [justSent, setJustSent] = useState(false)
  const [registering, setRegistering] = useState(false)

  async function send() {
    if (sending) return
    setSending(true)
    setSendError(undefined)
    try {
      await api.post<Invoice>(`/invoices/${id}/send`, undefined)
      setJustSent(true)
      // Se recarga en vez de meter la respuesta en el estado: `useResource` es la única
      // fuente de la factura en esta pantalla, y tener dos formas de actualizarla es cómo se
      // llega a que muestren cosas distintas.
      invoice.reload()
    } catch (caught) {
      setSendError(caught instanceof ApiError ? caught.detail : 'No se pudo mandar el mail.')
    } finally {
      setSending(false)
    }
  }

  /**
   * Reintenta la copia en Balance360. **No hay confirmación y no hace falta.**
   *
   * Es idempotente del otro lado: el id de esta factura viaja como clave, así que un segundo
   * registro devuelve el comprobante que ya estaba en vez de duplicarlo. Es la diferencia con
   * emitir, donde repetir crea un comprobante nuevo y por eso hay una pantalla entera de
   * confirmación.
   */
  async function register() {
    if (registering) return
    setRegistering(true)
    try {
      await api.post<Invoice>(`/invoices/${id}/register`, undefined)
      // Sin `catch` que muestre nada: el endpoint contesta 200 ande o no ande, y el motivo del
      // fallo vuelve adentro de la factura. Recargar es lo que lo pone en pantalla.
      invoice.reload()
    } finally {
      setRegistering(false)
    }
  }

  return (
    <div className="page">
      <Link className="back" to="/facturas">
        ← Facturas
      </Link>
      <h1 className="mono">{data?.label ?? 'Factura'}</h1>

      <Notice kind="error">{invoice.error}</Notice>
      {invoice.loading && data === undefined && <p className="muted">Cargando…</p>}

      {data !== undefined && (
        <>
          <div className="card">
            <dl className="summary">
              <div>
                <dt>Fecha</dt>
                <dd>{formatDate(data.date)}</dd>
              </div>
              <div>
                <dt>Emisor</dt>
                <dd>
                  {data.issuer_name} <span className="muted">({data.issuer_tax_id})</span>
                </dd>
              </div>
              <div>
                <dt>Cliente</dt>
                <dd>
                  {data.customer_name}{' '}
                  <span className="muted">({data.customer_doc_number})</span>
                </dd>
              </div>
              <div>
                <dt>Concepto</dt>
                <dd>{CONCEPTO_LABELS[data.concepto]}</dd>
              </div>
              {data.from_date !== null && data.to_date !== null && (
                <div>
                  <dt>Período</dt>
                  <dd>
                    {formatDate(data.from_date)} — {formatDate(data.to_date)}
                  </dd>
                </div>
              )}
              {data.due_date !== null && (
                <div>
                  <dt>Vence el pago</dt>
                  <dd>{formatDate(data.due_date)}</dd>
                </div>
              )}
              <div>
                <dt>CAE</dt>
                {/* Monoespaciada: son catorce dígitos que alguien puede tener que comparar a
                    ojo contra el sitio de ARCA, y en proporcional eso se hace mal. */}
                <dd className="mono">
                  {data.cae} <span className="muted">vence {formatDate(data.cae_expiry)}</span>
                </dd>
              </div>
            </dl>
          </div>

          <div className="card">
            {data.lines.map((line) => (
              <div className="line" key={line.id}>
                <div className="line-head">
                  <span>{line.description}</span>
                  <span className="line-amount">
                    {money.format(Number(line.quantity) * Number(line.unit_price))}
                  </span>
                </div>
                <p className="muted" style={{ margin: 0, fontSize: '0.82rem' }}>
                  {Number(line.quantity)} × {money.format(Number(line.unit_price))} · IVA{' '}
                  {IVA_ALIQUOT_LABELS[line.iva_aliquot]}
                </p>
              </div>
            ))}

            <div className="totals">
              <div>
                <span>Neto</span>
                <span>{money.format(Number(data.net_total))}</span>
              </div>
              <div>
                <span>IVA</span>
                <span>{money.format(Number(data.iva_total))}</span>
              </div>
              <div className="totals-total">
                <strong>Total</strong>
                <strong>{money.format(Number(data.total))}</strong>
              </div>
            </div>
            {/* A diferencia del editor, acá el total **no** es una cuenta nuestra: es el
                importe que ARCA autorizó, guardado en la factura. */}
            <p className="totals-note">Importe autorizado por ARCA con el CAE de arriba.</p>
          </div>

          <div className="card stack">
            {/* Un `<a>` común y no un fetch a blob: la cookie de sesión viaja sola porque el
                proxy de Vite deja todo en el mismo origen, y el navegador abre su visor de
                PDF. Bajarlo a mano quedaría a un toque igual. */}
            <a className="button-link secondary-link" href={`/api/invoices/${id}/pdf`}
               target="_blank" rel="noreferrer">
              Ver el PDF
            </a>

            {data.customer_email !== null ? (
              <button onClick={send} disabled={sending}>
                {sending
                  ? 'Mandando…'
                  : data.sent_at !== null
                    ? 'Mandar de nuevo'
                    : `Mandar por email a ${data.customer_email}`}
              </button>
            ) : (
              <Notice kind="warn">
                Este cliente no tiene email cargado.{' '}
                <Link to={`/clientes/${data.customer_id}`}>Agregáselo</Link> y volvé.
              </Notice>
            )}

            <Notice kind="error">{sendError}</Notice>
            {justSent && sendError === undefined && <Notice kind="ok">Mail enviado.</Notice>}

            {/* La marca es del último envío, no un historial: reenviar la pisa. Y no es acuse
                de recibo — dice que el servidor de mail lo aceptó, no que el cliente lo haya
                abierto. El texto lo dice para que nadie lo lea como otra cosa. */}
            {data.sent_at !== null && (
              <p className="totals-note" style={{ margin: 0 }}>
                Enviado por última vez el {formatDate(data.sent_at.slice(0, 10))}
                {data.sent_to !== null && <> a {data.sent_to}</>}. Que haya salido no garantiza
                que el cliente lo haya abierto.
              </p>
            )}
          </div>

          {/* El bloque de Balance360 aparece **solo si la factura entró al circuito**. Con
              `null` —el caso de todas las emitidas antes de conectar la cuenta— no se muestra
              nada: un indicador en gris diciendo "no registrada" en cada factura vieja sería
              ruido permanente sobre algo que nunca tuvo que pasar. */}
          {data.balance360_status !== null && (
            <div className="card stack">
              <p style={{ margin: 0 }}>
                {BALANCE360_STATUS_LABELS[data.balance360_status]}
                {data.balance360_synced_at !== null && (
                  <span className="muted">
                    {' '}
                    · {formatDate(data.balance360_synced_at.slice(0, 10))}
                  </span>
                )}
              </p>

              {/* El motivo tal como lo dio Balance360: "el CUIT no está cargado", "elegí una
                  entidad". Es lo único que le dice al usuario qué tiene que arreglar allá. */}
              {data.balance360_error !== null && (
                <Notice kind="warn">{data.balance360_error}</Notice>
              )}

              {data.balance360_status !== 'registered' && (
                <button className="secondary" onClick={register} disabled={registering}>
                  {registering ? 'Registrando…' : 'Reintentar el registro'}
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
