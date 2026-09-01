import { useCallback, useEffect, useMemo } from 'react'
import { Outlet } from 'react-router'

import { api } from '../api/client'
import type { Subscription } from '../api/types'
import { useResource } from '../hooks/useResource'
import { setVoiceAllowed } from '../speak'
import { SubscriptionContext, type SubscriptionState } from './context'

/**
 * El plan de la cuenta, pedido una vez y compartido por todas las pantallas con sesión.
 *
 * **Es un contexto y no un `useResource` por pantalla**, que es como se cargan los demás
 * recursos de la app. La diferencia es que ninguna pantalla viene a *ver* el plan: lo
 * consultan seis lugares que fueron a hacer otra cosa —el aviso de cupo de la barra, el alta
 * de identidad fiscal, la pantalla de emitir, los dos micrófonos y la pantalla del plan— y con
 * un `useResource` en cada uno eso serían seis `GET /subscription` por vuelta, tres de ellos
 * sobre pantallas que se abren cien veces por semana. `useResource` sigue siendo el que carga
 * *el* recurso de una pantalla; esto es un dato de la cuenta, como la sesión.
 *
 * **Es una ruta de layout y no un envoltorio de `<App>`**, al revés que `AuthProvider`. Está
 * puesto adentro de `RequireAuth` porque `GET /subscription` exige sesión: montado más afuera
 * dispararía un 401 en cada visita del que no entró todavía, incluidas las pantallas públicas
 * de confirmar el mail y restablecer la contraseña.
 *
 * Un fracaso de la consulta lo muestra solo la pantalla del plan — ver `error` en
 * `context.ts`.
 */
export function SubscriptionProvider() {
  const fetcher = useCallback(() => api.get<Subscription>('/subscription'), [])
  const { data, error, reload } = useResource(fetcher)

  // La voz es lo único que el backend no puede hacer cumplir: corre entera en el navegador,
  // así que la llave la tiene que bajar alguien de este lado. Va acá y no en cada componente
  // que habla porque `say()` se llama desde efectos y callbacks que no tienen contexto —la
  // lectura del comprobante en la pantalla de emitir, la respuesta de cada dictado—, y
  // pasársela a mano por seis lugares sería garantizar que uno quede sin enterarse.
  useEffect(() => {
    setVoiceAllowed(data?.voice_enabled ?? true)
  }, [data])

  const value = useMemo<SubscriptionState>(
    () => ({ plan: data, error, reload }),
    [data, error, reload],
  )

  return (
    <SubscriptionContext value={value}>
      <Outlet />
    </SubscriptionContext>
  )
}
