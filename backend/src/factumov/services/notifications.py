"""Los mails que manda FactuMov: asunto, cuerpo y a quién.

Separado de `email.py` a propósito: ahí vive el transporte —SMTP, TLS, timeouts— y acá el
contenido. Son las dos cosas que cambian por motivos distintos: cambiar de proveedor no
toca ni una palabra de estos textos, y corregir la redacción de un mail no debería obligar
a leer código de sockets.

Los textos van en español, como el resto de los strings de cara al usuario.
"""

import logging
from collections.abc import Sequence
from urllib.parse import quote

# Importado como módulo, no por nombre: `send_email` se resuelve en cada llamada, así que
# un test puede parchear `factumov.services.email.send_email` en un solo lugar y estas
# funciones miran el parche. Con `from ... import send_email` la referencia quedaría fija al
# importar y el parche no llegaría acá nunca.
from factumov.services import arca, email, subscription

logger = logging.getLogger(__name__)

_CONFIRMATION_PATH = "/confirmar-email"
_PASSWORD_RESET_PATH = "/restablecer-password"
_REGISTER_PATH = "/registro"
# La única pantalla de la app que no es para un usuario: donde aterriza el operador cuando dice
# que ya aceptó la designación en ARCA.
_DELEGATION_ACCEPTED_PATH = "/delegacion-aceptada"
# Los instructivos ilustrados que acompañan a los dos mails de delegación. No piden token ni
# sesión —son capturas de ARCA con los pasos numerados— y existen porque la página de ARCA es
# críptica y el texto solo no alcanza. El primero es para el contribuyente, el segundo para el
# operador de FactuMov. Sus nombres los reflejan las rutas de `App.tsx`.
_HOW_TO_DELEGATE_PATH = "/como-delegar"
_HOW_TO_ACCEPT_PATH = "/como-aceptar-delegacion"
# La app pelada, sin ninguna pantalla en particular. La usa el pie del mail de la factura, que
# es el único texto de la app dirigido a alguien que todavía no es usuario — ver
# `default_invoice_body`. Vacío y no `/registro` a propósito: en un mail de texto plano un
# dominio suelto se lee y se recuerda mucho mejor que un dominio con path, y el que llega sin
# cuenta cae en el login, que tiene su "Creá una" a la vista. El que ya la tiene, entra.
_HOME_PATH = ""

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


