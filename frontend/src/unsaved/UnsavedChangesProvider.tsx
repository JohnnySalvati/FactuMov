import { useMemo, useState, type ReactNode } from 'react'

import { UnsavedChangesContext, type UnsavedChangesState, type UnsavedEntry } from './context'

/**
 * Guarda cuál formulario está montado y si tiene cambios sin guardar.
 *
 * Hay una sola entrada, no una lista: las pantallas de formulario son rutas, así que nunca hay
 * dos montadas a la vez. Envuelve a `<Routes>` para que lo vean tanto las pantallas —que se
 * registran— como `AppLayout`, que cuelga de esto el guard de navegación y el gesto de
 * deslizar.
 */
export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const [entry, setEntry] = useState<UnsavedEntry | null>(null)
  const value = useMemo<UnsavedChangesState>(
    () => ({ entry, register: setEntry }),
    [entry],
  )
  return (
    <UnsavedChangesContext.Provider value={value}>{children}</UnsavedChangesContext.Provider>
  )
}
