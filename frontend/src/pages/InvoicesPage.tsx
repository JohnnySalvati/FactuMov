import { useCallback } from 'react'
import { Link } from 'react-router'

import { api } from '../api/client'
import type { Invoice } from '../api/types'
import { Notice } from '../components/Notice'
import { formatDate, money } from '../format'
import { useResource } from '../hooks/useResource'

/**
 * Las facturas emitidas, más nuevas primero.
 *
 * **No es la grilla de tarjetas.** Las otras tres pantallas de listado lo son porque en todas
 * se entra a un elemento y se lo puede eliminar, y una tarjeta grande con el nombre es lo que
 * mejor sirve para las dos cosas. Acá no se elimina nada —una factura emitida no se borra— y
 * lo que hace falta reconocer de un vistazo no es un nombre sino tres datos juntos: qué
 * comprobante, a quién y por cuánto. Una tarjeta con solo el número diría menos que esto.
 *
 * Sigue sin ser una `<table>`: es una lista de links apilados, que es lo mismo que la tabla se
 * volvía en angosto pero sin el `<thead>` escondido con `clip-path` y sin el `data-label` en
 * cada celda. El día que haga falta ordenar por columna o comparar importes en vertical, ahí
 * vuelve la tabla — y CLAUDE.md tiene anotado cómo se hacía.
 */
export function InvoicesPage() {
  const fetcher = useCallback(() => api.get<Invoice[]>('/invoices'), [])
  const invoices = useResource(fetcher)

  return (
    <div className="page">
      <h1>Facturas</h1>
      <Notice kind="error">{invoices.error}</Notice>

      {invoices.loading && invoices.data === undefined && <p className="muted">Cargando…</p>}

      {invoices.data?.length === 0 && (
        <div className="empty">
          <p>Todavía no emitiste ninguna factura.</p>
          <p className="muted">
            Se emiten desde un <Link to="/">modelo</Link>.
          </p>
        </div>
      )}

      {invoices.data !== undefined && invoices.data.length > 0 && (
        <ul className="record-list">
          {invoices.data.map((invoice) => (
            <li key={invoice.id}>
              <Link to={`/facturas/${invoice.id}`} className="record">
                <span className="record-main">
                  <strong className="mono">
                    {invoice.label}
                    {/* La única marca que se muestra en la lista, con el mismo criterio que
                        el "Sin verificar" de las identidades fiscales: es el único pendiente
                        que puede tener una factura ya emitida, y sin esto habría que entrar a
                        cada una para encontrar la que falta mandar. */}
                    {invoice.sent_at === null && <span className="badge pending">Sin enviar</span>}
                  </strong>
                  <span className="muted">{invoice.customer_name}</span>
                </span>
                <span className="record-side">
                  <strong>{money.format(Number(invoice.total))}</strong>
                  <span className="muted">{formatDate(invoice.date)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
