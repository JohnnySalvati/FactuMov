import { useCallback } from 'react'

import { api } from '../api/client'
import type { Customer } from '../api/types'
import { Notice } from '../components/Notice'
import { TileGrid } from '../components/TileGrid'
import { useResource } from '../hooks/useResource'

/** Los clientes, con la misma grilla que los modelos — ver `FiscalIdentitiesPage` por qué las
 *  tres pantallas de listado se manejan igual. */
export function CustomersPage() {
  const fetcher = useCallback(() => api.get<Customer[]>('/customers'), [])
  const { data, error, loading, reload } = useResource(fetcher)

  return (
    <div className="page">
      <h1>Clientes</h1>
      <p className="page-intro">
        A quiénes les facturás. Tocá uno para editarlo; mantenelo apretado para eliminarlo.
      </p>

      <Notice kind="error">{error}</Notice>
      {loading && !data && <p className="muted">Cargando…</p>}

      {data && (
        <TileGrid
          items={data.map((customer) => ({ id: customer.id, name: customer.name }))}
          to={(id) => `/clientes/${id}`}
          newTo="/clientes/nuevo"
          newLabel="Nuevo cliente"
          onDelete={async (id) => {
            await api.delete<void>(`/customers/${id}`)
            reload()
          }}
        />
      )}

      {data && data.length === 0 && (
        <p className="empty">
          Todavía no cargaste ninguno. Si tenés el CUIT, se completa solo desde el padrón de
          ARCA.
        </p>
      )}
    </div>
  )
}
