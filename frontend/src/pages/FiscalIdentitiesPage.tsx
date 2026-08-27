import { useCallback } from 'react'

import { api } from '../api/client'
import type { FiscalIdentity } from '../api/types'
import { Notice } from '../components/Notice'
import { TileGrid } from '../components/TileGrid'
import { useResource } from '../hooks/useResource'

/**
 * Las identidades fiscales, con la misma grilla que los modelos.
 *
 * Antes era una tabla con el formulario de alta arriba y un lápiz y un tacho por fila. Pasa a
 * tarjetas por lo mismo que la grilla de modelos: se usa desde el celular, y una tabla de cinco
 * columnas ahí es una pila de tarjetas improvisadas con un ícono de 44 px al final. Que las
 * tres pantallas de listado se manejen igual quita además la pregunta de "en esta cuál era el
 * gesto".
 */
export function FiscalIdentitiesPage() {
  const fetcher = useCallback(() => api.get<FiscalIdentity[]>('/fiscal-identities'), [])
  const { data, error, loading, reload } = useResource(fetcher)

  return (
    <div className="page">
      <h1>Identidades fiscales</h1>
      <p className="page-intro">
        Los CUIT desde los que emitís. Tocá uno para editarlo o verificar la delegación en ARCA;
        mantenelo apretado para eliminarlo.
      </p>

      <Notice kind="error">{error}</Notice>
      {loading && !data && <p className="muted">Cargando…</p>}

      {data && (
        <TileGrid
          items={data.map((identity) => ({
            id: identity.id,
            name: identity.name,
            // El único dato que sube a la tarjeta, y solo cuando falta: una identidad sin
            // delegación verificada no puede emitir, así que sin este aviso el usuario tendría
            // que entrar a cada una para descubrir cuál lo está frenando.
            warning: identity.delegation_verified_at === null ? 'Sin verificar' : undefined,
          }))}
          to={(id) => `/identidades/${id}`}
          newTo="/identidades/nueva"
          newLabel="Nueva identidad"
          onDelete={async (id) => {
            await api.delete<void>(`/fiscal-identities/${id}`)
            reload()
          }}
        />
      )}

      {data && data.length === 0 && (
        <p className="empty">
          Todavía no cargaste ninguna. Un modelo necesita saber desde qué CUIT emitís.
        </p>
      )}
    </div>
  )
}
