import { useContext } from 'react'

import { AuthContext } from './context'

export function useAuth() {
  const state = useContext(AuthContext)
  // Tirar el error en vez de devolver `null` convierte "me olvidé el provider" en un mensaje
  // que dice qué pasó, en vez de en un `Cannot read properties of null` diez líneas después.
  if (state === null) throw new Error('useAuth necesita estar adentro de <AuthProvider>')
  return state
}
