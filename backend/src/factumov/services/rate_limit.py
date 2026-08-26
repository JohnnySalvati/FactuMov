"""Rate limiting en memoria, por proceso.

**Es un piso, no el techo.** Un solo proceso cuenta lo suyo: con N workers el límite
efectivo es N veces el configurado, y con varias máquinas, más todavía. El techo de verdad
va en el borde —`limit_req` de nginx, o un WAF—, exactamente por el mismo motivo por el que
`MAX_UPLOAD_BYTES` no es el límite real de subida. Lo que sí hace esta capa es acotar el
daño desde adentro sin depender de que el despliegue esté bien configurado, y hacerlo con
conocimiento que el borde no tiene: nginx no sabe qué dirección de email viene en el body.

Ventana fija y no deslizante. La fija admite una ráfaga de hasta 2× justo en el borde entre
dos ventanas; la deslizante lo evita guardando el timestamp de cada intento en vez de un
contador. Para lo que se defiende acá —que nadie use el reenvío como mail bomb, ni pruebe
contraseñas de a miles— esa ráfaga no cambia nada, y un contador por clave es lo que hace
que la memoria no crezca con el tráfico.

Sin dependencias nuevas a propósito. `slowapi` daría backends de Redis y headers estándar,
pero acá alcanza un contador y un candado, y el día que haga falta compartir el estado entre
workers lo que se necesita es Redis, no un wrapper.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class _Window:
    started_at: float
    count: int


@dataclass
class RateLimiter:
    """Ventana fija: `limit` intentos cada `window_seconds` por clave."""

    limit: int
    window_seconds: float
    _windows: dict[str, _Window] = field(default_factory=dict)
    # Los endpoints son `def` y no `async def`, así que FastAPI los corre en el threadpool y
    # dos requests pueden tocar el mismo contador a la vez. Sin el candado, el `+= 1` de uno
    # pisa el del otro y el límite se vuelve una sugerencia bajo la carga que justamente
    # tendría que frenar.
    _lock: Lock = field(default_factory=Lock)
    # El reloj es un parámetro y no una llamada directa a `time.monotonic`, para que los
    # tests puedan mover el tiempo en vez de dormir: la ventana real es de una hora. Se
    # inyecta en vez de parchearse porque parchear `time.monotonic` lo cambia para todo el
    # proceso, pytest incluido. `monotonic` y no `time`: no retrocede si alguien le corrige
    # la hora al server, que con un reloj de pared abriría la ventana antes de tiempo.
    clock: Callable[[], float] = time.monotonic

    def check(self, key: str) -> float | None:
        """Registra un intento. Devuelve `None` si pasa, o los segundos que faltan si no.

        Contar y decidir en la misma llamada es lo que evita el error clásico de chequear
        primero y olvidarse de incrementar después en alguna rama.
        """
        now = self.clock()
        with self._lock:
            self._prune(now)
            window = self._windows.get(key)
            if window is None or now - window.started_at >= self.window_seconds:
                self._windows[key] = _Window(started_at=now, count=1)
                return None
            window.count += 1
            if window.count > self.limit:
                return self.window_seconds - (now - window.started_at)
            return None

    def _prune(self, now: float) -> None:
        """Tira las ventanas vencidas para que el dict no crezca con el tráfico.

        Corre adentro del candado, en cada intento. Es O(claves vivas) y suena caro, pero
        las claves vivas son las que actuaron en la última ventana: si esa cantidad llegara
        a ser un problema de CPU, el problema real sería el ataque, no el barrido.
        """
        expired = [
            key
            for key, window in self._windows.items()
            if now - window.started_at >= self.window_seconds
        ]
        for key in expired:
            del self._windows[key]

    def reset(self) -> None:
        """Vacía el estado. Existe para los tests: el limitador es un global de módulo y sin
        esto un test le dejaría el contador cargado al siguiente."""
        with self._lock:
            self._windows.clear()
