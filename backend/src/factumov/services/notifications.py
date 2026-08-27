"""Los mails que manda FactuMov: asunto, cuerpo y a quién.

Separado de `email.py` a propósito: ahí vive el transporte —SMTP, TLS, timeouts— y acá el
contenido. Son las dos cosas que cambian por motivos distintos: cambiar de proveedor no
toca ni una palabra de estos textos, y corregir la redacción de un mail no debería obligar
a leer código de sockets.

Los textos van en español, como el resto de los strings de cara al usuario.
"""

import logging
from urllib.parse import quote

# Importado como módulo, no por nombre: `send_email` se resuelve en cada llamada, así que
# un test puede parchear `factumov.services.email.send_email` en un solo lugar y estas
# funciones miran el parche. Con `from ... import send_email` la referencia quedaría fija al
# importar y el parche no llegaría acá nunca.
from factumov.services import arca, email

logger = logging.getLogger(__name__)

_CONFIRMATION_PATH = "/confirmar-email"
_PASSWORD_RESET_PATH = "/restablecer-password"
_REGISTER_PATH = "/registro"

# Cuál de los dos transportes usa cada mail — la decisión está explicada en `email.py`. En
# una línea: el mail que **es** el producto del request usa `send_email`, que levanta si no
# se pudo entregar, y el endpoint contesta 503 en vez de un 202 que no cumple. El mail que
# acompaña a algo ya guardado usa `send_email_best_effort`, porque su fallo no puede
# deshacer una confirmación ni una contraseña ya cambiada.


def _url(path: str, raw_token: str | None = None) -> str:
    """Una URL de la SPA. Los paths los fija `App.tsx`; cambiarlos rompe los mails ya enviados.

    `quote` y no interpolación pelada: `token_urlsafe` produce `-` y `_`, que son seguros,
    pero el día que el token cambie de alfabeto esto no se rompe en silencio.
    """
    base = f"{email.get_email_settings().app_base_url.rstrip('/')}{path}"
    return base if raw_token is None else f"{base}?token={quote(raw_token)}"


def send_confirmation_email(to: str, raw_token: str, valid_for_hours: int) -> None:
    email.send_email(
        to=to,
        subject="Confirmá tu dirección de email",
        body=(
            "Hola,\n\n"
            "Para terminar de crear tu cuenta en FactuMov, entrá en este link:\n\n"
            f"{_url(_CONFIRMATION_PATH, raw_token)}\n\n"
            f"El link vence en {valid_for_hours} horas. Si no fuiste vos, ignorá este "
            "mensaje: sin confirmar, la cuenta no se puede usar.\n"
        ),
    )


def send_already_registered_email(to: str) -> None:
    """Aviso para quien intenta registrarse con una dirección ya confirmada.

    Existe para que `POST /auth/register` pueda contestar siempre lo mismo sin dejar al
    usuario a oscuras. La respuesta HTTP no distingue el caso —eso sería un oráculo de
    enumeración—, así que el único lugar donde se puede contar qué pasó es la casilla del
    dueño de la dirección, que es justamente quien tiene derecho a saberlo.
    """
    email.send_email(
        to=to,
        subject="Ya tenés una cuenta en FactuMov",
        body=(
            "Hola,\n\n"
            "Alguien intentó crear una cuenta con esta dirección, que ya está registrada "
            "y confirmada. No hicimos ningún cambio: tu contraseña sigue siendo la misma.\n\n"
            "Si fuiste vos, entrá con tu contraseña de siempre.\n"
        ),
    )


def send_password_reset_email(to: str, raw_token: str, valid_for_minutes: int) -> None:
    """El link para elegir una contraseña nueva."""
    email.send_email(
        to=to,
        subject="Restablecer tu contraseña de FactuMov",
        body=(
            "Hola,\n\n"
            "Pediste restablecer tu contraseña de FactuMov. Elegí una nueva desde este "
            "link:\n\n"
            f"{_url(_PASSWORD_RESET_PATH, raw_token)}\n\n"
            f"El link vence en {valid_for_minutes} minutos y se puede usar una sola vez.\n\n"
            "Si no fuiste vos, ignorá este mensaje: tu contraseña sigue siendo la de "
            "siempre y nadie puede cambiarla sin este link.\n"
        ),
    )


