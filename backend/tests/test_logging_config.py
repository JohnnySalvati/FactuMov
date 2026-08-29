"""Que los logs de la app efectivamente se impriman.

Parece una perogrullada y es la regresión concreta que motivó el módulo: uvicorn configura sus
propios loggers y no toca el root, así que hasta el 2026-08-29 todo lo que la app logueaba salía
por `logging.lastResort` —el handler de emergencia de la stdlib, de WARNING para arriba— y los
`logger.info` no se imprimían en ninguna parte. El barrido de delegaciones anuncia su camino
feliz con dos de ellos, o sea que "corrió y no encontró nada" y "nunca arrancó" se veían igual.

Los tests no miran el formato ni el destino: miran lo único que se puede romper en silencio, que
es si un record llega o no llega a los handlers.
"""

import logging

import pytest

from factumov import logging_config


class Spy(logging.Handler):
    """Un handler que se queda con lo que le llega. `NOTSET` a propósito: lo que se está
    midiendo es qué dejan pasar los *loggers*, así que el handler no puede filtrar nada."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def fresh_config():
    """Deshace la configuración de la app y la repone al terminar.

    Toca **solo** el handler propio —el que lleva la marca de `logging_config`— y los dos
    niveles que ese módulo escribe. Vaciar `root.handlers` sería más simple y se llevaría puesto
    el handler con el que pytest captura los logs, que se monta y se desmonta alrededor de cada
    fase del test.

    Hace falta porque `configure_logging` es idempotente: sin esto, el primer test de la suite
    que levante el lifespan la deja configurada y acá no se estaría probando nada.
    """
    root = logging.getLogger()
    app = logging.getLogger("factumov")
    ours = [h for h in root.handlers if getattr(h, logging_config._MARKER, False)]
    levels = (root.level, app.level)

    for handler in ours:
        root.removeHandler(handler)
    yield root
    for handler in root.handlers[:]:
        if getattr(handler, logging_config._MARKER, False):
            root.removeHandler(handler)
    for handler in ours:
        root.addHandler(handler)
    root.setLevel(levels[0])
    app.setLevel(levels[1])


def test_an_info_of_the_app_reaches_the_handlers(fresh_config):
    """El caso que no funcionaba: el renglón del barrido diciendo que verificó una delegación."""
    logging_config.configure_logging()
    spy = Spy()
    fresh_config.addHandler(spy)

    logging.getLogger("factumov.services.delegation_watch").info("quedó verificada")

    assert [record.getMessage() for record in spy.records] == ["quedó verificada"]


def test_an_info_of_a_library_does_not(fresh_config):
    """El root queda en WARNING, y eso también es la decisión.

    Prender el INFO global encendería el de zeep, urllib3 y SQLAlchemy, y los dos renglones que
    importan quedarían enterrados: el mismo problema de antes con la forma invertida.
    """
    logging_config.configure_logging()
    spy = Spy()
    fresh_config.addHandler(spy)

    logging.getLogger("zeep.transports").info("bajando el WSDL")

    assert spy.records == []


def test_a_warning_of_a_library_does(fresh_config):
    """Bajar el ruido no puede ser apagar las librerías: WARNING para arriba sigue pasando."""
    logging_config.configure_logging()
    spy = Spy()
    fresh_config.addHandler(spy)

    logging.getLogger("zeep.transports").warning("el WSDL contestó 500")

    assert len(spy.records) == 1


def test_configuring_twice_does_not_duplicate_every_line(fresh_config):
    """El lifespan corre una vez por proceso; un test que levante la app dos veces, no."""
    logging_config.configure_logging()
    logging_config.configure_logging()

    ours = [h for h in fresh_config.handlers if getattr(h, logging_config._MARKER, False)]
    assert len(ours) == 1


def test_the_level_can_be_lowered_from_the_env(fresh_config, monkeypatch):
    """`LOG_LEVEL` existe para el día que haga falta el DEBUG de una conversación con ARCA."""
    monkeypatch.setenv("LOG_LEVEL", "warning")
    logging_config.configure_logging()
    spy = Spy()
    fresh_config.addHandler(spy)

    logging.getLogger("factumov.services.delegation_watch").info("quedó verificada")

    assert spy.records == []
