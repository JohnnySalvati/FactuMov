import { useCallback } from 'react'

import { api } from '../api/client'
import type { InvoiceTemplate } from '../api/types'
import { Notice } from '../components/Notice'
import { TileGrid } from '../components/TileGrid'
import { useResource } from '../hooks/useResource'

/**
 * La pantalla de entrada: una tarjeta por modelo, y una vacía con un `+` al final.
 *
 * La grilla, el gesto y el borrado viven en `TileGrid`, que es lo que comparte con las
 * pantallas de identidades fiscales y de clientes — ver ahí el porqué de cada decisión.
 */
export function TemplatesPage() {
  const fetcher = useCallback(() => api.get<InvoiceTemplate[]>('/invoice-templates'), [])
  const { data, error, loading, reload } = useResource(fetcher)

  return (
    <div className="page">
      <h1>Modelos</h1>
      <p className="page-intro">
        Tocá un modelo para emitirlo o retocarlo. Mantenelo apretado para eliminarlo.
      </p>

      <Notice kind="error">{error}</Notice>
      {loading && !data && <p className="muted">Cargando…</p>}

      {data && (
        <TileGrid
          items={data.map((template) => ({ id: template.id, name: template.name }))}
          to={(id) => `/modelos/${id}`}
          newTo="/modelos/nuevo"
          newLabel="Nuevo modelo"
          onDelete={async (id) => {
            await api.delete<void>(`/invoice-templates/${id}`)
            reload()
          }}
        />
      )}

      {data && data.length === 0 && (
        <p className="empty">
          Todavía no tenés ningún modelo. Empezá importando una factura que ya emitiste.
        </p>
      )}
    </div>
  )
}
