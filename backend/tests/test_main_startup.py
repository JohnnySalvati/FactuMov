"""El aviso de config de mail al arrancar.

Es la mitad "temprana" de la mejora: el 503 le cuenta al usuario que el mail no salió, y este
renglón se lo cuenta a quien lo puede arreglar, en el momento en que tiene el `.env` a mano.

El lifespan se corre con `asyncio.run` y no con `TestClient(app)` como context manager. Acá
lo único que importa es lo que loguea, y montar la app entera para leer un renglón sería
armar medio mundo para mirar una línea. `asyncio.run` en vez de `pytest-asyncio` porque la
suite no tiene esa dependencia y tres tests no la justifican.
"""

import asyncio
import logging

from factumov.main import lifespan
from factumov.services import email as email_service


def run_lifespan():
    async def go():
        async with lifespan(None):  # type: ignore[arg-type]
            pass

    asyncio.run(go())


def test_a_broken_mail_config_is_loud_at_startup(monkeypatch, caplog):
    """El error que costó dos días: el `.env` decía 465 y nada lo dijo hasta que faltó un mail."""
    monkeypatch.setenv("SMTP_PORT", "465")
    email_service.get_email_settings.cache_clear()

    with caplog.at_level(logging.ERROR):
        run_lifespan()

    assert "465" in caplog.text
    assert "SMTP" in caplog.text


def test_a_broken_mail_config_does_not_stop_the_app(monkeypatch):
    """Loguea y sigue: emitir, editar modelos y consultar el padrón no necesitan mail.

    Tirar abajo la app entera por una variable que solo miran el registro, el reenvío y el
    reset es el mismo error que `EmailSettings` evita al no instanciarse en el import.
    """
    monkeypatch.delenv("SMTP_HOST")
    email_service.get_email_settings.cache_clear()

    run_lifespan()  # no levanta


def test_a_good_config_says_nothing_alarming(caplog):
    with caplog.at_level(logging.ERROR):
        run_lifespan()

    assert caplog.records == []
