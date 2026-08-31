import { useContext, useEffect, useRef } from 'react'

import { UnsavedChangesContext, type UnsavedChangesState } from './context'

export function useUnsavedChanges(): UnsavedChangesState {
  const state = useContext(UnsavedChangesContext)
  // Tirar el error en vez de devolver `null` convierte "me olvidé el provider" en un mensaje
  // que dice qué pasó — mismo criterio que `useAuth`.
  if (state === null) {
    throw new Error('useUnsavedChanges necesita estar adentro de <UnsavedChangesProvider>')
  }
  return state
}

/**
 * Una pantalla de formulario declara acá si tiene cambios sin guardar y cómo guardarlos. El
 * guard de navegación (uno solo, en `AppLayout`) y el gesto de deslizar leen esto.
 *
 * `save` cierra sobre el estado del formulario, así que cambia de identidad en cada tecla; se
 * guarda en una ref para no re-registrar en cada render, y el guard llama siempre la última.
 * El registro se rehace solo cuando cambia `dirty`, que es el único dato que a los que leen
 * les importa.
 */
export function useRegisterUnsavedChanges(dirty: boolean, save: () => Promise<void>): void {
  const { register } = useUnsavedChanges()

  const saveRef = useRef(save)
  // La ref se actualiza en un efecto, no en el render: para cuando el guard llame `save` —un
  // click del usuario— el efecto ya corrió y apunta a la última versión.
  useEffect(() => {
    saveRef.current = save
  })

  useEffect(() => {
    register({ dirty, save: () => saveRef.current() })
  }, [dirty, register])

  // Cleanup solo al desmontar: al salir de la pantalla no hay más formulario que cuidar.
  useEffect(() => {
    return () => register(null)
  }, [register])
}
