"""Envío de mail transaccional por SMTP.

Config propia y no la de `database.py`: ese `Settings` es sobre la base, y meterle el
servidor de mail lo convertiría en un cajón de sastre. Son dos cosas que se configuran por
separado y fallan por separado.

`EmailSettings` se construye **adentro** de `send_email`, no al importar el módulo. Si se
instanciara arriba, un `.env` sin `SMTP_HOST` haría fallar el import de todo el paquete —o
sea la app entera y la suite completa— por no poder mandar un mail que nadie pidió. Con
`lru_cache` el costo de leer el entorno se paga una sola vez igual.

**Un fallo de entrega sube.** Hasta el 2026-08-27 este módulo se tragaba el `OSError` y
dejaba una línea de log, porque el envío corría siempre en un background task y no había a
quién avisarle. El resultado fue el peor de los posibles: el `.env` apuntaba al puerto 465
—que este transporte no sabe hablar—, el registro contestó 202 durante días y el mail no
salió nunca. Ahora la entrega es parte de la respuesta en los endpoints cuyo producto *es*
el mail, y `send_email_best_effort` queda para los que solo lo acompañan.
"""

import logging
import smtplib
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Un servidor SMTP caído no puede colgar un worker indefinidamente. Con el envío adentro del
# request este número es además el techo de lo que puede tardar un registro.
SMTP_TIMEOUT_SECONDS = 10

# TLS implícito: el servidor negocia desde el saludo y espera un handshake, no un `EHLO`.
# Necesita `smtplib.SMTP_SSL`, que este módulo no usa — ver el validador.
_IMPLICIT_TLS_PORT = 465


class EmailDeliveryError(Exception):
    """No se pudo entregar el mail: config inservible, servidor caído, credenciales malas.

    No distingue entre esas causas a propósito. Para el usuario que está esperando el mail
    las tres son lo mismo —no le llegó— y el detalle no puede viajar en la respuesta HTTP:
    diría cómo está armado nuestro lado. La causa concreta va al log, que es donde la puede
    leer quien la puede arreglar.
    """


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    smtp_host: str
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    # STARTTLS en 587 es lo que usan Gmail y casi todos los proveedores. Sigue siendo un flag
    # y no algo deducido del puerto porque un relay interno en el 25 o en el 587 puede no
    # ofrecer TLS, y ahí `starttls()` es un error.
    smtp_starttls: bool = True
    email_from: str
    # De dónde cuelga el link de confirmación. Es la SPA, no el backend: el usuario aterriza
    # en una pantalla que lee el token y lo postea. El default va con https porque el dev
    # server de Vite habla TLS (la cookie de sesión es Secure): con http el link del mail
    # llega inservible, y el navegador dice ERR_EMPTY_RESPONSE en vez de nombrar la causa.
    app_base_url: str = "https://localhost:5173"
    # A quién avisarle de lo que solo puede resolver una persona con la Clave Fiscal de
    # FactuMov. Hoy es un caso: aceptar en ARCA la designación de un usuario que ya delegó.
    #
    # Sin default y opcional, no obligatorio: es el único destinatario de la app que no sale de
    # una fila de `users`, y una instalación sin operador —un entorno de pruebas, un worker que
    # solo emite— tiene que poder arrancar igual. Cuando falta, el aviso queda en el log en vez
    # de tumbar nada, que es la misma política que `send_email_best_effort`.
    operator_email: str | None = None

    @model_validator(mode="after")
    def _reject_unusable_transport(self) -> "EmailSettings":
        """Corta las dos configuraciones que no pueden funcionar nunca.

        Las dos comparten la propiedad que las vuelve caras: fallan lejos de su causa. La
        del 465 se manifiesta como un timeout de diez segundos adentro de un envío, y la de
        las credenciales a medias como un rechazo del relay — ninguna de las dos nombra al
        `.env`, que es lo único que hay que tocar.

        Es un validador de la config y no un chequeo en `send_email` porque la pregunta
        "¿esto puede andar?" se contesta sin red: no hace falta intentar un envío para saber
        que este transporte no habla TLS implícito.
        """
        if self.smtp_port == _IMPLICIT_TLS_PORT:
            raise ValueError(
                f"SMTP_PORT={_IMPLICIT_TLS_PORT} (TLS implícito) no está soportado: este "
                "transporte abre siempre una conexión en texto plano. Usá 587 con "
                "SMTP_STARTTLS=true, que es lo que ofrecen Gmail y la mayoría."
            )
        # Con uno solo de los dos, `send_email` saltea el login sin decir nada y el servidor
        # rechaza el relay recién al final. Es la misma clase de error silencioso que el 465.
        if bool(self.smtp_user) != bool(self.smtp_password):
            raise ValueError(
                "SMTP_USER y SMTP_PASSWORD van juntos: con uno solo no se hace login y el "
                "servidor rechaza el envío. Sacá los dos si el relay no pide autenticación."
            )
        return self


