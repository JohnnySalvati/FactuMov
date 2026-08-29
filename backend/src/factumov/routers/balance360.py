"""La conexión del usuario con su Balance360, y el registro de lo que quedó pendiente.

Un solo recurso —"mi conexión"— siempre en la misma dirección, sin id en la URL. El id de la
fila existe pero no es direccionable: no hay ninguna operación que tenga sentido sobre la
conexión de otro, así que exponerlo solo agregaría una forma de pedir la que no es.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from factumov.crud import balance360_connection as connection_crud
from factumov.crud import invoice as invoice_crud
from factumov.dependencies import (
    CurrentUserDep,
    SessionDep,
    enforce_rate_limit,
    get_current_user,
)
from factumov.exceptions import Balance360Error, SecretsNotConfiguredError
from factumov.schemas.balance360 import (
    Balance360ConnectionUpsert,
    Balance360RegisterPendingResult,
    Balance360Settings,
)
from factumov.services import balance360, secrets
from factumov.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/balance360",
    tags=["balance360"],
    dependencies=[Depends(get_current_user)],
)

# Conectar manda una contraseña de Balance360 a Balance360, así que este endpoint autenticado
# es también, de hecho, un intermediario para probar contraseñas ajenas. La defensa de verdad
# está del otro lado —cinco intentos por cuarto de hora y por mail, en `services/rate_limit.py`
# de Balance360— y este límite es lo que evita gastársela desde acá: diez por hora alcanzan de
# sobra para alguien que se equivocó al tipear y no para recorrer un diccionario. Por usuario y
# no por IP: el endpoint está autenticado, así que hay alguien a quien contarle los intentos.
_CONNECT_LIMITER = RateLimiter(limit=10, window_seconds=60 * 60)

# El registro en lote pega una vez por factura pendiente. Es la operación más cara del
# módulo y la que menos apuro tiene.
_REGISTER_LIMITER = RateLimiter(limit=10, window_seconds=60 * 60)

@router.get("", response_model=Balance360Settings)
def get_settings(db: SessionDep, user: CurrentUserDep) -> Balance360Settings:
    """Todo lo que la pantalla de ajustes necesita, en un request.

    `connection` en `null` es "no conectado", que es un estado normal y no un 404: la pantalla
    existe igual y lo que muestra es el formulario vacío. Un 404 obligaría a la SPA a tratar
    como error el caso más común.

    `unavailable_reason` dice qué le falta al **servidor** para que la integración se pueda
    usar. Va acá y no descubierto al apretar "conectar" para que el formulario pueda avisar
    antes de que el usuario escriba una contraseña que no va a llegar a ningún lado.
    """
    return Balance360Settings(
        base_url=balance360.base_url(),
        unavailable_reason=balance360.unavailable_reason(),
        connection=connection_crud.get_for_user(db, user.id),  # type: ignore[arg-type]
    )


@router.put("", response_model=Balance360Settings)
def connect(
    data: Balance360ConnectionUpsert, db: SessionDep, user: CurrentUserDep
) -> Balance360Settings:
    """Cambia las credenciales del usuario por un token y guarda **el token**.

    El usuario pone su mail y su contraseña de Balance360 y no ve ningún token: se lo pide
    FactuMov por él. Antes había que pegar uno emitido por ssh contra el servidor de la otra
    app, o sea que conectar la integración dependía de quien administra la VM y el secreto
    llegaba al usuario por algún chat.

    **La contraseña muere en esta función.** Entra en el body, se la lleva `fetch_token` y no
    queda en ninguna columna ni en ningún log; lo único que se persiste es el token que volvió,
    cifrado. Ese es el intercambio que justifica pedirla: una credencial que se revoca sola y
    que solo puede lo que puede la API, en lugar de una que abre la cuenta entera.

    El orden sigue siendo la decisión: primero se habla con Balance360 y solo si contesta se
    escribe. Guardar y verificar después dejaría al usuario con una conexión que la pantalla
    muestra como puesta y que falla en silencio en cada emisión.

    Es un PUT idempotente: volver a conectar es la operación más frecuente de esta pantalla, y
    del otro lado emitir un token nuevo revoca el anterior de esta misma integración.

    **La dirección no viaja en el body**: sale de `BALANCE360_BASE_URL`. Era un campo, y era
    una pregunta que el usuario no puede contestar; el efecto secundario que importa es que
    un error de conexión ya no puede ser culpa de lo que tipeó.
    """
    enforce_rate_limit(_CONNECT_LIMITER, str(user.id))

    reason = balance360.unavailable_reason()
    if reason is not None:
        # 503 y no 400: no hay nada malo en lo que mandó el usuario, le falta algo al servidor.
        # Y se chequea antes de salir a la red, así que una contraseña que no se va a poder
        # guardar tampoco llega a viajar.
        raise HTTPException(status_code=503, detail=reason)

    try:
        api_token = balance360.fetch_token(data.email, data.password)
    except Balance360Error as error:
        # 502 y no 400: lo que falló es la otra app, no el request —ni siquiera cuando la que
        # rebota es la contraseña, porque quien la rechaza es Balance360 y no FactuMov—. El
        # mensaje se propaga entero: es lo único que le dice al usuario si erró las
        # credenciales, si tiene que esperar porque se pasó de intentos, o si del otro lado no
        # contesta nadie.
        raise HTTPException(status_code=502, detail=str(error)) from error

    try:
        connection = connection_crud.upsert(
            db,
            user.id,
            encrypted_token=secrets.encrypt(api_token),
            token_hint=balance360.token_hint(api_token),
            auto_register=data.auto_register,
        )
    except SecretsNotConfiguredError as error:
        # Solo si la clave se fue del entorno entre el chequeo de arriba y esta línea. Queda
        # igual porque `secrets.encrypt` la puede levantar y un 500 acá sería mentir sobre de
        # quién es el problema.
        raise HTTPException(status_code=503, detail=str(error)) from error

    # El token lo acaba de emitir Balance360 para este usuario: la conexión nace verificada.
    # `upsert` limpia `verified_at` a propósito —el token cambió— y acá se vuelve a poner.
    connection_crud.mark_verified(db, connection)
    db.commit()
    db.refresh(connection)
    return Balance360Settings(
        base_url=balance360.base_url(),
        unavailable_reason=None,
        connection=connection,  # type: ignore[arg-type]
    )


@router.delete("", status_code=204)
def disconnect(db: SessionDep, user: CurrentUserDep) -> None:
    """Desconecta la cuenta. No toca las facturas ya registradas.

    204 tanto si había conexión como si no: el resultado que el usuario pidió —que no haya
    conexión— es el mismo en los dos casos, y un 404 sobre algo que ya no está solo complica
    a la pantalla.
    """
    connection = connection_crud.get_for_user(db, user.id)
    if connection is not None:
        connection_crud.delete(db, connection)
        db.commit()


@router.post("/register-pending", response_model=Balance360RegisterPendingResult)
def register_pending(db: SessionDep, user: CurrentUserDep) -> Balance360RegisterPendingResult:
    """Reintenta todas las facturas que quedaron sin copiar.

    Existe porque el modo normal de fallar de esta integración es en lote: Balance360 estuvo
    caído una tarde, o el token venció, y lo que quedó no es una factura sino todas las de ese
    rato. Reintentarlas de a una desde la pantalla de cada factura sería el mismo trabajo
    repetido N veces.

    **Sigue de largo cuando una falla.** Los errores no son homogéneos —a una le falta el CUIT
    del otro lado, la que sigue anda perfecto— así que cortar en la primera dejaría el resto
    sin intentar por un problema que no las toca. Cada una queda con su propio motivo escrito.

    Sincrónico y no en background, al revés que el disparo de la emisión: acá hay un usuario
    que apretó un botón y quiere ver el resultado. El límite de reintentos por hora es lo que
    acota cuánto puede tardar.
    """
    enforce_rate_limit(_REGISTER_LIMITER, str(user.id))

    if connection_crud.get_for_user(db, user.id) is None:
        raise HTTPException(
            status_code=409,
            detail="No hay ninguna cuenta de Balance360 conectada.",
        )

    pending = invoice_crud.get_pending_balance360(db, user.id)
    registered = 0
    for invoice in pending:
        if balance360.register(db, invoice) is not None:
            registered += 1

    return Balance360RegisterPendingResult(
        attempted=len(pending), registered=registered, failed=len(pending) - registered
    )