def send_no_account_email(to: str) -> None:
    """Aviso para quien pide un reset sobre una dirección sin cuenta utilizable.

    Existe por el mismo motivo que `send_already_registered_email`, y además por uno
    estructural: `POST /auth/forgot-password` contesta 503 cuando el mail no se puede
    entregar. Si esta rama no mandara nada, nunca podría fallar — y entonces un 503 pasaría a
    significar "esa dirección sí existe". Las dos ramas mandan un mail justamente para que
    las dos puedan fallar igual.

    El texto no dice "no existe": una cuenta dada de baja también cae acá, y afirmar que no
    existe sería mentirle a su dueño.
    """
    email.send_email(
        to=to,
        subject="No pudimos restablecer tu contraseña",
        body=(
            "Hola,\n\n"
            "Alguien pidió restablecer la contraseña de esta dirección, pero no hay ninguna "
            "cuenta de FactuMov que se pueda usar con ella.\n\n"
            "Si esperabas poder entrar, puede que te hayas registrado con otra dirección. "
            "También podés crear una cuenta acá:\n\n"
            f"{_url(_REGISTER_PATH)}\n\n"
            "Si no fuiste vos, no hace falta que hagas nada.\n"
        ),
    )


def send_password_changed_email(to: str) -> None:
    """Aviso de que la contraseña cambió. Best effort: la contraseña ya es la nueva.

    No es una cortesía. Es la única señal que le llega al dueño de la casilla si el reset lo
    pidió otro, y llega a un lugar al que el atacante ya no puede volver: el link se consumió
    y las sesiones se cerraron todas.
    """
    email.send_email_best_effort(
        to=to,
        subject="Tu contraseña de FactuMov cambió",
        body=(
            "Hola,\n\n"
            "Tu contraseña de FactuMov se acaba de cambiar, y cerramos todas las sesiones "
            "que estaban abiertas.\n\n"
            "Si fuiste vos, no hace falta que hagas nada.\n\n"
            "Si no fuiste vos, alguien tiene acceso a esta casilla de mail: cambiá su "
            "contraseña y después volvé a pedir un restablecimiento en FactuMov.\n"
        ),
    )


def send_invoice_email(
    to: str,
    label: str,
    issuer_name: str,
    total: str,
    pdf: bytes,
    filename: str,
) -> None:
    """La factura emitida, con el PDF adjunto.

    Usa `send_email` y no la versión best effort: este mail **es** el producto del request —
    quien apretó "Mandar por email" no pidió otra cosa— así que si no sale, el endpoint tiene
    que decirlo. Es el mismo criterio que el mail de confirmación de cuenta.

    El asunto lleva el número del comprobante y la razón social del emisor porque es lo que el
    destinatario ve en la lista de su casilla, y "Factura" a secas no le dice de quién es.

    Los importes llegan ya formateados: quien los sabe formatear es `invoice_pdf`, y hacerlo
    otra vez acá sería una segunda forma de escribir el mismo número.
    """
    email.send_email(
        to=to,
        subject=f"Factura {label} de {issuer_name}",
        body=(
            "Hola,\n\n"
            f"Te adjuntamos la factura {label} de {issuer_name} por $ {total}.\n\n"
            "El comprobante está autorizado por ARCA; el CAE y su vencimiento figuran al pie "
            "del PDF.\n"
        ),
        attachments=[email.Attachment(filename=filename, content=pdf)],
    )


