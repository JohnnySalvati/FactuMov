import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuth } from '../auth/useAuth'

/**
 * Puerta de las rutas con sesión.
 *
 * **No es seguridad**, es navegación: quien quiera los datos le pega igual a la API, y ahí
 * el que decide es `get_current_user` del backend. Esto solo evita que el usuario sin sesión
 * vea una pantalla que va a cargar vacía y llena de 401.
 *
 * Se aplica al grupo de rutas y no pantalla por pantalla — mismo criterio que el
 * `APIRouter(dependencies=[Depends(get_current_user)])` del backend: la regla escrita una
 * vez no se puede olvidar en la pantalla que se agregue mañana.
 */
export function RequireAuth() {
  const { user } = useAuth()
  const location = useLocation()

  // `undefined` es "todavía no sé", distinto de `null` que es "no hay sesión". Sin esa
  // distinción, un refresh en `/clientes` rebota al login antes de que vuelva `/auth/me`, y
  // el usuario logueado se ve pateado afuera cada vez que recarga.
  if (user === undefined) return <p className="centered muted">Cargando…</p>

  if (user === null) {
    // `state` guarda a dónde quería ir, para volver ahí después de entrar. `replace` evita
    // que el login quede en el historial.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