def send_new_user_email(user_email: str) -> None:
    """Le avisa al operador que se registró alguien.

    Es el segundo mail que no le va a un usuario, y a diferencia del de la delegación no pide
    ninguna acción: es una señal de que el producto se está usando, que en una app recién
    salida es la que se mira todos los días y hoy no existe en ningún lado — para enterarse
    hay que entrar a la base.

    **Sale del registro y no de la confirmación**, o sea que avisa de una cuenta que todavía
    no se puede usar. Es a propósito: el que se registró y no confirmó también es información,
    y encima es la mitad interesante —alguien entró, quiso, y quedó a mitad de camino—. El
    cuerpo lo dice para que nadie lea "usuario nuevo" donde dice "intento".

    Lo dispara **solo el alta de una fila nueva**. Un segundo registro sobre una dirección que
    ya estaba no es alguien registrándose: es alguien volviendo.

    Best effort y en background, y acá eso no es solo por costumbre: `register` contesta lo
    mismo exista o no la dirección, y las tres ramas mandan un mail para que las tres puedan
    fallar igual. Un mail sincrónico de más en una sola de las tres la haría más lenta que las
    otras dos y con eso contestaría, por el reloj, la pregunta que el 202 calla. Ver
    `routers/auth.register`.
    """
    settings = email.get_email_settings()
    if settings.operator_email is None:
        # INFO y no WARNING, al revés que el aviso de la delegación: allá hay alguien
        # esperando un click que nadie va a dar, acá no hay nada pendiente. Nombra la variable
        # igual, que es lo que hace falta para prenderlo.
        logger.info("Se registró %s y no hay OPERATOR_EMAIL configurado para avisar.", user_email)
        return

    email.send_email_best_effort(
        to=settings.operator_email,
        subject=f"Alguien se registró en FactuMov: {user_email}",
        body=(
            f"{user_email} acaba de crear una cuenta en FactuMov.\n\n"
            "Todavía no confirmó la dirección, así que la cuenta no se puede usar: le "
            "mandamos el link y vence en unas horas. Si confirma, le llegan solas las "
            "instrucciones para delegarnos WSFE en ARCA.\n\n"
            "No hace falta que hagas nada. Si más adelante carga un CUIT y nos designa, te "
            "va a llegar otro aviso — ese sí pide un click tuyo en ARCA.\n"
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


def default_invoice_subject(label: str, issuer_name: str) -> str:
    """El asunto que manda la app cuando el modelo no tiene uno propio.

    Lleva el número del comprobante y la razón social del emisor porque es lo que el
    destinatario ve en la lista de su casilla, y "Factura" a secas no le dice de quién es.

    Es una función y no un f-string adentro del envío desde que el asunto se puede
    personalizar: el default pasó a ser una de dos ramas, y una rama que no tiene nombre no se
    puede probar ni citar desde el endpoint que elige entre las dos.
    """
    return f"Factura {label} de {issuer_name}"


def default_invoice_body(label: str, issuer_name: str, total: str) -> str:
    """El cuerpo que manda la app cuando el modelo no tiene uno propio.

    Los importes llegan ya formateados: quien los sabe formatear es `invoice_pdf`, y hacerlo
    otra vez acá sería una segunda forma de escribir el mismo número.

    **Termina en el pie de FactuMov**, que es propaganda y está solo acá: el cuerpo que escribe
    el usuario sale tal como lo escribió. Ver `_signature`.
    """
    return (
        "Hola,\n\n"
        f"Te adjuntamos la factura {label} de {issuer_name} por $ {total}.\n\n"
        "El comprobante está autorizado por ARCA; el CAE y su vencimiento figuran al pie "
        "del PDF.\n"
        f"{_signature()}"
    )


def _signature() -> str:
    """El pie que cuenta que FactuMov existe y que hay un plan gratis.

    **Es el único texto de la app dirigido a alguien que no es usuario**: el que lee este mail
    es el cliente del que facturó, y muy probablemente alguien que también emite facturas. Es
    el lugar más barato que tiene el producto para hacerse conocer, porque el mail ya se manda
    igual.

    - **Linkea a FactuMov y no a la landing de InSoft.** Al que acaba de recibir una factura le
      sirve "yo también puedo emitir las mías", y esa respuesta es la app. La landing presenta
      a la casa de software y sus tres productos, o sea que le pide al lector que primero
      averigüe cuál de los tres es para él — un paso más para perder gente que ya estaba a un
      click. Además vive fuera de este repo y sin git, y los mails ya enviados no se pueden
      corregir: linkear a algo que este proyecto no controla es apostar a que nadie le cambie
      la URL. La casa igual está: el dominio dice `insoft.net.ar`.
    - **Dice el número del plan Free y lo saca de `FREE_MONTHLY_INVOICES`.** "Gratis" a secas
      es la clase de promesa que se lee como mentira el día que el usuario choca el quinto
      comprobante; el número exacto es más honesto y además más convincente. Sale de la
      constante y no escrito acá porque es política comercial y va a cambiar — ver
      *Monetización → Los dos planes*.
    - **Va detrás de `-- `**, que es el separador de firma de RFC 3676: los clientes de mail lo
      reconocen y muchos lo pintan en gris o lo pliegan. O sea que la propaganda queda marcada
      como una firma y no disfrazada de parte del mensaje, que es la diferencia entre un pie y
      una trampa.
    - **Solo está en el texto por default.** Al cuerpo que escribió el usuario no se le agrega
      nada: sería meterle una línea que no puso en un mail que sale con su nombre y su factura
      adentro. La consecuencia es que quien no lo quiere lo saca escribiendo su propio texto,
      que es la función Pro — y que el editor lo muestra en el placeholder, así que nadie se
      entera de este pie por un cliente suyo.
    """
    return (
        "\n-- \n"
        "Esta factura se emitió con FactuMov. Vos también podés emitir las tuyas: "
        f"{subscription.FREE_MONTHLY_INVOICES} comprobantes por mes, gratis, en "
        f"{_url(_HOME_PATH)}\n"
    )


def send_invoice_email(
    to: str,
    label: str,
    issuer_name: str,
    total: str,
    pdf: bytes,
    filename: str,
    cc: Sequence[str] = (),
    subject: str | None = None,
    body: str | None = None,
) -> None:
    """La factura emitida, con el PDF adjunto.

    `cc` son las direcciones que el cliente tiene cargadas para recibir copia —el contador,
    el gestor—. Van en la cabecera `Cc` y no cambian ni el asunto ni el cuerpo: el mail es el
    mismo, solo que a más de un buzón.

    Usa `send_email` y no la versión best effort: este mail **es** el producto del request —
    quien apretó "Mandar por email" no pidió otra cosa— así que si no sale, el endpoint tiene
    que decirlo. Es el mismo criterio que el mail de confirmación de cuenta.

    `subject` y `body` son el texto propio del modelo del que salió la factura, cuando lo tiene
    y cuando el plan lo permite. Quien decide esas dos cosas es el endpoint de envío, que es el
    que conoce la factura y la cuenta; acá llegan resueltos, porque este módulo escribe textos
    y no consulta planes.

    **Caen en el default por separado.** Son dos `or` y no un `if` sobre los dos juntos: el que
    solo quiso cambiar el cuerpo conserva el asunto que arma la app, que es el que lleva el
    número del comprobante y la razón social. `or` y no `is None` porque un texto en blanco es
    lo mismo que ninguno — el schema ya lo convierte a `None` al guardarlo, y esto es la red
    por si algún día entra por otro lado.

    Lo que **no** cambia con un texto propio es el adjunto: el PDF va siempre. El texto
    acompaña al comprobante, no lo reemplaza.
    """
    email.send_email(
        to=to,
        subject=subject or default_invoice_subject(label, issuer_name),
        body=body or default_invoice_body(label, issuer_name, total),
        attachments=[email.Attachment(filename=filename, content=pdf)],
        cc=cc,
    )


def send_delegation_instructions_email(to: str) -> None:
    """Las instrucciones para delegar WSFE en el CUIT de FactuMov.

    Se manda al confirmar la dirección y no al registrarse: antes de confirmar no hay
    ninguna prueba de que la casilla sea de quien dice, y estas instrucciones terminan con
    alguien entrando a ARCA con su Clave Fiscal.

    Best effort: sale después de que la confirmación ya quedó guardada. Fallar el request
    por este mail mandaría al usuario a reintentar con un token que ya se consumió, o sea a
    un 400 sobre una cuenta que en realidad quedó confirmada.

    **Linkea el instructivo ilustrado** (`_HOW_TO_DELEGATE_PATH`, la pantalla
    `/como-delegar`): la página de ARCA es críptica y los pasos en texto no alcanzan.
    Igual van en el cuerpo, porque un mail que solo dice "entrá a este link" no sirve si el
    link no carga y no lo lee bien un lector de pantalla.
    """
    email.send_email_best_effort(
        to=to,
        subject="Cómo autorizar a FactuMov a emitir tus facturas",
        body=(
            "Hola,\n\n"
            "Tu cuenta ya está confirmada. Para que FactuMov pueda emitir facturas a "
            "nombre de tu CUIT, ARCA necesita que lo autorices vos. Es un trámite online, "
            "gratis, y se hace una sola vez por CUIT.\n\n"
            "Te lo mostramos paso a paso, con una captura de cada pantalla:\n\n"
            f"{_url(_HOW_TO_DELEGATE_PATH)}\n\n"
            "En resumen:\n\n"
            "1. Entrá a arca.gob.ar con tu Clave Fiscal y abrí 'Administrador de "
            "Relaciones'.\n"
            "2. Elegí 'Nueva Relación'. En 'Representado' dejá tu propio nombre.\n"
            "3. En 'Servicio' buscá, dentro de ARCA -> WebServices, 'Facturación "
            "Electrónica'.\n"
            f"4. Como representante, indicá el CUIT {arca.get_delegate_tax_id()} "
            "(FactuMov), y confirmá.\n\n"
            "Después cargá tu CUIT en FactuMov, en 'Identidades fiscales': verificamos la "
            "autorización solos y te avisamos por mail cuando puedas emitir. No hace falta "
            "que nos escribas.\n"
        ),
    )


def send_delegation_pending_email(
    tax_id: str, identity_name: str, user_email: str, raw_token: str
) -> None:
    """Le avisa al operador que hay una designación esperando que la acepte en ARCA.

    **Es el único mail de la app que no le va a un usuario**, y existe porque hay un paso
    del alta que ninguna máquina puede dar: aceptar la designación en «Aceptación de
    Designación» es un click con Clave Fiscal, y ARCA no publica las designaciones
    pendientes por ningún web service. O sea que la app no puede enterarse sola de que
    alguien la está esperando.

    Lo que sí puede es enterarse por el usuario. Este mail sale del momento exacto en que
    él dice "ya delegué" y ARCA sigue diciendo que no — el único instante en que existe
    evidencia de que hay una persona esperando del otro lado.

    **Describe dos pasos y no uno, corregido el 2026-08-29.** Las instrucciones anteriores
    terminaban en «aceptá la designación», y eso no alcanza: aceptarla habilita a la *persona*,
    pero WSAA le emite el ticket al *certificado* y la lista de relaciones que WSFE valida es la
    del certificado. Falta entonces crear a mano la relación que la aceptación no crea —el
    servicio, con el **computador** como representante— y hay que hacerlo por cada CUIT. Sin
    eso, una designación perfectamente aceptada sigue contestando el código 600, que es
    indistinguible de no haber hecho nada. Ver *Delegar tiene dos partes* en `docs/arca.md`.
    Los dos pasos van también ilustrados en `/como-aceptar-delegacion` (`_HOW_TO_ACCEPT_PATH`),
    que el cuerpo linkea antes del texto — la pantalla de ARCA es críptica y una captura con
    el botón marcado es lo que evita el error de dejar el propio CUIT como Representante.

    **Termina con un link, agregado el 2026-08-29.** Los dos pasos se hacen en ARCA, que no le
    cuenta nada a nadie: hasta ahora el operador los terminaba y no tenía forma de saber si
    habían quedado bien, ni el usuario de enterarse, hasta que al barrido de los quince minutos
    le tocara. El link contesta las dos cosas en el momento —le pregunta a ARCA y le avisa al
    usuario si dice que sí— y sobre todo contesta *que no* cuando falta el paso 2, que es el
    error que este mail existe para prevenir y el único momento en que el operador todavía
    tiene las pantallas de ARCA abiertas para corregirlo.

    Best effort, y sale una sola vez por identidad: lo dispara el **primer** aviso, no cada
    click. Ver `crud/fiscal_identity.mark_delegation_claimed`. Esa unicidad es también la del
    link: hay un solo token por identidad justamente porque hay un solo mail.

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
            "habilita, así que faltan DOS pasos, no uno.\n\n"
            "Están los dos ilustrados, con una captura de cada pantalla de ARCA, acá:\n\n"
            f"{_url(_HOW_TO_ACCEPT_PATH)}\n\n"
            "En texto, para tenerlo a mano: entrá a arca.gob.ar con la Clave Fiscal de "
            "FactuMov y abrí el 'Administrador de Relaciones de Clave Fiscal'.\n\n"
            "PASO 1 - Aceptar la designación\n"
            "  a. Entrá en 'Aceptación de Designación'.\n"
            f"  b. Aceptá la fila del representado {tax_id}, servicio Facturación "
            "Electrónica.\n\n"
            "PASO 2 - Darle ese servicio al certificado\n"
            "  a. Volvé al Administrador de Relaciones y elegí 'Nueva Relación'.\n"
            f"  b. En Representado poné {tax_id}.\n"
            "  c. En Servicio: BUSCAR -> WebServices -> Facturación Electrónica.\n"
            "  d. En Representante: BUSCAR -> el COMPUTADOR cuyo certificado usa "
            "FactuMov,\n"
            "     NO tu CUIT. Si dejás tu CUIT, la relación queda colgada de la persona\n"
            "     y no del certificado. WSAA le emite el ticket al certificado, y la\n"
            "     lista de relaciones que WSFE valida es la de él: sin este paso sigue\n"
            "     contestando el código 600 igual que si no hubieras aceptado nada.\n\n"
            "Los dos pasos van por cada CUIT que nos delegue. No alcanza con haberlos "
            "hecho una vez.\n\n"
            "Cuando termines los dos pasos, entrá acá para avisarle a FactuMov:\n\n"
            f"{_url(_DELEGATION_ACCEPTED_PATH, raw_token)}\n\n"
            "Ese link le pregunta a ARCA en el momento y te contesta. Si dice que todavía no, "
            "casi seguro falta el PASO 2: volvé, completalo y entrá al link de nuevo. Si dice "
            "que sí, le avisamos al usuario en el acto y no queda nada más por hacer.\n\n"
            "El usuario ya sabe que la demora es nuestra y está esperando. No hace falta que "
            "le contestes: si no entrás al link, FactuMov reverifica igual contra ARCA cada "
            "15 minutos y le avisa cuando quede habilitado.\n"
        ),
    )


def send_delegation_ready_email(to: str, identity_name: str, tax_id: str) -> None:
    """Le avisa al usuario que su CUIT ya puede emitir.

    Cierra la única espera de la app que el usuario no puede resolver ni observar. Él hizo
    su parte, le dijimos que faltaba un paso nuestro, y desde entonces no tiene forma de
    saber cuándo terminó salvo volver a la pantalla a probar. Este mail es el "ya está".

    Lo dispara el barrido de `services/delegation_watch.py`, o sea que llega solo. Best
    effort: la verificación ya quedó guardada y no se puede deshacer por un SMTP caído — y
    si el mail no sale, el usuario se entera igual la próxima vez que abra la pantalla.
    """
    email.send_email_best_effort(
        to=to,
        subject=f"Ya podés emitir con el CUIT {tax_id}",
        body=(
            "Hola,\n\n"
            f"Ya aceptamos la designación en ARCA: la identidad fiscal «{identity_name}» "
            f"(CUIT {tax_id}) quedó habilitada y podés emitir facturas con ella.\n\n"
            "No hace falta que hagas nada más — entrá a FactuMov y emití.\n"
        ),
    )
