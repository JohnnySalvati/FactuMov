"""Tests de la composición de los mails.

Lo que los tests de router ya cubren —que el link de confirmación abre la cuenta y que el
mail de delegación lleva el CUIT configurado— no se repite acá. Queda lo que solo se ve
mirando el texto: el armado de la URL y lo que el mensaje le promete al usuario.
"""

from factumov.services import email as email_module
from factumov.services import notifications
from factumov.services.email import EmailSettings


def test_the_confirmation_link_survives_a_trailing_slash(monkeypatch, sent_emails):
    """`APP_BASE_URL` con barra final es el typo de config más fácil de cometer."""
    monkeypatch.setenv("APP_BASE_URL", "https://factumov.test/")
    email_module.get_email_settings.cache_clear()

    notifications.send_confirmation_email("ana@cucu.com", "el-token", valid_for_hours=24)

    assert "https://factumov.test/confirmar-email?token=el-token" in sent_emails[0].body


def test_the_confirmation_mail_states_the_deadline(sent_emails):
    notifications.send_confirmation_email("ana@cucu.com", "el-token", valid_for_hours=24)

    assert "vence en 24 horas" in sent_emails[0].body


def test_the_delegation_mail_carries_the_configured_cuit(monkeypatch, sent_emails):
    monkeypatch.setenv("ARCA_DELEGATE_TAX_ID", "30-99999999-7")
    email_module.get_email_settings.cache_clear()

    notifications.send_delegation_instructions_email("ana@cucu.com")

    assert "30-99999999-7" in sent_emails[0].body


def test_the_default_cuit_is_a_visible_placeholder():
    """Se afirma sobre el default de la clase y no sobre un mail.

    Mirar el default directo deja el test independiente de la config: montar el caso con un
    `delenv` lo dejaría a merced de que nadie ponga la variable en su `.env`. Lo que importa
    es que el default se note en el cuerpo del mail — un CUIT falso pero plausible saldría
    sin que nadie lo mire dos veces.
    """
    default = EmailSettings.model_fields["arca_delegate_tax_id"].default

    assert "a completar" in default