@lru_cache
def get_email_settings() -> EmailSettings:
    return EmailSettings()  # type: ignore[call-arg]


def config_problem() -> str | None:
    """Qué tiene de malo la config de mail, o `None` si puede funcionar.

    No sale a la red: contesta lo que se sabe leyendo el entorno —variables que faltan, y lo
    que rechaza `_reject_unusable_transport`—. Que no haya problema acá no promete que el
    mail vaya a salir; que sí lo haya promete que no.

    Existe para poder avisar al arrancar, que es cuando alguien está mirando la consola y
    puede corregir el `.env`, en vez de al primer registro de un usuario real.
    """
    try:
        get_email_settings()
    except ValidationError as error:
        return "; ".join(_describe(item["loc"], item["msg"]) for item in error.errors())
    return None


def _describe(loc: tuple[int | str, ...], message: str) -> str:
    """Un error de Pydantic en una línea. `loc` vacío es el validador del modelo entero."""
    field = ".".join(str(part) for part in loc)
    return f"{field}: {message}" if field else message


@dataclass(frozen=True)
class Attachment:
    """Un archivo adjunto, ya en memoria.

    Recibe los bytes y no una ruta a propósito: el único adjunto que manda FactuMov es un PDF
    que se genera al vuelo y nunca toca el disco, así que un archivo temporal sería basura que
    alguien tiene que acordarse de limpiar.

    `media_type` va partido en tipo y subtipo porque es lo que pide `add_attachment` de
    `EmailMessage`. Se guarda entero y se parte al usarlo, que se lee mejor que dos campos.
    """

    filename: str
    content: bytes
    media_type: str = "application/pdf"


def send_email(
    to: str,
    subject: str,
    body: str,
    attachments: Sequence[Attachment] = (),
    cc: Sequence[str] = (),
) -> None:
    """Manda un mail de texto plano, con adjuntos si los hay.

    El default vacío es una tupla y no una lista: un mutable por default se comparte entre
    todas las llamadas, y aunque acá nadie lo modifique, es la clase de detalle que deja de
    ser inofensivo en cuanto alguien agregue una línea.

    `cc` viaja solo como cabecera `Cc`: `send_message` deduce los destinatarios de las
    cabeceras `To`/`Cc`/`Bcc` cuando no se le pasa `to_addrs`, así que agregar la cabecera
    alcanza para que las copias se entreguen. Se omite si la lista viene vacía —una cabecera
    `Cc:` en blanco es tan válida como fea—.

    La config se resuelve acá adentro y su `ValidationError` se convierte en la misma
    excepción que un servidor caído: para el que llama, "el `.env` está mal" y "el servidor
    no contesta" tienen la misma consecuencia —el mail no salió— y el mismo tratamiento.
    Dejar subir el `ValidationError` haría que un `.env` incompleto se viera como un 500 con
    traceback de Pydantic en vez de un error de entrega.
    """
    try:
        settings = get_email_settings()
    except ValidationError as error:
        raise EmailDeliveryError(f"La configuración de mail no sirve: {error}") from error

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.set_content(body)
    for attachment in attachments:
        maintype, _, subtype = attachment.media_type.partition("/")
        message.add_attachment(
            attachment.content, maintype=maintype, subtype=subtype, filename=attachment.filename
        )

    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
        ) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
    except OSError as error:
        # `smtplib.SMTPException` y los errores de socket bajan los dos de OSError.
        raise EmailDeliveryError(f"No se pudo entregar el mail a {to}") from error


def send_email_best_effort(
    to: str, subject: str, body: str, attachments: Sequence[Attachment] = ()
) -> None:
    """Manda un mail cuyo fallo no debe tumbar la operación que lo generó.

    Es para los mails que **acompañan** a algo que ya pasó y quedó guardado: las
    instrucciones de delegación después de confirmar la dirección, el aviso de que la
    contraseña cambió. Ahí el request no puede fallar aunque el mail no salga —la cuenta ya
    está confirmada, la contraseña ya es la nueva— y devolver un error haría que el usuario
    reintente una acción que no se puede repetir.

    La distinción con `send_email` es de rol, no de importancia: el mail de confirmación es
    el producto del request y su fallo tiene que verse; estos son una consecuencia.
    """
    try:
        send_email(to=to, subject=subject, body=body, attachments=attachments)
    except EmailDeliveryError:
        logger.exception("No se pudo enviar el mail a %s (asunto: %s)", to, subject)
