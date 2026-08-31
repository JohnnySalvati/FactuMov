import { useState } from 'react'
import { useBlocker, type Blocker } from 'react-router'

import { ApiError } from '../api/client'
import { Notice } from '../components/Notice'
import { useUnsavedChanges } from './hooks'
import type { UnsavedEntry } from './context'

/**
 * Frena la salida de un formulario con cambios sin guardar y pregunta qué hacer.
 *
 * Se monta **una sola vez**, en `AppLayout`: `useBlocker` admite un solo bloqueo a la vez, y
 * cubre todo —los links, el botón "atrás", `navigate()` y el gesto de deslizar—, porque todo
 * eso pasa por el router. Cada pantalla de formulario solo declara si tiene cambios
 * (`useRegisterUnsavedChanges`); acá se decide.
 *
 * No es un `window.confirm`: bloquea el hilo, no se puede estilar, y en algunos navegadores
 * queda suprimido si el usuario marcó "no mostrar más" — o sea que la confirmación
 * desaparecería sin que nadie se entere. Es el mismo criterio que el borrado de las tarjetas y
 * la pantalla de emisión.
 *
 * **Solo la edición llega acá.** El alta de un cliente o una identidad navega sola al terminar
 * y no se registra; deslizar sobre `/clientes/nuevo` sigue sin hacer nada, como antes.
 */
export function UnsavedChangesGuard() {
  const { entry } = useUnsavedChanges()
  const blocker = useBlocker(entry?.dirty ?? false)

  if (blocker.state !== 'blocked') return null

  // El diálogo va en un componente aparte con `key` en el intento de navegación: así su estado
  // —"guardando", el error— arranca limpio en cada bloqueo, sin un efecto que lo resetee.
  return (
    <UnsavedDialog key={blocker.location.key} blocker={blocker} save={entry?.save ?? null} />
  )
}

function UnsavedDialog({
  blocker,
  save,
}: {
  blocker: Extract<Blocker, { state: 'blocked' }>
  save: UnsavedEntry['save'] | null
}) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string>()

  async function saveAndLeave() {
    if (save === null) {
      blocker.proceed()
      return
    }
    setSaving(true)
    setError(undefined)
    try {
      await save()
      blocker.proceed()
    } catch (caught) {
      // El detalle del backend si lo hay ("Numero de documento/CUIT duplicado"), o un texto
      // genérico: el error queda a la vista dentro del cartel, no tapado detrás de él.
      setError(
        caught instanceof ApiError ? caught.detail : 'No se pudo guardar. Revisá los datos.',
      )
      setSaving(false)
    }
  }

  return (
    <div className="sheet-backdrop" role="dialog" aria-modal="true" aria-labelledby="unsaved-title">
      <div className="dialog">
        <h2 id="unsaved-title">Tenés cambios sin guardar</h2>
        <p className="muted">Si salís de esta pantalla ahora, se pierde lo que editaste.</p>

        <Notice kind="error">{error}</Notice>

        <button onClick={saveAndLeave} disabled={saving}>
          {saving ? 'Guardando…' : 'Guardar y salir'}
        </button>
        <button className="secondary" onClick={() => blocker.proceed()} disabled={saving}>
          Salir sin guardar
        </button>
        <button className="link" onClick={() => blocker.reset()} disabled={saving}>
          Seguir editando
        </button>
      </div>
    </div>
  )
}
