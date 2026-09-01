import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { BrandMark } from './BrandMark'
import { PlanBanner } from './PlanBanner'
import { useAuth } from '../auth/useAuth'
import { useSwipeNav, type SwipeSection } from '../hooks/useSwipeNav'
import { UnsavedChangesGuard } from '../unsaved/UnsavedChangesGuard'

/**
 * Las cuatro secciones, **en el orden en que están en la barra de arriba**, que es el orden en
 * el que las recorre el gesto de deslizar. Si se agrega una pestaña hay que sumarla en los dos
 * lados: acá y en el `<nav>` de más abajo, que están en este mismo archivo justamente por eso.
 *
 * `owns` es lo que hace que el gesto también funcione **adentro** de una sección: parado en
 * `/clientes/abc` deslizar te lleva a Identidades o al borde, igual que si estuvieras en la
 * grilla. Las pantallas de alta (`/clientes/nuevo`, `/identidades/nueva`, `/modelos/nuevo`)
 * quedan afuera a propósito: navegan solas al terminar y no tienen guard de cambios, así que
 * deslizar ahí seguiría perdiendo lo tipeado sin preguntar.
 */
const SECTIONS: readonly SwipeSection[] = [
  {
    to: '/',
    owns: (p) => p === '/' || (p.startsWith('/modelos/') && p !== '/modelos/nuevo'),
  },
  { to: '/facturas', owns: (p) => p === '/facturas' || p.startsWith('/facturas/') },
  {
    to: '/identidades',
    owns: (p) => p === '/identidades' || (p.startsWith('/identidades/') && p !== '/identidades/nueva'),
  },
  {
    to: '/clientes',
    owns: (p) => p === '/clientes' || (p.startsWith('/clientes/') && p !== '/clientes/nuevo'),
  },
]

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

  const { swipeProps, enterKey, enterClass } = useSwipeNav(SECTIONS)

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
          {/* Los ajustes no son una quinta pestaña: se tocan una vez y le cobrarían ancho a
              las cuatro que se usan todas las semanas. El engranaje va acá y no colgado del
              mail porque el mail está oculto en el celular, que es el caso principal.
              `aria-label` porque el contenido es un símbolo: sin eso el lector de pantalla
              anuncia "engranaje" o directamente nada. */}
          <NavLink
            to="/ajustes"
            className={({ isActive }) => `app-settings ${isActive ? 'active' : ''}`}
            aria-label="Ajustes"
            title="Ajustes"
          >
            ⚙
          </NavLink>
          <button className="secondary" onClick={onLogout}>
            Salir
          </button>
        </div>
      </header>
      {/* El aviso de cupo va abajo de la barra y arriba del contenido, o sea en el layout y
          no en una pantalla: el que se está por quedar sin comprobantes tiene que enterarse
          esté donde esté, y no al apretar "Emitir". Casi siempre no dibuja nada. */}
      <PlanBanner />
      {/* El `<Outlet />` va adentro de un contenedor propio y no suelto: el gesto necesita un
          elemento del que colgarse que cubra la pantalla entera y que no sea la barra —
          deslizar sobre las pestañas tiene que seguir siendo tocar una pestaña. */}
      <div className={`app-main ${enterClass}`} key={enterKey} {...swipeProps}>
        <Outlet />
      </div>
      {/* El cartel de "cambios sin guardar": una sola instancia para toda la app, porque
          `useBlocker` admite un solo bloqueo a la vez. */}
      <UnsavedChangesGuard />
    </>
  )
}
