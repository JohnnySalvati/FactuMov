import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../api/client'

interface State<T> {
  data?: T
  error?: string
  loading: boolean
}

interface Resource<T> extends State<T> {
  /** Volver a pedir. Se llama después de crear, editar o borrar. */
  reload: () => void
}

/**
 * Carga un recurso y lo vuelve a cargar cuando se lo piden.
 *
 * Deliberadamente **sin TanStack Query**. Esa librería resuelve caché compartida entre
 * pantallas, deduplicación de requests en vuelo y revalidación en foco — tres problemas que
 * esta app todavía no tiene: son cuatro pantallas y cada una carga su propia lista. Lo que
 * costaría hoy es una dependencia y un vocabulario nuevo encima de un hook de treinta líneas.
 * Revisar cuando dos pantallas necesiten los mismos datos y empiecen a discrepar.
 *
 * `fetcher` tiene que ser estable (`useCallback`), como cualquier dependencia de un efecto:
 * si se recrea en cada render, el efecto corre en loop. **Y tiene que ser el mismo recurso
 * siempre**: este hook no resetea el estado cuando cambia de identidad, porque acá cada
 * pantalla tiene el suyo fijo.
 */
export function useResource<T>(fetcher: () => Promise<T>): Resource<T> {
  const [state, setState] = useState<State<T>>({ loading: true })
  const [nonce, setNonce] = useState(0)

  // El `loading` se prende acá y no adentro del efecto. Es la diferencia entre marcar el
  // estado desde el evento que lo causó —apretar "Agregar"— y hacerlo desde el efecto, que
  // dispara un render de más por cada carga. Se conserva `data`: mantener la lista vieja
  // mientras llega la nueva evita el parpadeo a vacío.
  const reload = useCallback(() => {
    setState((current) => ({ ...current, loading: true, error: undefined }))
    setNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    fetcher()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false })
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setState({
          error: caught instanceof ApiError ? caught.detail : 'Error inesperado.',
          loading: false,
        })
      })
    // El guard existe porque desmontar mientras carga dejaría un `setState` sobre un
    // componente que ya no está.
    return () => {
      cancelled = true
    }
  }, [fetcher, nonce])

  return { ...state, reload }
}
