import { createContext } from 'react'

import type { Subscription } from '../api/types'

export interface SubscriptionState {
  /** El plan de la cuenta, o `undefined` mientras el primer `GET /subscription` no volvió. */
  plan: Subscription | undefined
  /**
   * Por qué no se pudo traer, si no se pudo.
   *
   * **Lo muestra una sola pantalla**: la del plan, que es la única que vino a mirarlo. Los
   * demás consumidores —el aviso de cupo de la barra, los micrófonos, el alta de identidad
   * fiscal— tienen que ignorarlo y comportarse como si no supieran: pintar un cartel rojo en
   * la grilla de modelos por un dato accesorio a lo que el usuario fue a hacer sería peor que
   * no avisar de un cupo, y esconderle la voz al Pro por un error de red sería sacarle algo
   * que pagó. Cuando no se sabe, el aviso no aparece y la voz queda prendida.
   */
  error: string | undefined
  /**
   * Volver a preguntar. Lo llama quien acaba de mover un contador —emitir gasta cupo, dar de
   * baja cambia el estado— porque este contexto vive mientras dure la sesión y no se recarga
   * solo al cambiar de pantalla.
   */
  reload: () => void
}

/**
 * En archivo aparte del provider y del hook, igual que `auth/context.ts`: Fast Refresh solo
 * recarga en caliente un módulo que exporta componentes y nada más.
 */
export const SubscriptionContext = createContext<SubscriptionState | null>(null)
