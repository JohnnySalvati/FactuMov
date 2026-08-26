from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from sqlalchemy.orm import Session

from factumov.crud import email_confirmation as email_confirmation_crud
from factumov.crud import user as user_crud
from factumov.crud import user_session as user_session_crud
from factumov.dependencies import (
    SESSION_COOKIE_NAME,
    CurrentSessionDep,
    CurrentUserDep,
    SessionDep,
)
from factumov.exceptions import DuplicateUserEmailError
from factumov.models.user import User
from factumov.schemas.auth import (
    ConfirmEmailRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResendConfirmationRequest,
    UserRead,
)

# Importado como módulo y no por nombre: así un test puede parchear
# `notifications.send_confirmation_email` y el router mira el parche. Con
# `from ... import send_confirmation_email` la referencia se resuelve al importar y el test
# terminaría parcheando una copia que nadie lee — mismo criterio que `MAX_UPLOAD_BYTES`.
from factumov.services import notifications
from factumov.services.rate_limit import RateLimiter
from factumov.services.security import (
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)

# Vencimiento absoluto: se fija en el login y no se extiende por usar la sesión.
SESSION_LIFETIME = timedelta(days=7)

# Ventana para confirmar la dirección. Larga a propósito: el mail puede caer en spam y
# tardar en aparecer, y el costo de que venza es un reenvío, no una cuenta perdida.
CONFIRMATION_LIFETIME = timedelta(hours=24)

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

# Por dirección, además de por IP. La de por IP no alcanza para el caso que más molesta: un
# atacante con muchas IPs usando el registro o el reenvío como mail bomb contra una sola
# casilla. Es también el límite que el borde no puede aplicar, porque nginx no lee el body.
_EMAIL_LIMITER = RateLimiter(limit=3, window_seconds=60 * 60)

_RATE_LIMITED_DETAIL = "Demasiados intentos. Esperá un rato y probá de nuevo."

ALL_LIMITERS = (_LOGIN_LIMITER, _REGISTER_IP_LIMITER, _RESEND_IP_LIMITER, _EMAIL_LIMITER)


def _client_key(request: Request) -> str:
    """La IP del cliente, tal como la ve la app.

    Se lee de `request.client` y no del header `X-Forwarded-For`. Detrás de un proxy es
    uvicorn —con `--proxy-headers` y `--forwarded-allow-ips`— el que reescribe
    `request.client` a partir de ese header, y solo si el que se conectó es un proxy de
    confianza. Leer el header acá saltearía esa decisión, y un header que cualquiera puede
    inventar convierte el limitador en un adorno: se manda uno distinto en cada request y no
    hay límite, o se manda el de otro y se lo deja afuera a él.
    """
    return request.client.host if request.client else "sin-ip"


def _enforce(limiter: RateLimiter, key: str) -> None:
    retry_after = limiter.check(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail=_RATE_LIMITED_DETAIL,
            # Segundos enteros y redondeando para arriba: un `Retry-After: 0` invitaría a
            # reintentar de inmediato, que es justo lo que se está tratando de frenar.
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


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


def _issue_confirmation(background: BackgroundTasks, db: Session, user: User) -> None:
    """Emite un token de confirmación y encola el mail que lo lleva.

    El token nuevo no invalida los anteriores. Un usuario que pidió un reenvío puede tener
    dos mails abiertos, y romperle el link del primero no protege nada: cada token es de un
    solo uso, vence solo, y apunta al mismo usuario que el otro.

    El mail va en un background task para que la latencia de SMTP no esté en el camino del
    request.

    El `commit` explícito es la parte que no se puede sacar, y va contra la convención del
    proyecto —commitea `get_db`, el CRUD solo flushea— por dos razones medidas, no
    supuestas. En FastAPI 0.141 los background tasks corren **antes** del cierre de las
    dependencias con `yield`, o sea antes del commit de `get_db`. Sin este commit:

    - el mail sale con un token que todavía no está en la base, y si la transacción termina
      abortando, el usuario recibe un link que nunca va a funcionar;
    - y la transacción queda abierta durante toda la conexión SMTP, que puede tardar hasta
      `SMTP_TIMEOUT_SECONDS`. Diez segundos de transacción abierta por registro es el
      problema más caro de los dos.

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
    background.add_task(
        notifications.send_confirmation_email,
        user.email,
        raw_token,
        int(CONFIRMATION_LIFETIME.total_seconds() // 3600),
    )


@router.post("/register", status_code=202, response_model=MessageResponse)
def register(
    data: RegisterRequest, request: Request, background: BackgroundTasks, db: SessionDep
) -> MessageResponse:
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
    """
    # Los dos límites se cuentan antes de mirar la base, y eso es parte de la propiedad
    # anti-enumeración: si el contador solo avanzara cuando la dirección existe, el 429
    # llegaría antes para las registradas y contestaría la pregunta que el 202 calla.
    _enforce(_REGISTER_IP_LIMITER, _client_key(request))
    _enforce(_EMAIL_LIMITER, data.email)

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
            _issue_confirmation(background, db, user)
    elif user.email_confirmed_at is None:
        _issue_confirmation(background, db, user)
    else:
        # No hay nada escrito que commitear en esta rama, pero el `commit` cierra igual la
        # transacción de lectura antes de que el background task se cuelgue del SMTP.
        db.commit()
        background.add_task(notifications.send_already_registered_email, user.email)

    return MessageResponse(detail=_REGISTRATION_ACCEPTED_DETAIL)


@router.post("/resend-confirmation", status_code=202, response_model=MessageResponse)
def resend_confirmation(
    data: ResendConfirmationRequest,
    request: Request,
    background: BackgroundTasks,
    db: SessionDep,
) -> MessageResponse:
    """Reenvía la confirmación. Contesta lo mismo exista o no la dirección."""
    _enforce(_RESEND_IP_LIMITER, _client_key(request))
    _enforce(_EMAIL_LIMITER, data.email)
    user = user_crud.get_by_email(db, data.email)
    if user is not None and user.is_active and user.email_confirmed_at is None:
        _issue_confirmation(background, db, user)
    return MessageResponse(detail=_RESEND_ACCEPTED_DETAIL)


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
    _enforce(_LOGIN_LIMITER, _client_key(request))
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
