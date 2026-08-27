import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from sqlalchemy.orm import Session

from factumov.crud import email_confirmation as email_confirmation_crud
from factumov.crud import password_reset as password_reset_crud
from factumov.crud import user as user_crud
from factumov.crud import user_session as user_session_crud
from factumov.dependencies import (
    SESSION_COOKIE_NAME,
    CurrentSessionDep,
    CurrentUserDep,
    SessionDep,
    client_key,
    enforce_rate_limit,
)
from factumov.exceptions import DuplicateUserEmailError
from factumov.models.user import User
from factumov.schemas.auth import (
    ConfirmEmailRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResendConfirmationRequest,
    ResetPasswordRequest,
    UserRead,
)

# Importado como módulo y no por nombre: así un test puede parchear
# `notifications.send_confirmation_email` y el router mira el parche. Con
# `from ... import send_confirmation_email` la referencia se resuelve al importar y el test
# terminaría parcheando una copia que nadie lee — mismo criterio que `MAX_UPLOAD_BYTES`.
from factumov.services import notifications
from factumov.services.email import EmailDeliveryError
from factumov.services.rate_limit import RateLimiter
from factumov.services.security import (
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)

# Vencimiento absoluto: se fija en el login y no se extiende por usar la sesión.
SESSION_LIFETIME = timedelta(days=7)

# Ventana para confirmar la dirección. Larga a propósito: el mail puede caer en spam y
# tardar en aparecer, y el costo de que venza es un reenvío, no una cuenta perdida.
CONFIRMATION_LIFETIME = timedelta(hours=24)

# Mucho más corta que la de confirmación, y no por simetría rota sino porque lo que está en
# juego es distinto. Un token de confirmación vencido cuesta un reenvío; uno de reset vivo es
# la cuenta entera para cualquiera que llegue a esa casilla. El usuario acaba de pedirlo y lo
# va a usar en el minuto siguiente, así que una hora ya es holgado.
PASSWORD_RESET_LIFETIME = timedelta(hours=1)

# Mismo cuerpo para email desconocido, contraseña incorrecta y usuario sin confirmar o dado
# de baja. "Confirmá tu email" sería un oráculo de enumeración.
_INVALID_CREDENTIALS_DETAIL = "Email o contraseña incorrectos"

# El registro contesta esto pase lo que pase: dirección nueva, dirección sin confirmar y
# dirección ya confirmada dan el mismo 202 con el mismo texto. Es afirmativo y no
# condicional ("si la dirección...") porque las tres ramas mandan un mail: las dos primeras
# el de confirmación, la tercera el aviso de que la cuenta ya existe. No hay nada que
# condicionar y el usuario recibe una instrucción clara en vez de un acertijo.
_REGISTRATION_ACCEPTED_DETAIL = "Te mandamos un mail a esa dirección. Revisá tu casilla."

# El reenvío sí es condicional: para una dirección que no existe no hay ningún mail que
# mandar, así que prometer uno sería mentir.
_RESEND_ACCEPTED_DETAIL = (
    "Si esa dirección está registrada y falta confirmarla, te mandamos un mail."
)

# Token desconocido, vencido y ya usado comparten respuesta. Distinguirlos no aportaría
# nada: el remedio de los tres es pedir un mail nuevo, y el texto lo dice.
_INVALID_CONFIRMATION_DETAIL = "El link no es válido o ya venció. Pedí uno nuevo."

# El reset contesta lo mismo exista o no la cuenta, igual que el registro, y por el mismo
# motivo. Es afirmativo porque las dos ramas mandan un mail: la que tiene cuenta recibe el
# link, y la que no, un aviso de que no hay ninguna cuenta usable con esa dirección.
_FORGOT_ACCEPTED_DETAIL = "Te mandamos un mail a esa dirección. Revisá tu casilla."

_INVALID_RESET_DETAIL = "El link no es válido o ya venció. Pedí uno nuevo."

_PASSWORD_CHANGED_DETAIL = "Listo, tu contraseña cambió. Entrá con la nueva."

# 503 y no 500: no es un bug nuestro sino un servicio del que dependemos que no está. El
# texto no dice por qué —la config del SMTP no le importa al usuario y describirla cuenta
# cómo está armado nuestro lado— pero sí dice lo único accionable, que es reintentar.
_MAIL_UNAVAILABLE_DETAIL = (
    "No pudimos mandarte el mail. Es un problema nuestro, no de tu cuenta: probá de nuevo "
    "en unos minutos."
)

