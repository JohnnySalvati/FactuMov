import { createContext } from 'react'

/**
 * Lo que una pantalla de formulario le declara al guard de navegación: si tiene ediciones sin
 * guardar y cómo persistirlas.
 *
 * `save` **tiene que rechazar** si no se pudo guardar. El guard lo espera para decidir si deja
 * salir: si se tragara el error, "Guardar y salir" navegaría igual y se perderían los cambios
 * que no entraron.
 */
export interface UnsavedEntry {
  dirty: boolean
  save: () => Promise<void>
}

export interface UnsavedChangesState {
  /** La pantalla montada ahora, o `null` si la que está no es un formulario con guard. */
  entry: UnsavedEntry | null
  register: (entry: UnsavedEntry | null) => void
}

/**
 * En archivo aparte del provider y de los hooks, misma razón que `auth/context.ts`: Fast
 * Refresh solo recarga en caliente un módulo que exporta componentes nada más. Mezclarlos hace
 * que cada cambio recargue la página entera y se pierda el formulario que uno estaba probando.
 */
export const UnsavedChangesContext = createContext<UnsavedChangesState | null>(null)
