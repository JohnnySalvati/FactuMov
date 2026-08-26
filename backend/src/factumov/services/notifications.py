"""Los mails que manda FactuMov: asunto, cuerpo y a quién.

Separado de `email.py` a propósito: ahí vive el transporte —SMTP, TLS, timeouts— y acá el
contenido. Son las dos cosas que cambian por motivos distintos: cambiar de proveedor no
toca ni una palabra de estos textos, y corregir la redacción de un mail no debería obligar
a leer código de sockets.

Los textos van en español, como el resto de los strings de cara al usuario.
"""

from urllib.parse import quote

# Importado como módulo, no por nombre: `send_email` se resuelve en cada llamada, así que
# un test puede parchear `factumov.services.email.send_email` en un solo lugar y estas
# funciones miran el parche. Con `from ... import send_email` la referencia quedaría fija al
# importar y el parche no llegaría acá nunca.
from factumov.services import arca, email

_CONFIRMATION_PATH = "/confirmar-email"


def _confirmation_url(raw_token: str) -> str:
    settings = email.get_email_settings()
    # `quote` y no interpolación pelada: `token_urlsafe` produce `-` y `_`, que son seguros,
    # pero el día que el token cambie de alfabeto esto no se rompe en silencio.
    return f"{settings.app_base_url.rstrip('/')}{_CONFIRMATION_PATH}?token={quote(raw_token)}"


def send_confirmation_email(to: str, raw_token: str, valid_for_hours: int) -> None:
    email.send_email(
        to=to,
        subject="Confirmá tu dirección de email",
        body=(
            "Hola,\n\n"
            "Para terminar de crear tu cuenta en FactuMov, entrá en este link:\n\n"
            f"{_confirmation_url(raw_token)}\n\n"
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


def send_delegation_instructions_email(to: str) -> None:
    """Las instrucciones para delegar WSFE en el CUIT de FactuMov.

    Se manda al confirmar la dirección y no al registrarse: antes de confirmar no hay
    ninguna prueba de que la casilla sea de quien dice, y estas instrucciones terminan con
    alguien entrando a ARCA con su Clave Fiscal.
    """
    email.send_email(
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
