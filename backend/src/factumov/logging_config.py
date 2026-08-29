"""La configuración de logging de la app: el único lugar donde se decide qué se ve.

Existe por una falla que costó una sesión entera de diagnóstico. Uvicorn configura **sus**
loggers y no toca el root, así que hasta acá todo lo que la app logueaba con `logger.info`
salía por `logging.lastResort` — el handler de emergencia de la stdlib, que imprime a stderr
**de WARNING para arriba**. O sea que los INFO no se imprimían en ninguna parte.

Eso no era un detalle cosmético: el barrido de delegaciones anuncia su camino feliz con dos
`logger.info` (`main.py` y `services/delegation_watch.py`), y sin ellos "el barrido corrió y no
encontró nada" y "el barrido nunca arrancó" se ven exactamente igual — en silencio. La única
señal que quedaba era la de los fallos, así que la app solo sabía contar lo que salía mal.
"""

import logging
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict

# El mismo orden de campos que la línea de uvicorn (nivel, después el mensaje), con el nombre
# del logger en el medio: en un `docker compose logs app` las dos fuentes se leen mezcladas y
# lo que hay que poder distinguir de un vistazo es de cuál viene cada renglón.
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Marca sobre nuestro propio handler. `configure_logging` puede llamarse más de una vez —el
# lifespan corre una vez por proceso, pero un test que levante la app dos veces no—, y sin esto
# cada llamada agregaría un handler más y cada línea saldría duplicada.
_MARKER = "_factumov_handler"


class LogSettings(BaseSettings):
    """`extra="ignore"` por lo mismo que las otras tres: el `.env` es uno solo para toda la app."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # INFO y no WARNING: el default tiene que ser el que hace visible el trabajo de fondo, que
    # es justamente lo que no se veía. Los niveles de la app están elegidos para eso —el camino
    # feliz es INFO y lo raro es WARNING o ERROR—, así que INFO no es ruido, es la bitácora.
    log_level: str = "INFO"


def configure_logging() -> None:
    """Manda los logs de `factumov` a stderr, con el nivel de `LOG_LEVEL`.

    **El nivel se pone en el logger `factumov` y no en el root**, y esa es la decisión. Poner el
    root en INFO prendería también el INFO de zeep, urllib3 y SQLAlchemy, y el resultado sería
    que los dos renglones que importan queden enterrados — o sea el mismo problema de antes con
    otra forma. El root queda en WARNING, que es el piso razonable para las librerías.

    Que eso alcance depende de una sutileza de `logging` que conviene dejar escrita: al
    propagar, un record ya admitido por el logger que lo emitió **no vuelve a chequear el nivel
    de los loggers de arriba**, solo el de los handlers. Por eso un `factumov` en INFO alcanza
    para que el handler del root imprima sus INFO, con el root en WARNING.

    A stderr y no a stdout, que es a donde escribe uvicorn: así el orden de los renglones entre
    las dos fuentes se conserva y no quedan dos streams bufferados por separado.
    """
    root = logging.getLogger()
    if any(getattr(handler, _MARKER, False) for handler in root.handlers):
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    setattr(handler, _MARKER, True)

    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    logging.getLogger("factumov").setLevel(LogSettings().log_level.upper())
