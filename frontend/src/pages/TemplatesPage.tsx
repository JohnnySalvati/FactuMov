import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError, api } from '../api/client'
import type { InvoiceTemplate } from '../api/types'
import { Notice } from '../components/Notice'
import { useLongPress } from '../hooks/useLongPress'
import { useResource } from '../hooks/useResource'

/**
 * La pantalla de entrada: una tarjeta por modelo, y una vacía con un `+` al final.
 *
 * Las tarjetas muestran **solo el nombre**. Es la pantalla que se abre cien veces por semana
 * para hacer siempre lo mismo, así que lo que importa es reconocer el modelo de un vistazo y
 * llegar con un dedo; el CUIT, el cliente y los importes están adentro, que es donde se los
 * mira. Una lista con cuatro columnas diría más y se leería peor.
 *
 * Se entra tocando y se borra manteniendo apretado. Que eliminar quede detrás de un gesto y no
 * de un tacho siempre visible es a propósito: en una grilla de objetivos de 150 px, un ícono
 * de borrar pegado al área que se toca cien veces por semana se aprieta solo.
 */
export function TemplatesPage() {
  const fetcher = useCallback(() => api.get<InvoiceTemplate[]>('/invoice-templates'), [])
  const { data, error, loading, reload } = useResource(fetcher)

  // Qué tarjeta tiene el borrar a la vista. Es uno solo: dos tarjetas armadas a la vez serían
  // dos preguntas abiertas y ninguna forma de saber cuál se está contestando.
  const [armed, setArmed] = useState<string | null>(null)

  // Tocar en cualquier otro lado desarma. Va sobre `pointerdown` y no sobre `click` para que
  // el primer toque afuera sirva para cancelar y no se lo coma la tarjeta que estaba armada.
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
    <div className="page">
      <h1>Modelos</h1>
      <p className="page-intro">
        Tocá un modelo para emitirlo o retocarlo. Mantenelo apretado para eliminarlo.
      </p>

      <Notice kind="error">{error}</Notice>
      {loading && !data && <p className="muted">Cargando…</p>}

      {data && (
        <div className="tiles">
          {data.map((template) => (
            <TemplateTile
              key={template.id}
              template={template}
              armed={armed === template.id}
              onArm={() => setArmed(template.id)}
              onDisarm={() => setArmed(null)}
              onDeleted={() => {
                setArmed(null)
                reload()
              }}
            />
          ))}

          <Link className="tile tile-new" to="/modelos/nuevo">
            <span className="tile-plus" aria-hidden="true">
              +
            </span>
            <span className="tile-name">Nuevo modelo</span>
          </Link>
        </div>
      )}

      {data && data.length === 0 && (
        <p className="empty">
          Todavía no tenés ningún modelo. Empezá importando una factura que ya emitiste.
        </p>
      )}
    </div>
  )
}

function TemplateTile({
  template,
  armed,
  onArm,
  onDisarm,
  onDeleted,
}: {
  template: InvoiceTemplate
  armed: boolean
  onArm: () => void
  onDisarm: () => void
  onDeleted: () => void
}) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const longPress = useLongPress(onArm)

  async function remove() {
    setBusy(true)
    setError(undefined)
    try {
      await api.delete<void>(`/invoice-templates/${template.id}`)
      onDeleted()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo eliminar.')
      setBusy(false)
    }
  }

  if (armed) {
    // Dos botones con su nombre escrito, y no el tacho de dos pasos de las listas. Sostener el
    // dedo medio segundo ya fue el paso deliberado; lo que falta es un objetivo grande y sin
    // ambigüedad, que en una tarjeta de 150 px no lo da un ícono.
    return (
      <div className="tile armed">
        <span className="tile-name">{template.name}</span>
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

  // Es un `<button>` y no un `<Link>`: `useLongPress` necesita frenar el click que el
  // navegador manda al soltar el dedo, y sobre un ancla eso significa además pelearle la
  // navegación por defecto. Con un botón, cancelar el click es todo lo que hay que hacer.
  return (
    <button
      type="button"
      className="tile"
      onClick={() => navigate(`/modelos/${template.id}`)}
      {...longPress}
    >
      <span className="tile-name">{template.name}</span>
    </button>
  )
}
