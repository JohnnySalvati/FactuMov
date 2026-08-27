import { Outlet } from 'react-router'

import { BrandMark, InSoftCredit } from './BrandMark'

/**
 * El marco de las cinco pantallas sin sesión: la marca arriba, la pantalla en el medio y el
 * crédito de InSoft abajo.
 *
 * Es una ruta de layout y no un componente que cada pantalla incluya, por el mismo motivo por
 * el que `RequireAuth` envuelve al grupo en vez de repetirse pantalla por pantalla: la regla
 * escrita una vez no se puede olvidar en la que se agregue mañana, y olvidarse dejaría una
 * pantalla sin marca sin que nada lo marque.
 */
export function PublicLayout() {
  return (
    <div className="public-layout">
      <div className="public-brand">
        <BrandMark size={40} />
      </div>
      <Outlet />
      <InSoftCredit />
    </div>
  )
}
