import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiError, api } from '../api/client'
import type { User } from '../api/types'
import { AuthContext, type AuthState } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined)

  // La cookie es `httpOnly`, así que el JS no la puede leer: la única forma de saber si hay
  // sesión es preguntarle al backend. Un flag en `localStorage` sería más rápido y mentiría
  // en los dos casos que importan — la sesión revocada desde otra pestaña, y la vencida.
  useEffect(() => {
    let cancelled = false
    api
      .get<User>('/auth/me')
      .then((me) => {
        if (!cancelled) setUser(me)
      })
      .catch(() => {
        // Un 401 acá es lo normal —visitante sin sesión—, no un problema que reportar.
        if (!cancelled) setUser(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    // El backend contesta el usuario y setea la cookie en la misma respuesta, así que no
    // hace falta un `/auth/me` después.
    setUser(await api.post<User>('/auth/login', { email, password }))
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.post<void>('/auth/logout')
    } catch (error) {
      // Si la sesión ya estaba muerta el backend contesta 401. Para el usuario que apretó
      // "salir" el resultado es el mismo, así que se sigue de largo y se limpia igual;
      // dejarlo adentro por un error de red sería peor.
      if (!(error instanceof ApiError)) throw error
    }
    setUser(null)
  }, [])

  const value = useMemo<AuthState>(() => ({ user, login, logout }), [user, login, logout])

  return <AuthContext value={value}>{children}</AuthContext>
}
