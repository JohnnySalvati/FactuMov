import { useState } from 'react'

/**
 * Tacho de basura con confirmación en dos pasos.
 *
 * No usa `window.confirm`: ese diálogo bloquea el hilo entero, no se puede estilar, y en
 * algunos navegadores queda suprimido si el usuario marcó "no mostrar más" — o sea que la
 * confirmación puede desaparecer sin que nadie se entere y el próximo click borre directo.
 * Dos pasos in-place es más código y no tiene esa falla.
 *
 * El error se muestra acá adentro y no en el padre a propósito: el 409 de "tiene modelos
 * asociados" es sobre *esta* fila, y mostrarlo arriba de la tabla obligaría al usuario a
 * adivinar cuál de todas se quejó.
 */
export function DeleteButton({
  onDelete,
  confirmLabel = '¿Eliminar?',
  title = 'Eliminar',
}: {
  onDelete: () => Promise<void>
  confirmLabel?: string
  title?: string
}) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  async function confirm() {
    setBusy(true)
    setError(undefined)
    try {
      await onDelete()
      // No hay `setAsking(false)` en el camino feliz: la fila desaparece con el reload, así
      // que tocar estado de un componente que se está por desmontar no aporta nada.
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'No se pudo eliminar.')
      setAsking(false)
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return (
      <span className="delete-error">
        {error}{' '}
        <button className="link" onClick={() => setError(undefined)}>
          Cerrar
        </button>
      </span>
    )
  }

  if (asking) {
    return (
      <span className="confirm-group">
        <span className="muted">{confirmLabel}</span>
        <button className="danger" onClick={confirm} disabled={busy}>
          {busy ? 'Eliminando…' : 'Sí'}
        </button>
        <button className="secondary" onClick={() => setAsking(false)} disabled={busy}>
          No
        </button>
      </span>
    )
  }

  return (
    <button
      className="icon"
      onClick={() => setAsking(true)}
      title={title}
      // El ícono es un emoji, que los lectores de pantalla leen como "cesto de basura" o no
      // leen nada según el sistema. El `aria-label` dice qué hace el botón, no qué dibuja.
      aria-label={title}
    >
      🗑
    </button>
  )
}
