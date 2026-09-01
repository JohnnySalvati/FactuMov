import { useContext } from 'react'

import { SubscriptionContext } from './context'

export function useSubscription() {
  const state = useContext(SubscriptionContext)
  if (state === null) {
    throw new Error('useSubscription necesita estar adentro de <SubscriptionProvider>')
  }
  return state
}
