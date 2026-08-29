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

# Guardar la conexión sale a la red para probar el token, así que se limita como todo lo que
# gasta una conexión saliente. Por usuario y no por IP: el endpoint está autenticado.
_CONNECT_LIMITER = RateLimiter(limit=20, window_seconds=60 * 60)

# El registro en lote pega una vez por factura pendiente. Es la operación más cara del
# módulo y la que menos apuro tiene.
_REGISTER_LIMITER = RateLimiter(limit=10, window_seconds=60 * 60)

_NOT_AVAILABLE_DETAIL = (
    "Este servidor no tiene configurada la integración con Balance360. "
    "Falta la clave de cifrado de secretos."
)


@router.get("", response_model=Balance360Settings)
def get_settings(db: SessionDep, user: CurrentUserDep) -> Balance360Settings:
    """Todo lo que la pantalla de ajustes necesita, en un request.

    `connection` en `null` es "no conectado", que es un estado normal y no un 404: la pantalla
    existe igual y lo que muestra es el formulario vacío. Un 404 obligaría a la SPA a tratar
    como error el caso más común.

    `available` dice si el **servidor** puede guardar un token. Va acá y no descubierto al
    apretar "guardar" para que el formulario pueda avisar antes de que el usuario pegue una
    credencial que no se va a poder guardar.
    """
    return Balance360Settings(
        available=secrets.is_configured(),
        connection=connection_crud.get_for_user(db, user.id),  # type: ignore[arg-type]
    )


@router.put("", response_model=Balance360Settings)
def connect(
    data: Balance360ConnectionUpsert, db: SessionDep, user: CurrentUserDep
) -> Balance360Settings:
    """Guarda la conexión, **después** de probar que el token anda.

    El orden es la decisión: primero se prueba contra Balance360 y solo si contesta se
    escribe. Guardar y verificar después dejaría al usuario con una conexión que la pantalla
    muestra como puesta y que falla en silencio en cada emisión — y el momento de enterarse de
    que pegó mal el token es mientras lo tiene en el portapapeles.

    Es un PUT idempotente: reemplazar el token es la operación más frecuente de esta pantalla,
    porque es lo que hay que hacer cuando se lo revoca del otro lado.
    """
    enforce_rate_limit(_CONNECT_LIMITER, str(user.id))

    if not secrets.is_configured():
        raise HTTPException(status_code=503, detail=_NOT_AVAILABLE_DETAIL)

    try:
        balance360.check_token(data.base_url, data.api_token)
    except Balance360Error as error:
        # 502 y no 400: lo que falló es la otra app, no el request. El mensaje sí se propaga
        # entero —es lo único que le dice al usuario si erró la dirección o el token—.
        raise HTTPException(status_code=502, detail=str(error)) from error

    try:
        connection = connection_crud.upsert(
            db,
            user.id,
            base_url=data.base_url,
            encrypted_token=secrets.encrypt(data.api_token),
            token_hint=balance360.token_hint(data.api_token),
            auto_register=data.auto_register,
        )
    except SecretsNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=_NOT_AVAILABLE_DETAIL) from error

    # El token acaba de contestar bien: la conexión nace verificada. `upsert` limpia
    # `verified_at` a propósito —el token pudo haber cambiado— y acá se vuelve a poner con el
    # dato recién comprobado.
    connection_crud.mark_verified(db, connection)
    db.commit()
    db.refresh(connection)
    return Balance360Settings(available=True, connection=connection)  # type: ignore[arg-type]


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
