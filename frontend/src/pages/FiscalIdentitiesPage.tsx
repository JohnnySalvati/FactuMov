import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import { checkDelegation, checkedRecently, needsChecking } from '../api/delegation'
import type { FiscalIdentity } from '../api/types'
import { Notice } from '../components/Notice'
import { TileGrid } from '../components/TileGrid'
import { useResource } from '../hooks/useResource'
import { useSubscription } from '../subscription/useSubscription'

/**
 * Las identidades fiscales, con la misma grilla que los modelos.
 *
 * Antes era una tabla con el formulario de alta arriba y un lápiz y un tacho por fila. Pasa a
 * tarjetas por lo mismo que la grilla de modelos: se usa desde el celular, y una tabla de cinco
 * columnas ahí es una pila de tarjetas improvisadas con un ícono de 44 px al final. Que las
 * tres pantallas de listado se manejen igual quita además la pregunta de "en esta cuál era el
 * gesto".
 *
 * **La grilla también repregunta por la delegación** (2026-08-29). Antes el aviso "Sin
 * verificar" salía de la columna guardada y nada más, así que decía la verdad recién después de
 * entrar a cada identidad: una que ya estaba habilitada en ARCA seguía marcada como sin
 * verificar hasta que alguien la abriera. La marca existe justamente para no tener que entrar
 * tarjeta por tarjeta, o sea que era la única pantalla donde el dato tenía que estar fresco y
 * era la única que no lo refrescaba.
 */
export function FiscalIdentitiesPage() {
  const fetcher = useCallback(() => api.get<FiscalIdentity[]>('/fiscal-identities'), [])
  const { data, error, loading, reload } = useResource(fetcher)
  const { reload: reloadPlan } = useSubscription()

  // Lo que ARCA contestó recién, por identidad. Se guarda al lado de `data` en vez de
  // reescribirlo: `useResource` es dueño de esa lista y la vuelve a pedir al borrar, y un
  // recurso que se deja mutar desde afuera es un recurso que en la próxima recarga vuelve atrás
  // sin que se note. `undefined` en el Map = todavía no preguntamos; `null` = ARCA dijo que no.
  const [checked, setChecked] = useState(new Map<string, string | null>())
  const [sweeping, setSweeping] = useState(false)
  const [sweepFailed, setSweepFailed] = useState(false)

  // Una barrida por carga de la pantalla, no una por render. El ref es el mismo guard que usa
  // el detalle contra el doble montaje de StrictMode.
  const swept = useRef(false)

  useEffect(() => {
    if (data === undefined || swept.current) return
    swept.current = true

    let cancelled = false
    async function sweep(identities: FiscalIdentity[]) {
      // `needsChecking` descarta las que ya sabemos vigentes y `checkedRecently` las que
      // acabamos de preguntar desde el detalle: el presupuesto de ARCA es del certificado y es
      // uno solo para toda la app — ver `api/delegation.ts`.
      const pending = identities.filter(
        (identity) =>
          needsChecking(identity.delegation_verified_at) && !checkedRecently(identity.id),
      )
      if (pending.length === 0) return

      setSweeping(true)
      for (const identity of pending) {
        try {
          const status = await checkDelegation(identity.id)
          if (cancelled) return
          setChecked((current) =>
            new Map(current).set(identity.id, status.delegation_verified_at),
          )
        } catch {
          // **Se corta en el primero que falla, no se sigue con el resto.** Lo que hace fallar
          // a una las hace fallar a todas: o ARCA no contesta, o el limitador ya dijo basta. En
          // los dos casos, seguir el loop es gastar N llamadas para juntar N veces el mismo
          // error — y con el limitador es además cavar más hondo el pozo del que se quiere
          // salir.
          if (!cancelled) setSweepFailed(true)
          return
        }
      }
    }

    // Secuencial y no `Promise.all`: cada vuelta es una conversación con ARCA de varios
    // segundos por un certificado compartido, y dispararlas todas juntas es la forma más rápida
    // de comerse el 429. Las tarjetas se van pintando de a una, que además se lee mejor.
    void sweep(data).finally(() => {
      if (!cancelled) setSweeping(false)
    })

    return () => {
      cancelled = true
    }
  }, [data])

  return (
    <div className="page">
      <h1>Identidades fiscales</h1>
      <p className="page-intro">
        Los CUIT desde los que emitís. Tocá uno para editarlo o verificar la delegación en ARCA;
        mantenelo apretado para eliminarlo.
      </p>

      <Notice kind="error">{error}</Notice>
      {loading && !data && <p className="muted">Cargando…</p>}
      {sweeping && <p className="muted">Consultando ARCA…</p>}
      {/* Sin cartel rojo, por lo mismo que en el detalle: nadie pidió esta consulta. Pero
          tampoco en silencio — si no se pudo preguntar, "Sin verificar" en una tarjeta es un
          dato viejo y no una respuesta de ARCA, y esa diferencia es la que hace ir a mirar al
          lugar equivocado. */}
      {sweepFailed && (
        <p className="muted">
          No se pudo consultar ARCA recién: lo que dicen las tarjetas es lo último que sabíamos.
        </p>
      )}

      {data && (
        <TileGrid
          items={data.map((identity) => {
            const fresh = checked.get(identity.id)
            const verifiedAt = fresh === undefined ? identity.delegation_verified_at : fresh
            return {
              id: identity.id,
              name: identity.name,
              // El único dato que sube a la tarjeta, y solo cuando falta: una identidad sin
              // delegación verificada no puede emitir, así que sin este aviso el usuario tendría
              // que entrar a cada una para descubrir cuál lo está frenando.
              warning: verifiedAt === null ? 'Sin verificar' : undefined,
            }
          })}
          to={(id) => `/identidades/${id}`}
          newTo="/identidades/nueva"
          newLabel="Nueva identidad"
          onDelete={async (id) => {
            await api.delete<void>(`/fiscal-identities/${id}`)
            reload()
            // Borrar una devuelve cupo: sin esto, el Free que elimina la que tenía sigue
            // viendo el aviso de "ya la cargaste" en el alta.
            reloadPlan()
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
