import { useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import type { PointOfSale, PointsOfSale } from '../api/types'

/**
 * Los cinco finales posibles de "¿qué puntos de venta tiene este CUIT?", que es justo lo que el
 * campo necesita para decidir si muestra una lista o una caja de texto.
 *
 * `ready` con `points` vacío **no** es lo mismo que `notDelegated`: el primero es "ARCA
 * contestó y no hay ninguno dado de alta", el segundo es "ARCA no nos deja preguntar". Los dos
 * terminan en un input libre, pero el cartel que los acompaña manda al usuario a lugares
 * distintos.
 */
export type PointsOfSaleState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; points: PointOfSale[] }
  | { status: 'notDelegated' }
  | { status: 'unavailable' }

/**
 * Trae de ARCA los puntos de venta de una identidad fiscal, y los recuerda mientras la pantalla
 * siga abierta.
 *
 * No usa `useResource` a propósito: ese hook es para un recurso fijo por pantalla y no resetea
 * su estado cuando cambia de identidad — lo dice su propio docstring. Acá el recurso *es* la
 * identidad elegida, que cambia con el selector de arriba del formulario.
 *
 * **La respuesta se guarda en un mapa por identidad y el estado se deriva de ahí en el render.**
 * Esa es la decisión de forma, y resuelve dos cosas de una: no hace falta cancelar los pedidos
 * en vuelo —una respuesta que llega tarde se guarda bajo *su* id y no puede pisar lo que el
 * campo está mostrando— y no queda ningún `setState` sincrónico adentro de un efecto, que es lo
 * que dispara renders en cascada. La alternativa, un solo estado que se resetea al cambiar de
 * identidad, necesita las dos cosas que esto evita.
 *
 * **El caché no es cosmético.** Cada consulta sale a WSFE, tarda segundos y gasta cuota contra
 * el certificado de FactuMov, que es uno solo para todos los usuarios; sin caché, alguien que
 * compara dos CUIT dispara una llamada por cada ida y vuelta. Vive en el estado del hook y no en
 * un módulo para que se muera con la pantalla: un punto de venta recién dado de alta en ARCA
 * aparece volviendo a entrar al editor, sin recargar la app. Por lo mismo se recuerda también el
 * fallo — si ARCA no contestó, reintentar solo por haber cambiado de campo sería martillarlo.
 */
export function usePointsOfSale(fiscalIdentityId: string | null): PointsOfSaleState {
  const [answers, setAnswers] = useState<ReadonlyMap<string, PointsOfSaleState>>(new Map())
  // Los ids que ya se pidieron. Va en un ref y no se deduce de `answers` porque tiene que
  // marcarse **antes** de que llegue la respuesta: si no, cada render mientras el pedido está
  // en vuelo lo volvería a disparar.
  const asked = useRef(new Set<string>())

  useEffect(() => {
    if (fiscalIdentityId === null || asked.current.has(fiscalIdentityId)) return
    asked.current.add(fiscalIdentityId)

    const remember = (answer: PointsOfSaleState) =>
      setAnswers((current) => new Map(current).set(fiscalIdentityId, answer))

    void api
      .get<PointsOfSale>(`/fiscal-identities/${fiscalIdentityId}/points-of-sale`)
      .then((answer) =>
        remember(
          answer.granted ? { status: 'ready', points: answer.points } : { status: 'notDelegated' },
        ),
      )
      .catch(() => remember({ status: 'unavailable' }))
  }, [fiscalIdentityId])

  if (fiscalIdentityId === null) return { status: 'idle' }
  // Sin entrada todavía es "cargando": el efecto la pidió, o está por pedirla en este mismo
  // ciclo. No hay un sexto estado "ni siquiera empezó" porque no habría nada distinto que
  // mostrar en él.
  return answers.get(fiscalIdentityId) ?? { status: 'loading' }
}