# --- Rate limiting --------------------------------------------------------------------
#
# Los cuatro límites son por proceso; el techo real va en el borde (ver
# `services/rate_limit.py`). Los números están elegidos para no estorbarle nunca a un
# usuario real: nadie se registra cinco veces por hora ni pide tres reenvíos seguidos.
#
# El login es el más generoso de los cuatro porque el que se equivoca de contraseña de
# verdad reintenta varias veces seguidas, y un límite corto ahí se siente como una cuenta
# rota. Contra el credential stuffing, lo que importa no es que sean diez o veinte sino que
# no sean diez mil.
_LOGIN_LIMITER = RateLimiter(limit=10, window_seconds=15 * 60)
_REGISTER_IP_LIMITER = RateLimiter(limit=5, window_seconds=60 * 60)
_RESEND_IP_LIMITER = RateLimiter(limit=5, window_seconds=60 * 60)
_FORGOT_IP_LIMITER = RateLimiter(limit=5, window_seconds=60 * 60)

# El que **usa** el link no manda mails, así que no comparte el presupuesto de casilla. Su
# límite es por otra cosa: hashea con argon2, o sea que es el único endpoint sin sesión que
# quema ~100 ms de CPU por request. El 422 por contraseña corta ni siquiera llega acá —lo
# corta Pydantic antes—, así que diez es de sobra para quien se equivoca tipeando.
_RESET_IP_LIMITER = RateLimiter(limit=10, window_seconds=60 * 60)

# Por dirección, además de por IP. La de por IP no alcanza para el caso que más molesta: un
# atacante con muchas IPs usando el registro, el reenvío o el "olvidé mi contraseña" como
# mail bomb contra una sola casilla. Es también el límite que el borde no puede aplicar,
# porque nginx no lee el body.
#
# Lo comparten los tres endpoints que le mandan mail a la dirección del body. Presupuestos
# separados dejarían triplicar el bombardeo alternando entre ellos, que es exactamente el
# ataque del que este limitador defiende.
_EMAIL_LIMITER = RateLimiter(limit=3, window_seconds=60 * 60)

# `_client_key` y `_enforce` se mudaron a `dependencies.py` cuando los endpoints de ARCA
# empezaron a necesitarlas: importarlas de este router habría sido un router hermano
# importando de otro. Lo mismo con la tupla `ALL_LIMITERS`, que ahora es el registro
# automático de `rate_limit.reset_all()`.


router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _deliver(send: Callable[[], None]) -> None:
    """Manda un mail que es el producto del request, o contesta 503.

    Es el reemplazo de la política vieja, en la que todos los mails salían en un
    `BackgroundTasks` y `send_email` se tragaba el error. Esa combinación tenía una
    consecuencia que costó descubrir: con el SMTP mal configurado, el registro contestaba un
    202 alegre y el mail no salía nunca. La respuesta afirmaba algo que el sistema no había
    hecho, y el único rastro era una línea de log.

    El costo de traer el envío adentro del request es latencia —hasta
    `SMTP_TIMEOUT_SECONDS`— y se paga solo en los cuatro endpoints cuyo producto *es* el
    mail. Se paga barato: son operaciones que un usuario hace una vez, no cien por semana, y
    a cambio la respuesta dice la verdad. Los mails que solo acompañan a algo ya guardado
    siguen yendo en background y sin poder tumbar nada — ver `send_email_best_effort`.

    El detalle de la falla se loguea acá y no viaja en la respuesta: nombrar el servidor o la
    variable que falta cuenta cómo está armado nuestro lado, y al usuario no le sirve.
    """
    try:
        send()
    except EmailDeliveryError as error:
        logger.exception("No se pudo entregar un mail; el endpoint contesta 503")
        raise HTTPException(status_code=503, detail=_MAIL_UNAVAILABLE_DETAIL) from error