def send_delegation_instructions_email(to: str) -> None:
    """Las instrucciones para delegar WSFE en el CUIT de FactuMov.

    Se manda al confirmar la dirección y no al registrarse: antes de confirmar no hay
    ninguna prueba de que la casilla sea de quien dice, y estas instrucciones terminan con
    alguien entrando a ARCA con su Clave Fiscal.

    Best effort: sale después de que la confirmación ya quedó guardada. Fallar el request
    por este mail mandaría al usuario a reintentar con un token que ya se consumió, o sea a
    un 400 sobre una cuenta que en realidad quedó confirmada.
    """
    email.send_email_best_effort(
        to=to,
        subject="Cómo autorizar a FactuMov a emitir tus facturas",
        body=(
            "Hola,\n\n"
            "Tu cuenta ya está confirmada. Para que FactuMov pueda emitir facturas a "
            "nombre de tu CUIT, ARCA necesita que se lo autorices vos. Es un trámite "
            "online y se hace una sola vez por CUIT:\n\n"
            "1. Entrá a arca.gob.ar con tu Clave Fiscal.\n"
            "2. Abrí 'Administrador de Relaciones de Clave Fiscal'.\n"
            "3. Elegí 'Nueva Relación' y buscá el servicio de Facturación Electrónica "
            "(WSFE).\n"
            f"4. Como representante, indicá el CUIT {arca.get_delegate_tax_id()} "
            "(FactuMov).\n"
            "5. Confirmá.\n\n"
            "Después cargá tu CUIT en FactuMov: verificamos la autorización solos, no hace "
            "falta que nos avises.\n"
        ),
    )


def send_delegation_pending_email(tax_id: str, identity_name: str, user_email: str) -> None:
    """Le avisa al operador que hay una designación esperando que la acepte en ARCA.

    **Es el único mail de la app que no le va a un usuario**, y existe porque hay un paso
    del alta que ninguna máquina puede dar: aceptar la designación en «Aceptación de
    Designación» es un click con Clave Fiscal, y ARCA no publica las designaciones
    pendientes por ningún web service. O sea que la app no puede enterarse sola de que
    alguien la está esperando.

    Lo que sí puede es enterarse por el usuario. Este mail sale del momento exacto en que
    él dice "ya delegué" y ARCA sigue diciendo que no — el único instante en que existe
    evidencia de que hay una persona esperando del otro lado.

    Best effort, y sale una sola vez por identidad: lo dispara el **primer** aviso, no cada
    click. Ver `crud/fiscal_identity.mark_delegation_claimed`.

    Sin `OPERATOR_EMAIL` configurado no hay a quién avisarle, y eso no puede romper el
    request del usuario: queda un WARNING en el log, que es donde lo va a ver quien
    configura el `.env`. Es la misma política que `send_email_best_effort`, un escalón
    antes.
    """
    settings = email.get_email_settings()
    if settings.operator_email is None:
        logger.warning(
            "El CUIT %s (%s) dice haber delegado y ARCA todavía no lo confirma, pero no hay "
            "OPERATOR_EMAIL configurado para avisar. Hay que aceptar la designación a mano "
            "en el «Administrador de Relaciones» de ARCA.",
            tax_id,
            user_email,
        )
        return

    email.send_email_best_effort(
        to=settings.operator_email,
        subject=f"Aceptar la delegación del CUIT {tax_id}",
        body=(
            f"{user_email} cargó la identidad fiscal «{identity_name}» (CUIT {tax_id}) "
            "y dice que ya nos designó como representante en ARCA. WSFE todavía no nos "
            "habilita, así que falta aceptar la designación:\n\n"
            "1. Entrá a arca.gob.ar con la Clave Fiscal de FactuMov.\n"
            "2. Abrí 'Administrador de Relaciones de Clave Fiscal'.\n"
            "3. Entrá en 'Aceptación de Designación'.\n"
            f"4. Aceptá la fila del representado {tax_id}, servicio Facturación "
            "Electrónica.\n\n"
            "El usuario ya sabe que la demora es nuestra y está esperando. No hace falta "
            "que le contestes: FactuMov reverifica contra ARCA y le avisa cuando quede "
            "habilitado.\n"
        ),
    )
