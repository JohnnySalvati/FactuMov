import { useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'

/** Cuánto tiene que recorrer el dedo. En una pantalla de 360 px son unos 17 %: lejos de un
 *  toque mal apoyado, y cerca de la mitad de lo que se necesita para pasar de página en un
 *  lector, que es el gesto con el que se lo compara. */
const DISTANCE_PX = 60

/** Cuánto más horizontal que vertical tiene que ser el trazo. Sin esto, desplazar la lista en
 *  diagonal —que es como se desplaza de verdad, nadie mueve el dedo en una recta— cambia de
 *  sección a mitad de scroll. */
const RATIO = 1.5

/** Más lento que esto no es un swipe: es un dedo apoyado que se fue moviendo. Ese caso tiene
 *  que quedar afuera porque compite con el "mantener apretado" de las tarjetas. */
const MAX_MS = 700

type Direction = 'forward' | 'back'

/**
 * Cambiar de sección deslizando el dedo, entre las rutas de `paths` y en ese orden.
 *
 * **Solo con el dedo** (`pointerType === 'touch'`). Con un mouse, arrastrar sobre la página es
 * seleccionar texto, y en una pantalla grande las pestañas están siempre a la vista: el gesto
 * resolvería un problema que ahí no existe y rompería la selección, que sí.
 *
 * **Es un atajo y no la única puerta**, igual que el "mantener apretado" de las tarjetas: la
 * barra de pestañas sigue arriba, visible y sticky. Un gesto invisible no puede ser el único
 * camino a nada — nadie lo descubre, y quien no lo descubre se queda sin la función.
 *
 * **Sin vuelta al principio**: desde la última sección, seguir deslizando no hace nada. Con
 * `wrap`, un swipe de más te manda al otro extremo de la app y el borde deja de sentirse como
 * un borde. Es lo mismo que hacen las pestañas de Android.
 *
 * Devuelve los handlers para desparramar sobre el contenedor, y el par `key`/`className` con
 * el que ese contenedor anima la entrada de la pantalla nueva.
 */
export function useSwipeNav(paths: readonly string[]) {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  // Refs y no estado: solo se leen desde los handlers, y ninguna tiene que provocar un render.
  const start = useRef<{ x: number; y: number; t: number } | undefined>(undefined)
  const swiped = useRef(false)

  // Esto sí es estado, porque es lo que dispara la animación. El `nonce` existe para que dos
  // swipes seguidos en la misma dirección vuelvan a animar: sin él, la clase no cambia, el
  // contenedor no se vuelve a montar y el segundo swipe entra sin moverse.
  const [enter, setEnter] = useState<{ dir: Direction; nonce: number }>()

  function go(step: 1 | -1) {
    const index = paths.indexOf(pathname)
    // -1 es una ruta que no es una sección: un modelo abierto, el editor de un cliente, la
    // pantalla de emitir. Ahí el gesto no hace nada a propósito — son pantallas con formularios
    // a medio llenar, y salirse de una con un dedo mal apoyado pierde lo escrito.
    if (index === -1) return false
    const next = paths[index + step]
    if (next === undefined) return false
    setEnter((current) => ({
      dir: step === 1 ? 'forward' : 'back',
      nonce: (current?.nonce ?? 0) + 1,
    }))
    navigate(next)
    return true
  }

  const swipeProps = {
    onPointerDown(event: PointerEvent) {
      if (event.pointerType !== 'touch') return
      swiped.current = false
      start.current = { x: event.clientX, y: event.clientY, t: event.timeStamp }
    },

    onPointerUp(event: PointerEvent) {
      const origin = start.current
      start.current = undefined
      if (origin === undefined) return

      const dx = event.clientX - origin.x
      const dy = event.clientY - origin.y
      if (event.timeStamp - origin.t > MAX_MS) return
      if (Math.abs(dx) < DISTANCE_PX) return
      if (Math.abs(dx) < Math.abs(dy) * RATIO) return

      // El dedo va a la izquierda y el contenido avanza, como al pasar la hoja de un libro.
      swiped.current = go(dx < 0 ? 1 : -1)
    },

    /**
     * El navegador manda `pointercancel` en cuanto decide que el gesto es un desplazamiento
     * vertical y se queda con el puntero. Sin esto, el `pointerup` nunca llega, `start` queda
     * cargado, y el próximo toque en cualquier lado se mide contra un origen viejo.
     */
    onPointerCancel() {
      start.current = undefined
    },

    /**
     * Un swipe que arranca **arriba de una tarjeta** termina en un `click` sobre esa tarjeta:
     * el gesto cambiaría de sección y además entraría al modelo que quedó abajo del dedo. Va en
     * fase de captura, que baja desde acá antes de llegar al `onClick` de la tarjeta.
     */
    onClickCapture(event: MouseEvent) {
      if (!swiped.current) return
      event.preventDefault()
      event.stopPropagation()
      swiped.current = false
    },
  }

  return {
    swipeProps,
    /** Cambia en cada swipe y solo en un swipe: remonta el contenedor para que la animación
     *  vuelva a correr, y deja quietas las navegaciones que salen de las pestañas. */
    enterKey: enter?.nonce ?? 0,
    enterClass: enter === undefined ? '' : `app-main-${enter.dir}`,
  }
}
