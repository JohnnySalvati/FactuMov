import { useRef, type PointerEvent, type MouseEvent } from 'react'

/** Cuánto hay que sostener. 500 ms es lo que usan Android y iOS para su propio menú
 *  contextual: más corto se dispara al desplazar, más largo se siente colgado. */
const HOLD_MS = 500

/** Si el dedo se movió más que esto, el gesto era un scroll y no un "mantener apretado".
 *  Sin esta tolerancia, arrastrar la lista abre el menú de la tarjeta que quedó abajo. */
const MOVE_TOLERANCE_PX = 10

/**
 * "Mantener apretado" sobre un elemento, con la salida equivalente para mouse y teclado.
 *
 * Se usa con eventos de puntero y no con `touchstart`/`mousedown`: `pointer*` cubre dedo,
 * mouse y lápiz con un solo juego de handlers, y sobre todo evita el clásico de que el mismo
 * gesto dispare la rama táctil y la de mouse (los navegadores emiten eventos de mouse
 * sintéticos después de un toque).
 *
 * **El `contextmenu` no es un extra.** Sostener el dedo es invisible con un mouse y no existe
 * con un teclado, así que el gesto no puede ser la única puerta a lo que abre. El evento
 * `contextmenu` es exactamente el equivalente en las otras dos entradas: lo emite el botón
 * derecho, la tecla Menú y Shift+F10. Con eso, la misma acción llega desde el dedo, desde el
 * mouse y desde el teclado sin escribir tres caminos.
 *
 * Los handlers se rearman en cada render y no se memorizan: son props de un nodo del DOM, así
 * que su identidad no dispara ningún trabajo. Memorizarlos obligaría a guardar el callback en
 * una ref y escribirla durante el render, que es justo lo que React desaconseja.
 *
 * Devuelve props para desparramar (`{...longPress}`) sobre el elemento.
 */
export function useLongPress(onLongPress: () => void) {
  // Estas tres sí son refs: sobreviven al render y solo se leen desde los handlers.
  const timer = useRef<number | undefined>(undefined)
  const origin = useRef<{ x: number; y: number } | undefined>(undefined)
  const fired = useRef(false)

  function clear() {
    if (timer.current !== undefined) {
      window.clearTimeout(timer.current)
      timer.current = undefined
    }
  }

  return {
    onPointerDown(event: PointerEvent) {
      // Solo el botón principal del mouse: el derecho ya tiene su camino por `contextmenu`.
      if (event.pointerType === 'mouse' && event.button !== 0) return
      fired.current = false
      origin.current = { x: event.clientX, y: event.clientY }
      clear()
      timer.current = window.setTimeout(() => {
        timer.current = undefined
        fired.current = true
        // Android confirma el gesto con una vibración cortita y es la única señal de que
        // "ya está, soltá". iOS ignora la llamada, así que no hace falta detectar nada.
        navigator.vibrate?.(15)
        onLongPress()
      }, HOLD_MS)
    },
    onPointerMove(event: PointerEvent) {
      if (timer.current === undefined || origin.current === undefined) return
      const dx = event.clientX - origin.current.x
      const dy = event.clientY - origin.current.y
      if (Math.hypot(dx, dy) > MOVE_TOLERANCE_PX) clear()
    },
    onPointerUp: clear,
    onPointerCancel: clear,
    onPointerLeave: clear,
    /**
     * Al soltar el dedo el navegador manda igual el `click`, así que sin esto un "mantener
     * apretado" sobre una tarjeta abre el menú **y** entra adentro de la tarjeta. Va en fase
     * de captura para llegar antes que el handler del elemento.
     */
    onClickCapture(event: MouseEvent) {
      if (!fired.current) return
      event.preventDefault()
      event.stopPropagation()
      fired.current = false
    },
    onContextMenu(event: MouseEvent) {
      // El `preventDefault` sirve dos veces: le saca el menú del navegador al botón derecho,
      // y en Android evita que el long press que ya atendimos abra encima el menú del sistema.
      event.preventDefault()
      clear()
      onLongPress()
    },
  }
}
