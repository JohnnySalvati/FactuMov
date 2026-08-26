"""Tests de la composición de los mails.

Lo que los tests de router ya cubren —que el link de confirmación abre la cuenta y que el
mail de delegación llega al confirmar— no se repite acá. Queda lo que solo se ve
mirando el texto: el armado de la URL y lo que el mensaje le promete al usuario.
"""

from factumov.services import email as email_module
from factumov.services import notifications
from factumov.services.arca import ArcaSettings
from tests.conftest import FALLBACK_DELEGATE_TAX_ID


def test_the_confirmation_link_survives_a_trailing_slash(monkeypatch, sent_emails):
    """`APP_BASE_URL` con barra final es el typo de config más fácil de cometer."""
    monkeypatch.setenv("APP_BASE_URL", "https://factumov.test/")
    email_module.get_email_settings.cache_clear()

    notifications.send_confirmation_email("ana@cucu.com", "el-token", valid_for_hours=24)

    assert "https://factumov.test/confirmar-email?token=el-token" in sent_emails[0].body


def test_the_confirmation_mail_states_the_deadline(sent_emails):
    notifications.send_confirmation_email("ana@cucu.com", "el-token", valid_for_hours=24)

    assert "vence en 24 horas" in sent_emails[0].body


def test_the_delegation_mail_names_the_certificate_cuit(sent_emails, arca_cert):
    """El certificado manda: es el CUIT que ARCA va a ver del otro lado."""
    notifications.send_delegation_instructions_email("ana@cucu.com")

    assert arca_cert in sent_emails[0].body


def test_without_a_certificate_the_mail_falls_back_to_the_setting(sent_emails):
    """Un worker que solo manda mails puede no tener el certificado; el mail sale igual."""
    notifications.send_delegation_instructions_email("ana@cucu.com")

    assert FALLBACK_DELEGATE_TAX_ID in sent_emails[0].body


def test_the_certificate_wins_over_the_setting(sent_emails, arca_cert):
    """Si los dos están y discrepan, vale el certificado.

    El otro es una variable que alguien escribió a mano, y el mail termina con un usuario
    entrando a ARCA a autorizar ese número: nombrar el equivocado le hace otorgar una
    delegación que no sirve, y descubrirlo recién al verificar.
    """
    notifications.send_delegation_instructions_email("ana@cucu.com")

    assert FALLBACK_DELEGATE_TAX_ID not in sent_emails[0].body


def test_the_default_cuit_is_the_real_one():
    """El certificado de FactuMov existe y es el mismo con el que Balance360 ya emite.

    Se afirma sobre el default de la clase y no sobre un mail: montar el caso con variables
    lo dejaría a merced del `.env` de cada máquina. Antes acá se exigía un placeholder
    visible, porque el certificado no existía todavía.
    """
    assert ArcaSettings.model_fields["arca_delegate_tax_id"].default == "20182810674"
