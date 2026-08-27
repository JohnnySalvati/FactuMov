import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import { useLongPress } from '../hooks/useLongPress'

export interface TileItem {
  id: string
  name: string
  /**
   * Un aviso corto abajo del nombre, o nada.
   *
   * Es la única excepción al "solo el nombre", y está acotada a propósito: solo se usa para un
   * estado que **bloquea** al usuario y que de otro modo obligaría a entrar tarjeta por tarjeta
   * a buscar cuál es —hoy, la identidad fiscal sin delegación verificada, que no puede emitir—.
   * Cuando todo está en orden no aparece nada, así que el caso normal sigue siendo una grilla
   * de nombres.
   */
  warning?: string
}

/**
 * La grilla de tarjetas: una por elemento, una vacía con un `+` al final.
 *
 * Es la forma que tienen las tres pantallas de listado —modelos, identidades fiscales y
 * clientes—. Estaba escrita adentro de `TemplatesPage`, y se extrajo al querer la misma cosa en
 * las otras dos: no es un patrón visual que se pueda copiar y pegar, porque adentro tiene el
 * estado de "cuál está armada", el gesto, y las tres precauciones de `useLongPress`. Copiado
 * tres veces, la próxima corrección del gesto arregla una pantalla y deja dos rotas.
 *
 * Las tarjetas muestran **solo el nombre**. Lo que hace falta acá es reconocer el elemento de un
 * vistazo y llegar con un dedo; el resto de los datos están adentro, que es donde se los mira.
 * Una lista con cuatro columnas diría más y se leería peor.
 *
 * Se entra tocando y se borra manteniendo apretado. Que eliminar quede detrás de un gesto y no
 * de un tacho siempre visible es a propósito: en una grilla de objetivos de 150 px, un ícono de
 * borrar pegado al área que se toca cien veces por semana se aprieta solo.
 */
export function TileGrid({
  items,
  to,
  newTo,
  newLabel,
  onDelete,
}: {
  items: TileItem[]
  /** A dónde lleva tocar una tarjeta. */
  to: (id: string) => string
  newTo: string
  newLabel: string
  /** Borra y recarga la lista. Lo que tire se muestra adentro de la tarjeta. */
  onDelete: (id: string) => Promise<void>
}) {
  // Qué tarjeta tiene el borrar a la vista. Es una sola: dos armadas a la vez serían dos
  // preguntas abiertas y ninguna forma de saber cuál se está contestando.
  const [armed, setArmed] = useState<string | null>(null)

  // Tocar en cualquier otro lado desarma. Va sobre `pointerdown` y no sobre `click` para que el
  // primer toque afuera sirva para cancelar y no se lo coma la tarjeta que estaba armada.
  useEffect(() => {
    if (armed === null) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target
      if (target instanceof Element && target.closest('.tile.armed') !== null) return
      setArmed(null)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [armed])

  return (
    <div className="tiles">
      {items.map((item) => (
        <Tile
          key={item.id}
          item={item}
          to={to(item.id)}
          armed={armed === item.id}
          onArm={() => setArmed(item.id)}
          onDisarm={() => setArmed(null)}
          onDelete={async () => {
            await onDelete(item.id)
            setArmed(null)
          }}
        />
      ))}

      <Link className="tile tile-new" to={newTo}>
        <span className="tile-plus" aria-hidden="true">
          +
        </span>
        <span className="tile-name">{newLabel}</span>
      </Link>
    </div>
  )
}

function Tile({
  item,
  to,
  armed,
  onArm,
  onDisarm,
  onDelete,
}: {
  item: TileItem
  to: string
  armed: boolean
  onArm: () => void
  onDisarm: () => void
  onDelete: () => Promise<void>
}) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const longPress = useLongPress(onArm)

  async function remove() {
    setBusy(true)
    setError(undefined)
    try {
      await onDelete()
      // Sin `setBusy(false)` en el camino feliz: la tarjeta se va con la recarga de la lista, y
      // el cartel de "Eliminando…" tiene que seguir puesto mientras tanto.
    } catch (caught) {
      // El error se muestra **adentro de la tarjeta** y no arriba de la grilla: el 409 de "tiene
      // modelos asociados" es sobre este elemento, y mostrarlo arriba obligaría a adivinar cuál
      // se quejó.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo eliminar.')
      setBusy(false)
    }
  }

  if (armed) {
    // Dos botones con su nombre escrito, y no un tacho de dos pasos. Sostener el dedo medio
    // segundo ya fue el paso deliberado; lo que falta es un objetivo grande y sin ambigüedad,
    // que en una tarjeta de 150 px no lo da un ícono.
    return (
      <div className="tile armed">
        <span className="tile-name">{item.name}</span>
        {error && <span className="tile-error">{error}</span>}
        <div className="tile-actions">
          <button type="button" className="danger" onClick={remove} disabled={busy}>
            {busy ? 'Eliminando…' : '🗑 Eliminar'}
          </button>
          <button type="button" className="secondary" onClick={onDisarm} disabled={busy}>
            Cancelar
          </button>
        </div>
      </div>
    )
  }

  // Es un `<button>` y no un `<Link>`: `useLongPress` necesita frenar el click que el navegador
  // manda al soltar el dedo, y sobre un ancla eso significa además pelearle la navegación por
  // defecto. Con un botón, cancelar el click es todo lo que hay que hacer.
  return (
    <button type="button" className="tile" onClick={() => navigate(to)} {...longPress}>
      <span className="tile-name">{item.name}</span>
      {item.warning !== undefined && <span className="tile-badge">{item.warning}</span>}
    </button>
  )
}
