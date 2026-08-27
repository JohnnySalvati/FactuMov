"""Tests del transporte SMTP de `services/email.py`.

Ojo con un detalle del import: el fixture autouse `sent_emails` reemplaza el atributo
`send_email` del módulo, así que el resto de la suite nunca toca un socket. Acá se importa
la función **por nombre**, y ese binding se resuelve cuando pytest colecta el archivo, o sea
antes de que corra ningún fixture. Por eso `send_email` acá es la de verdad y no el fake, y
es justamente lo que este archivo tiene que ejercitar.
"""

import smtplib

import pytest
from pydantic import ValidationError

from factumov.services import email as email_module
from factumov.services.email import EmailSettings, send_email


class FakeSMTP:
    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.credentials = None
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.credentials = (user, password)

    def send_message(self, message):
        self.messages.append(message)


@pytest.fixture
def smtp(monkeypatch):
    """Sustituye `smtplib.SMTP` y devuelve la instancia que se haya construido."""
    built = []

    def factory(host, port, timeout=None):
        server = FakeSMTP(host, port, timeout=timeout)
        built.append(server)
        return server

    monkeypatch.setattr(smtplib, "SMTP", factory)
    return built


def configure(monkeypatch, **overrides):
    """Fija la config de mail y limpia la cache de `get_email_settings`."""
    for key, value in overrides.items():
        monkeypatch.setenv(key.upper(), value)
    email_module.get_email_settings.cache_clear()


def test_sends_the_message_to_the_configured_server(monkeypatch, smtp):
    configure(monkeypatch, smtp_host="mail.test", smtp_port="2525")

    send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert len(smtp) == 1
    assert (smtp[0].host, smtp[0].port) == ("mail.test", 2525)
    assert smtp[0].timeout == email_module.SMTP_TIMEOUT_SECONDS
    message = smtp[0].messages[0]
    assert message["To"] == "ana@cucu.com"
    assert message["Subject"] == "Hola"
    assert message.get_content().strip() == "Cuerpo"


def test_uses_the_configured_sender(monkeypatch, smtp):
    configure(monkeypatch, email_from="FactuMov <hola@factumov.test>")

    send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert smtp[0].messages[0]["From"] == "FactuMov <hola@factumov.test>"


def test_starts_tls_by_default(monkeypatch, smtp):
    send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert smtp[0].started_tls is True


def test_skips_starttls_when_disabled(monkeypatch, smtp):
    """Un relay interno puede no ofrecer TLS, y ahí `starttls()` es un error.

    Es el único motivo que le queda al flag: el otro caso que solía justificarlo —el puerto
    465— ahora se rechaza al construir la config, porque apagar STARTTLS tampoco lo hacía
    funcionar.
    """
    configure(monkeypatch, smtp_starttls="false")

    send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert smtp[0].started_tls is False


def test_does_not_log_in_without_credentials(monkeypatch, smtp):
    """Un relay interno suele no pedir auth, y `login(None, None)` sería un error."""
    send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert smtp[0].credentials is None


def test_logs_in_when_credentials_are_configured(monkeypatch, smtp):
    configure(monkeypatch, smtp_user="ana", smtp_password="secreta")

    send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert smtp[0].credentials == ("ana", "secreta")


def break_the_server(monkeypatch):
    """Hace que cualquier conexión SMTP falle, como un servidor caído o inalcanzable."""

    def explode(host, port, timeout=None):
        raise smtplib.SMTPConnectError(421, "no hay nadie")

    monkeypatch.setattr(smtplib, "SMTP", explode)


def test_a_failing_server_raises(monkeypatch):
    """El fallo sube: el que llama decide si el request muere con él o sigue.

    Hasta el 2026-08-27 esta función se tragaba el error y dejaba una línea de log, porque
    el envío siempre corría en un background task. Con esa política el registro contestaba
    202 con el SMTP mal configurado y el mail no salía nunca.
    """
    break_the_server(monkeypatch)

    with pytest.raises(email_module.EmailDeliveryError):
        send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")


