import { createContext } from 'react'

import type { User } from '../api/types'

export interface AuthState {
  /** `undefined` mientras no se sabe: el primer `GET /auth/me` todavía no volvió. */
  user: User | null | undefined
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

/**
 * En archivo aparte del provider y del hook a propósito: Fast Refresh de Vite solo puede
 * recargar un módulo en caliente si exporta **componentes nada más**. Mezclar el contexto,
 * el provider y el hook en un archivo hace que cada cambio recargue la página entera y se
 * pierda el estado del formulario que uno estaba probando.
 */
export const AuthContext = createContext<AuthState | null>(null)
