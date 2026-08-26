"""Tests del transporte SMTP de `services/email.py`.

Ojo con un detalle del import: el fixture autouse `sent_emails` reemplaza el atributo
`send_email` del módulo, así que el resto de la suite nunca toca un socket. Acá se importa
la función **por nombre**, y ese binding se resuelve cuando pytest colecta el archivo, o sea
antes de que corra ningún fixture. Por eso `send_email` acá es la de verdad y no el fake, y
es justamente lo que este archivo tiene que ejercitar.
"""

import smtplib

import pytest

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
    """El puerto 465 negocia TLS desde el saludo y `starttls()` ahí es un error."""
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


def test_a_failing_server_does_not_raise(monkeypatch, caplog):
    """Corre en un background task, con la respuesta ya enviada: no hay a quién avisarle."""

    def explode(host, port, timeout=None):
        raise smtplib.SMTPConnectError(421, "no hay nadie")

    monkeypatch.setattr(smtplib, "SMTP", explode)

    send_email(to="ana@cucu.com", subject="Hola", body="Cuerpo")

    assert "ana@cucu.com" in caplog.text


def test_the_password_is_not_a_plain_string(monkeypatch):
    """`SecretStr` para que no se filtre en un repr, un log o un traceback."""
    configure(monkeypatch, smtp_password="secreta")

    settings = EmailSettings()  # type: ignore[call-arg]

    assert "secreta" not in repr(settings)
    assert settings.smtp_password is not None
    assert settings.smtp_password.get_secret_value() == "secreta"
