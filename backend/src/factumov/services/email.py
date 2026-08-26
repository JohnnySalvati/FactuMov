"""Envío de mail transaccional por SMTP.

Config propia y no la de `database.py`: ese `Settings` es sobre la base, y meterle el
servidor de mail lo convertiría en un cajón de sastre. Son dos cosas que se configuran por
separado y fallan por separado.

`EmailSettings` se construye **adentro** de `send_email`, no al importar el módulo. Si se
instanciara arriba, un `.env` sin `SMTP_HOST` haría fallar el import de todo el paquete —o
sea la app entera y la suite completa— por no poder mandar un mail que nadie pidió. Con
`lru_cache` el costo de leer el entorno se paga una sola vez igual.
"""

import logging
import smtplib
from email.message import EmailMessage
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Un servidor SMTP caído no puede colgar un worker indefinidamente. El envío ya corre en un
# background task, así que este timeout acota la tarea, no el request.
SMTP_TIMEOUT_SECONDS = 10


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    smtp_host: str
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    # STARTTLS en 587 es lo que usan Gmail y casi todos los proveedores. El puerto 465
    # (TLS implícito desde el saludo) necesita `SMTP_SSL` y no `starttls()`, por eso es un
    # flag y no algo que se pueda deducir del número de puerto sin adivinar.
    smtp_starttls: bool = True
    email_from: str
    # De dónde cuelga el link de confirmación. Es la SPA, no el backend: el usuario aterriza
    # en una pantalla que lee el token y lo postea.
    app_base_url: str = "http://localhost:5173"


@lru_cache
def get_email_settings() -> EmailSettings:
    return EmailSettings()  # type: ignore[call-arg]


def send_email(to: str, subject: str, body: str) -> None:
    """Manda un mail de texto plano.

    No propaga la excepción: se llama desde un background task, después de que la respuesta
    ya salió, así que no hay nadie a quien contarle el error. Dejarla subir mataría la tarea
    con un traceback sin contexto; loguearla deja el rastro donde se puede ver.
    """
    settings = get_email_settings()
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
        ) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except OSError:
        # `smtplib.SMTPException` y los errores de socket bajan los dos de OSError.
        logger.exception("No se pudo enviar el mail a %s (asunto: %s)", to, subject)
