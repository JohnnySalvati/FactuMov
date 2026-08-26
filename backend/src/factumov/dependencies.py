"""Dependencias compartidas por los routers.

`SessionDep` estaba copiada en los cuatro routers; acá queda una sola vez.
`get_current_user` vive en este módulo y no en `routers/auth.py` para que
`routers/customer.py` no termine importando de un router hermano sin ninguna razón
estructural.
"""

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from factumov.crud import user_session as user_session_crud
from factumov.database import get_db
from factumov.models.user import User
from factumov.models.user_session import UserSession
from factumov.services.rate_limit import RateLimiter
from factumov.services.security import hash_opaque_token

SESSION_COOKIE_NAME = "factumov_session"

# Un solo mensaje para las cinco causas posibles (sin cookie, token desconocido, vencido,
# revocado, usuario dado de baja o sin confirmar). Distinguirlas en la respuesta le diría a
# un atacante qué parte de su intento estuvo cerca de funcionar.
_UNAUTHENTICATED_DETAIL = "No autenticado"

SessionDep = Annotated[Session, Depends(get_db)]


def get_current_session(
    db: SessionDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> UserSession:
    """Resuelve la cookie de sesión a la fila viva de `user_sessions`.

    Devuelve la sesión y no el usuario porque el logout necesita la fila para revocarla.
    `get_current_user` se apoya en esta.
    """
    if session_token is None:
        raise HTTPException(status_code=401, detail=_UNAUTHENTICATED_DETAIL)
    token_hash = hash_opaque_token(session_token)
    user_session = user_session_crud.get_active_by_token_hash(db, token_hash)
    if user_session is None:
        raise HTTPException(status_code=401, detail=_UNAUTHENTICATED_DETAIL)
    return user_session


CurrentSessionDep = Annotated[UserSession, Depends(get_current_session)]


def get_current_user(user_session: CurrentSessionDep) -> User:
    """El usuario dueño de la sesión, revalidando su estado en cada request.

    `is_active` y `email_confirmed_at` se vuelven a chequear acá y no solo en el login: la
    sesión vive días, y dar de baja a un usuario tiene que cortarle el acceso en el request
    siguiente, no cuando le venza el token. El `joinedload` del CRUD ya trajo la fila, así
    que no cuesta una query extra.
    """
    user = user_session.user
    if not user.is_active or user.email_confirmed_at is None:
        raise HTTPException(status_code=401, detail=_UNAUTHENTICATED_DETAIL)
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


# --- Rate limiting --------------------------------------------------------------------
#
# Estas dos vivían en `routers/auth.py` mientras el único que limitaba algo era auth. Con la
# consulta al padrón y la verificación de delegación —que salen a ARCA y gastan la cuota del
# certificado, que es una sola para todos los usuarios— pasan a hacer falta en otro router, y
# la alternativa era importarlas de un router hermano. Es el mismo motivo por el que
# `get_current_user` está en este módulo y no en `routers/auth.py`.

_RATE_LIMITED_DETAIL = "Demasiados intentos. Esperá un rato y probá de nuevo."


def client_key(request: Request) -> str:
    """La IP del cliente, tal como la ve la app.

    Se lee de `request.client` y no del header `X-Forwarded-For`. Detrás de un proxy es
    uvicorn —con `--proxy-headers` y `--forwarded-allow-ips`— el que reescribe
    `request.client` a partir de ese header, y solo si el que se conectó es un proxy de
    confianza. Leer el header acá saltearía esa decisión, y un header que cualquiera puede
    inventar convierte el limitador en un adorno: se manda uno distinto en cada request y no
    hay límite, o se manda el de otro y se lo deja afuera a él.
    """
    return request.client.host if request.client else "sin-ip"


def enforce_rate_limit(limiter: RateLimiter, key: str) -> None:
    retry_after = limiter.check(key)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail=_RATE_LIMITED_DETAIL,
            # Segundos enteros y redondeando para arriba: un `Retry-After: 0` invitaría a
            # reintentar de inmediato, que es justo lo que se está tratando de frenar.
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