def test_an_unusable_config_raises_the_same_error_as_a_dead_server(monkeypatch, smtp):
    """Un `.env` incompleto no es un 500 con traceback de Pydantic: es un mail que no salió."""
    monkeypatch.delenv("SMTP_HOST")
    email_module.get_email_settings.cache_clear()

    with pytest.raises(email_module.EmailDeliveryError):
        send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")


@pytest.fixture
def unpatched_transport(monkeypatch):
    """Devuelve el `send_email` de verdad al módulo.

    El fixture autouse `sent_emails` reemplaza `email.send_email` para que ningún test toque
    un socket, y `send_email_best_effort` resuelve ese nombre por el módulo en cada llamada
    —que es justamente la propiedad por la que el parche llega hasta él—. O sea que para
    probar el best effort en sí hay que deshacer el parche primero. El resto de este archivo
    no lo necesita porque importa `send_email` por nombre, y ese binding se resuelve al
    colectar, antes de que corra ningún fixture.
    """
    monkeypatch.setattr(email_module, "send_email", send_email)


def test_best_effort_swallows_the_failure_and_logs_it(monkeypatch, caplog, unpatched_transport):
    """Para los mails que acompañan a algo ya guardado. El rastro queda en el log."""
    break_the_server(monkeypatch)

    email_module.send_email_best_effort(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert "ana@cucu.com" in caplog.text


def test_best_effort_still_sends_when_the_server_answers(smtp, unpatched_transport):
    email_module.send_email_best_effort(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert smtp[0].messages[0]["To"] == "ana@cucu.com"


# --- la config que no puede funcionar ------------------------------------------------------
#
# Las tres se rechazan al construir `EmailSettings` y no al intentar un envío: la pregunta
# "¿esto puede andar?" se contesta sin salir a la red. El valor está en *dónde* aparece el
# error — al arrancar, con el `.env` a mano— y no en que aparezca.


def test_the_implicit_tls_port_is_rejected(monkeypatch):
    """El 465 negocia TLS desde el saludo y este transporte abre siempre texto plano.

    Es el error que costó dos días el 2026-08-26: el `.env` decía 465, la conexión moría por
    timeout a los diez segundos, y el `except OSError` de entonces lo dejaba solo en el log.
    """
    configure(monkeypatch, smtp_port="465")

    with pytest.raises(ValidationError) as caught:
        EmailSettings()  # type: ignore[call-arg]

    assert "587" in str(caught.value)


@pytest.mark.parametrize("present", ["smtp_user", "smtp_password"])
def test_half_the_credentials_are_rejected(monkeypatch, present):
    """Con uno solo no se hace login y el relay rechaza el envío recién al final."""
    configure(monkeypatch, **{present: "algo"})

    with pytest.raises(ValidationError):
        EmailSettings()  # type: ignore[call-arg]


def test_config_problem_is_none_when_the_config_can_work():
    assert email_module.config_problem() is None


def test_config_problem_names_the_missing_variable(monkeypatch):
    monkeypatch.delenv("SMTP_HOST")
    email_module.get_email_settings.cache_clear()

    problem = email_module.config_problem()

    assert problem is not None
    assert "smtp_host" in problem.lower()


def test_config_problem_explains_the_unusable_port(monkeypatch):
    configure(monkeypatch, smtp_port="465")

    problem = email_module.config_problem()

    assert problem is not None
    assert "465" in problem


def test_the_password_is_not_a_plain_string(monkeypatch):
    """`SecretStr` para que no se filtre en un repr, un log o un traceback."""
    configure(monkeypatch, smtp_user="ana", smtp_password="secreta")

    settings = EmailSettings()  # type: ignore[call-arg]

    assert "secreta" not in repr(settings)
    assert settings.smtp_password is not None
    assert settings.smtp_password.get_secret_value() == "secreta"