def _issue_confirmation(db: Session, user: User) -> None:
    """Emite un token de confirmación y manda el mail que lo lleva.

    El token nuevo no invalida los anteriores. Un usuario que pidió un reenvío puede tener
    dos mails abiertos, y romperle el link del primero no protege nada: cada token es de un
    solo uso, vence solo, y apunta al mismo usuario que el otro.

    El `commit` explícito va contra la convención del proyecto —commitea `get_db`, el CRUD
    solo flushea— y sigue siendo obligatorio, ahora por una razón sola en vez de dos. Sin él
    la transacción queda abierta durante toda la conexión SMTP, hasta
    `SMTP_TIMEOUT_SECONDS`: diez segundos de transacción abierta por registro. La otra razón
    —que el mail salía con un token que todavía no estaba en la base, porque los background
    tasks de FastAPI 0.141 corren antes del cierre de las dependencias con `yield`— dejó de
    aplicar cuando el envío pasó a ser sincrónico, pero el orden que exigía es el mismo:
    primero se guarda el token, después se manda el link que lo nombra.

    Commitear acá y de nuevo en `get_db` es inofensivo: el segundo commit no tiene nada que
    escribir. En los tests el override cuelga de una sesión con `join_transaction_mode=
    "create_savepoint"`, así que este commit cierra el savepoint y el rollback del fixture
    `db` sigue revirtiendo todo.
    """
    raw_token = generate_opaque_token()
    email_confirmation_crud.create(
        db,
        user_id=user.id,
        token_hash=hash_opaque_token(raw_token),
        expires_at=datetime.now(UTC) + CONFIRMATION_LIFETIME,
    )
    db.commit()
    address = user.email
    _deliver(
        lambda: notifications.send_confirmation_email(
            address, raw_token, int(CONFIRMATION_LIFETIME.total_seconds() // 3600)
        )
    )


@router.post("/register", status_code=202, response_model=MessageResponse)
def register(data: RegisterRequest, request: Request, db: SessionDep) -> MessageResponse:
    """Alta self-serve. La respuesta no depende de si la dirección ya existía.

    La contraseña se hashea **antes** de buscar al usuario, aunque en dos de las tres ramas
    el hash termine sin usarse. Argon2 cuesta ~100 ms y es lo más caro del endpoint: si solo
    se hasheara al crear, una dirección ya registrada contestaría notoriamente más rápido y
    el tiempo de respuesta sería el oráculo de enumeración que el cuerpo idéntico evita. Es
    la misma maniobra que el hash dummy del login, con el desperdicio del lado contrario.

    Una dirección sin confirmar recibe un token nuevo pero **conserva su contraseña**. Pisar
    la contraseña de una cuenta pendiente sería tomarla: al atacante le alcanzaría con
    registrarse encima y esperar a que el dueño real —que estaba esperando un mail— haga
    clic en el link de confirmación que le llegue. Quien se equivocó de contraseña al
    registrarse tiene que usar el reset, no un segundo registro.

    **Las tres ramas mandan un mail, y las tres pueden contestar 503 si no sale.** Eso no es
    casualidad: si alguna no mandara nada, nunca podría fallar, y un 503 pasaría a significar
    "tu dirección cae en las otras dos ramas". La propiedad anti-enumeración no la sostiene
    solo el cuerpo idéntico — la sostiene que las tres ramas hagan lo mismo.

    Un 503 llega con la fila del usuario ya creada y commiteada. Es correcto y no hace falta
    deshacerlo: la cuenta queda sin confirmar, o sea inservible, y el reintento cae en la
    rama de "dirección sin confirmar" y le emite un token nuevo.
    """
    # Los dos límites se cuentan antes de mirar la base, y eso es parte de la propiedad
    # anti-enumeración: si el contador solo avanzara cuando la dirección existe, el 429
    # llegaría antes para las registradas y contestaría la pregunta que el 202 calla.
    enforce_rate_limit(_REGISTER_IP_LIMITER, client_key(request))
    enforce_rate_limit(_EMAIL_LIMITER, data.email)

    hashed_password = hash_password(data.password.get_secret_value())
    user = user_crud.get_by_email(db, data.email)

    if user is None:
        try:
            user = user_crud.create(db, email=data.email, hashed_password=hashed_password)
        except DuplicateUserEmailError:
            # Carrera: otro request insertó la misma dirección entre el SELECT y el INSERT.
            # El rollback es obligatorio y no cosmético — la transacción quedó abortada por
            # la IntegrityError, y sin esto el `db.commit()` de `get_db` explota con un
            # PendingRollbackError y el 202 se convierte en 500. El que ganó la carrera ya
            # mandó el mail, así que acá no queda nada por hacer.
            db.rollback()
        else:
            _issue_confirmation(db, user)
    elif user.email_confirmed_at is None:
        _issue_confirmation(db, user)
    else:
        # No hay nada escrito que commitear en esta rama, pero el `commit` cierra igual la
        # transacción de lectura antes de que el envío se cuelgue del SMTP.
        db.commit()
        address = user.email
        _deliver(lambda: notifications.send_already_registered_email(address))

    return MessageResponse(detail=_REGISTRATION_ACCEPTED_DETAIL)


@router.post("/resend-confirmation", status_code=202, response_model=MessageResponse)
def resend_confirmation(
    data: ResendConfirmationRequest, request: Request, db: SessionDep
) -> MessageResponse:
    """Reenvía la confirmación. Contesta lo mismo exista o no la dirección.

    Es el único de los cuatro endpoints de mail donde una rama no manda nada, y por eso su
    texto es condicional ("si esa dirección está registrada..."): para una dirección
    confirmada o inexistente no hay ningún mail que mandar, y prometerlo sería mentir. La
    contrapartida es que acá el 503 sí distingue una rama de la otra. Se acepta porque lo
    que revela es "esa dirección está registrada **y sin confirmar**", que es un estado
    transitorio de horas, y porque la alternativa —mandar un mail a direcciones que no
    pidieron nada— convierte el reenvío en el mail bomb del que hay que defenderse.
    """
    enforce_rate_limit(_RESEND_IP_LIMITER, client_key(request))
    enforce_rate_limit(_EMAIL_LIMITER, data.email)
    user = user_crud.get_by_email(db, data.email)
    if user is not None and user.is_active and user.email_confirmed_at is None:
        _issue_confirmation(db, user)
    return MessageResponse(detail=_RESEND_ACCEPTED_DETAIL)


@router.post("/forgot-password", status_code=202, response_model=MessageResponse)
def forgot_password(
    data: ForgotPasswordRequest, request: Request, db: SessionDep
) -> MessageResponse:
    """Manda el link para elegir una contraseña nueva. Contesta lo mismo exista o no la cuenta.

    **Funciona sobre una cuenta sin confirmar**, y eso no es un descuido sino el motivo por el
    que esta unidad existe. Quien se equivocó de contraseña al registrarse no tenía ninguna
    salida: el segundo registro no pisa la contraseña —a propósito, ver `register`— así que
    la cuenta quedaba con una contraseña que nadie sabe y una dirección que nadie puede
    volver a usar. El reset es la única puerta, y por eso no puede exigir estar confirmado.

    Una cuenta dada de baja no recibe link. Cae en la rama del aviso, que no dice "no
    existe": decirlo sería mentirle a su dueño.
    """
    enforce_rate_limit(_FORGOT_IP_LIMITER, client_key(request))
    enforce_rate_limit(_EMAIL_LIMITER, data.email)

    user = user_crud.get_by_email(db, data.email)
    if user is None or not user.is_active:
        db.commit()
        address = data.email
        _deliver(lambda: notifications.send_no_account_email(address))
    else:
        raw_token = generate_opaque_token()
        password_reset_crud.create(
            db,
            user_id=user.id,
            token_hash=hash_opaque_token(raw_token),
            expires_at=datetime.now(UTC) + PASSWORD_RESET_LIFETIME,
        )
        # Mismo commit explícito, mismo motivo que en `_issue_confirmation`: el token tiene
        # que estar guardado antes de que salga el mail que lo lleva, y la transacción no
        # puede quedar abierta durante la conexión SMTP.
        db.commit()
        address = user.email
        minutes = int(PASSWORD_RESET_LIFETIME.total_seconds() // 60)
        _deliver(lambda: notifications.send_password_reset_email(address, raw_token, minutes))

    return MessageResponse(detail=_FORGOT_ACCEPTED_DETAIL)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    data: ResetPasswordRequest, request: Request, background: BackgroundTasks, db: SessionDep
) -> MessageResponse:
    """Consume el token y deja la contraseña nueva.

    No abre sesión, por lo mismo que la confirmación no la abre: el token vivió en una
    casilla de mail, y convertirlo en cookie dejaría adentro a cualquiera con acceso a ese
    mensaje. El usuario entra una vez con la contraseña que acaba de elegir.

    **Confirma la dirección si estaba sin confirmar.** Haber abierto este link prueba
    exactamente lo mismo que prueba el de confirmación: que quien lo abrió tiene la casilla.
    Sin esto, la salida que el reset le da al que se equivocó de contraseña al registrarse
    sería falsa — cambiaría la contraseña y seguiría sin poder entrar, con el mismo 401 de
    siempre y sin nada que le explique por qué. Y como la confirmación es lo que dispara las
    instrucciones de delegación, ese mail sale acá también la primera vez.

    **Cierra todas las sesiones.** Quien resetea porque sospecha que alguien le entró tiene
    que quedarse solo adentro: sin esto, la sesión ajena sigue viva hasta una semana y el
    cambio de contraseña no la toca.

    El hash de argon2 se calcula **después** de validar el token, al revés que en el registro.
    Allá el costo se paga siempre para que el tiempo de respuesta no delate si la dirección
    existía; acá no hay nada que ocultar —el 200 y el 400 ya dicen si el token servía— y
    hashear antes solo le regalaría 100 ms de CPU a cualquiera que postee un token inventado.
    """
    enforce_rate_limit(_RESET_IP_LIMITER, client_key(request))

    reset = password_reset_crud.get_pending_by_token_hash(db, hash_opaque_token(data.token))
    if reset is None or not reset.user.is_active:
        raise HTTPException(status_code=400, detail=_INVALID_RESET_DETAIL)

    user = reset.user
    was_unconfirmed = user.email_confirmed_at is None
    user_crud.set_password(db, user, hash_password(data.password.get_secret_value()))
    password_reset_crud.consume(db, reset)
    # El consumido primero y los demás después: la fila de este token queda marcada como
    # usada —que es un hecho— y las otras como inválidas. Las dos cosas se escriben en
    # `used_at`, pero el orden deja el rastro en el orden correcto.
    password_reset_crud.invalidate_all_for_user(db, user.id)
    user_session_crud.revoke_all_for_user(db, user.id)
    user_crud.confirm_email(db, user)
    db.commit()

    # Los dos van en background y son best effort: la contraseña ya cambió y las sesiones ya
    # se cerraron. Un 503 acá mandaría al usuario a reintentar con un token que se consumió,
    # o sea a un 400 sobre una cuenta cuya contraseña en realidad sí cambió.
    background.add_task(notifications.send_password_changed_email, user.email)
    if was_unconfirmed:
        background.add_task(notifications.send_delegation_instructions_email, user.email)

    return MessageResponse(detail=_PASSWORD_CHANGED_DETAIL)


@router.post("/confirm", response_model=UserRead)
def confirm_email(data: ConfirmEmailRequest, background: BackgroundTasks, db: SessionDep) -> User:
    """Consume el token y habilita la cuenta.

    No deja la sesión abierta. Sería mejor UX, pero el token viene de un link que vivió un
    día entero en una casilla de mail: convertirlo en cookie de sesión haría que cualquiera
    con acceso a ese mensaje quede logueado. Pedir la contraseña una vez después de
    confirmar cierra eso y cuesta una pantalla.

    El mail con las instrucciones de delegación sale acá y no en el registro: recién con la
    dirección confirmada hay alguna prueba de que la casilla es de quien dice, y el mail
    termina con alguien entrando a ARCA con su Clave Fiscal. Sale solo la primera vez, para
    que reconfirmar no lo repita.
    """
    confirmation = email_confirmation_crud.get_pending_by_token_hash(
        db, hash_opaque_token(data.token)
    )
    if confirmation is None or not confirmation.user.is_active:
        raise HTTPException(status_code=400, detail=_INVALID_CONFIRMATION_DETAIL)

    user = confirmation.user
    was_unconfirmed = user.email_confirmed_at is None
    email_confirmation_crud.consume(db, confirmation)
    user_crud.confirm_email(db, user)
    if was_unconfirmed:
        # Mismo commit explícito que en `_issue_confirmation`, y por el segundo de sus dos
        # motivos: acá el mail no lleva ningún token, pero sí abriría una conexión SMTP con
        # la transacción todavía abierta.
        db.commit()
        background.add_task(notifications.send_delegation_instructions_email, user.email)
    return user


@router.post("/login", response_model=UserRead)
def login(data: LoginRequest, request: Request, response: Response, db: SessionDep) -> User:
    enforce_rate_limit(_LOGIN_LIMITER, client_key(request))
    user = user_crud.get_by_email(db, data.email)
    # La verificación corre siempre, incluso sin usuario: `verify_password` acepta `None` y
    # compara contra un hash dummy para que el email desconocido cueste lo mismo que la
    # contraseña equivocada. Cortar antes acá reabriría el oráculo de timing.
    password_ok = verify_password(
        data.password.get_secret_value(), user.hashed_password if user else None
    )
    if user is None or not password_ok or not user.is_active or user.email_confirmed_at is None:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS_DETAIL)

    raw_token = generate_opaque_token()
    user_session_crud.create(
        db,
        user_id=user.id,
        token_hash=hash_opaque_token(raw_token),
        expires_at=datetime.now(UTC) + SESSION_LIFETIME,
    )
    _set_session_cookie(response, raw_token)
    return user


@router.post("/logout", status_code=204)
def logout(user_session: CurrentSessionDep, response: Response, db: SessionDep) -> None:
    """Revoca la sesión actual y borra la cookie.

    Depende de la sesión y no del usuario a propósito: un usuario dado de baja mientras
    tenía la sesión abierta igual tiene que poder cerrarla. `revoked_at` deja la fila en su
    lugar, así que repetir el logout es inofensivo.
    """
    user_session_crud.revoke(db, user_session)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUserDep) -> User:
    return current_user
