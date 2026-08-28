import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { BrandMark } from './BrandMark'
import { useAuth } from '../auth/useAuth'
import { useSwipeNav } from '../hooks/useSwipeNav'

/**
 * Las cuatro secciones, **en el orden en que están en la barra de arriba**, que es el orden en
 * el que las recorre el gesto de deslizar. Si se agrega una pestaña hay que sumarla en los dos
 * lados: acá y en el `<nav>` de más abajo, que están en este mismo archivo justamente por eso.
 */
const SECTION_PATHS = ['/', '/facturas', '/identidades', '/clientes']

/** El marco de las pantallas con sesión: barra arriba y `<Outlet />` para la ruta activa. */
export function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  async function onLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  // Los modelos viven en dos rutas —la grilla en `/` y cada uno en `/modelos/…`— así que el
  // `isActive` de `NavLink` no alcanza: con `end` se apagaría adentro de un modelo, y sin
  // `end` la raíz haría match con todas las rutas y la pestaña quedaría prendida siempre.
  const inTemplates = pathname === '/' || pathname.startsWith('/modelos')

  const { swipeProps, enterKey, enterClass } = useSwipeNav(SECTION_PATHS)

  return (
    <>
      <header className="app-header">
        <span className="app-brand">
          <BrandMark />
        </span>
        <nav className="app-nav">
          <NavLink to="/" className={inTemplates ? 'active' : ''}>
            Modelos
          </NavLink>
          {/* `NavLink` pone la clase `active` sola según la ruta; con `Link` habría que
              comparar `useLocation` a mano en cada ítem. Las facturas van segundas —después de
              los modelos y antes de la configuración— porque emitir y después mirar lo emitido
              es el recorrido de todas las semanas; identidades y clientes se tocan al empezar
              y después casi nunca. */}
          <NavLink to="/facturas" className={({ isActive }) => (isActive ? 'active' : '')}>
            Facturas
          </NavLink>
          <NavLink to="/identidades" className={({ isActive }) => (isActive ? 'active' : '')}>
            Identidades
          </NavLink>
          <NavLink to="/clientes" className={({ isActive }) => (isActive ? 'active' : '')}>
            Clientes
          </NavLink>
        </nav>
        <div className="app-user">
          <span className="app-user-email">{user?.email}</span>
          <button className="secondary" onClick={onLogout}>
            Salir
          </button>
        </div>
      </header>
      {/* El `<Outlet />` va adentro de un contenedor propio y no suelto: el gesto necesita un
          elemento del que colgarse que cubra la pantalla entera y que no sea la barra —
          deslizar sobre las pestañas tiene que seguir siendo tocar una pestaña. */}
      <div className={`app-main ${enterClass}`} key={enterKey} {...swipeProps}>
        <Outlet />
      </div>
    </>
  )
}
