import type { ReactNode } from 'react'

/**
 * Los carteles de error, éxito y aviso. Existe para que no haya tres formas distintas de
 * mostrar un error en cuatro pantallas — que es lo que pasa siempre cuando cada una arma su
 * propio `<div style=...>`.
 */
export function Notice({
  kind,
  children,
}: {
  kind: 'error' | 'ok' | 'warn'
  children: ReactNode
}) {
  if (!children) return null
  // `role="alert"` hace que el lector de pantalla lo anuncie al aparecer. Sin eso, quien no
  // ve la pantalla aprieta "Guardar", no pasa nada visible y no se entera de por qué.
  return (
    <div className={`notice ${kind}`} role="alert">
      {children}
    </div>
  )
}
