import { NavLink, Outlet, useNavigate } from 'react-router'

import { useAuth } from '../auth/useAuth'

/** El marco de las pantallas con sesión: barra arriba y `<Outlet />` para la ruta activa. */
export function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function onLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <>
      <header className="app-header">
        <span className="app-brand">FactuMov</span>
        <nav className="app-nav">
          {/* `NavLink` pone la clase `active` sola según la ruta; con `Link` habría que
              comparar `useLocation` a mano en cada ítem. */}
          <NavLink to="/identidades" className={({ isActive }) => (isActive ? 'active' : '')}>
            Identidades fiscales
          </NavLink>
          <NavLink to="/clientes" className={({ isActive }) => (isActive ? 'active' : '')}>
            Clientes
          </NavLink>
        </nav>
        <div className="app-user">
          <span>{user?.email}</span>
          <button className="secondary" onClick={onLogout}>
            Salir
          </button>
        </div>
      </header>
      <Outlet />
    </>
  )
}
