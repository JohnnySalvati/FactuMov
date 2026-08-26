from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response

from factumov.crud import user as user_crud
from factumov.crud import user_session as user_session_crud
from factumov.dependencies import (
    SESSION_COOKIE_NAME,
    CurrentSessionDep,
    CurrentUserDep,
    SessionDep,
)
from factumov.models.user import User
from factumov.schemas.auth import LoginRequest, UserRead
from factumov.services.security import (
    generate_session_token,
    hash_session_token,
    verify_password,
)

# Vencimiento absoluto: se fija en el login y no se extiende por usar la sesión.
SESSION_LIFETIME = timedelta(days=7)

# Mismo cuerpo para email desconocido, contraseña incorrecta y usuario sin confirmar o dado
# de baja. "Confirmá tu email" sería un oráculo de enumeración.
_INVALID_CREDENTIALS_DETAIL = "Email o contraseña incorrectos"

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


@router.post("/login", response_model=UserRead)
def login(data: LoginRequest, response: Response, db: SessionDep) -> User:
    user = user_crud.get_by_email(db, data.email)
    # La verificación corre siempre, incluso sin usuario: `verify_password` acepta `None` y
    # compara contra un hash dummy para que el email desconocido cueste lo mismo que la
    # contraseña equivocada. Cortar antes acá reabriría el oráculo de timing.
    password_ok = verify_password(
        data.password.get_secret_value(), user.hashed_password if user else None
    )
    if user is None or not password_ok or not user.is_active or user.email_confirmed_at is None:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS_DETAIL)

    raw_token = generate_session_token()
    user_session_crud.create(
        db,
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
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
