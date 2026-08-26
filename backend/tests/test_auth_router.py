"""Tests HTTP de `routers/auth.py` y de la dependencia `get_current_user`.

Casi todos usan `anonymous_client`: el fixture `client` ya viene autenticado, que es
justamente lo que la mayoría de estos tests necesita *no* tener.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from factumov.dependencies import SESSION_COOKIE_NAME
from factumov.models.user_session import UserSession
from factumov.routers.auth import SESSION_LIFETIME
from tests.factories import PASSWORD, make_user, make_user_session


def login(anonymous_client, email, password=PASSWORD):
    return anonymous_client.post("/auth/login", json={"email": email, "password": password})


def sessions_of(db, user):
    return db.execute(select(UserSession).where(UserSession.user_id == user.id)).scalars().all()


def confirmed_user(db, **kwargs):
    kwargs.setdefault("email_confirmed_at", datetime.now(UTC))
    return make_user(db, **kwargs)


# --- login ------------------------------------------------------------------------------


def test_login_returns_the_user(anonymous_client, db):
    user = confirmed_user(db, email="ana@cucu.com")

    response = login(anonymous_client, "ana@cucu.com")

    assert response.status_code == 200
    assert response.json() == {"id": str(user.id), "email": "ana@cucu.com"}


def test_login_creates_a_session(anonymous_client, db):
    user = confirmed_user(db, email="ana@cucu.com")

    login(anonymous_client, "ana@cucu.com")

    sessions = sessions_of(db, user)
    assert len(sessions) == 1
    assert sessions[0].revoked_at is None
    expected = datetime.now(UTC) + SESSION_LIFETIME
    assert abs(sessions[0].expires_at - expected) < timedelta(minutes=1)


def test_login_sets_a_hardened_cookie(anonymous_client, db):
    confirmed_user(db, email="ana@cucu.com")

    response = login(anonymous_client, "ana@cucu.com")

    raw_cookie = response.headers["set-cookie"]
    assert raw_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in raw_cookie
    assert "Secure" in raw_cookie
    assert "SameSite=lax" in raw_cookie


def test_login_stores_the_token_hashed(anonymous_client, db):
    """La cookie lleva el token en claro; la fila guarda solo su SHA-256."""
    user = confirmed_user(db, email="ana@cucu.com")

    response = login(anonymous_client, "ana@cucu.com")

    raw_token = response.cookies[SESSION_COOKIE_NAME]
    (session,) = sessions_of(db, user)
    assert session.token_hash != raw_token
    assert len(session.token_hash) == 64


def test_login_normalizes_the_email(anonymous_client, db):
    """El `field_validator` del schema baja a minúsculas antes de buscar la fila."""
    confirmed_user(db, email="ana@cucu.com")

    assert login(anonymous_client, "ANA@cucu.com").status_code == 200


def test_login_lets_the_session_be_used(anonymous_client, db):
    confirmed_user(db, email="ana@cucu.com")

    login(anonymous_client, "ana@cucu.com")

    assert anonymous_client.get("/auth/me").status_code == 200


def _unknown_email(db):
    return None


def _wrong_password(db):
    return confirmed_user(db, email="ana@cucu.com")


def _unconfirmed(db):
    return make_user(db, email="ana@cucu.com", email_confirmed_at=None)


def _inactive(db):
    return confirmed_user(db, email="ana@cucu.com", is_active=False)


@pytest.mark.parametrize(
    "arrange, email, password",
    [
        pytest.param(_unknown_email, "nadie@cucu.com", PASSWORD, id="unknown_email"),
        pytest.param(_wrong_password, "ana@cucu.com", "otra", id="wrong_password"),
        pytest.param(_unconfirmed, "ana@cucu.com", PASSWORD, id="unconfirmed"),
        pytest.param(_inactive, "ana@cucu.com", PASSWORD, id="inactive"),
    ],
)
def test_login_rejects(anonymous_client, db, arrange, email, password):
    """Las cuatro causas dan exactamente la misma respuesta.

    Distinguirlas convertiría al login en un oráculo de enumeración: un "confirmá tu email"
    ya confirma que la dirección está registrada.
    """
    arrange(db)

    response = login(anonymous_client, email, password)

    assert response.status_code == 401
    assert response.json() == {"detail": "Email o contraseña incorrectos"}
    assert "set-cookie" not in response.headers


def test_login_rejection_creates_no_session(anonymous_client, db):
    user = confirmed_user(db, email="ana@cucu.com")

    login(anonymous_client, "ana@cucu.com", "otra")

    assert sessions_of(db, user) == []


# --- me / get_current_user ---------------------------------------------------------------


def test_me_with_a_valid_session(client, user):
    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {"id": str(user.id), "email": user.email}


def test_me_without_a_cookie(anonymous_client):
    response = anonymous_client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "No autenticado"}


def test_me_with_an_unknown_token(anonymous_client, db):
    confirmed_user(db)
    anonymous_client.cookies.set(SESSION_COOKIE_NAME, "un token que nadie emitio")

    assert anonymous_client.get("/auth/me").status_code == 401


def test_me_with_an_expired_session(anonymous_client, db):
    """El vencimiento se compara en SQL, así que basta con insertar la fila en el pasado."""
    user = confirmed_user(db)
    make_user_session(
        db,
        user_id=user.id,
        raw_token="expirado",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    anonymous_client.cookies.set(SESSION_COOKIE_NAME, "expirado")

    assert anonymous_client.get("/auth/me").status_code == 401


def test_me_with_a_revoked_session(anonymous_client, db):
    user = confirmed_user(db)
    make_user_session(
        db,
        user_id=user.id,
        raw_token="revocado",
        revoked_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    anonymous_client.cookies.set(SESSION_COOKIE_NAME, "revocado")

    assert anonymous_client.get("/auth/me").status_code == 401


@pytest.mark.parametrize(
    "user_kwargs",
    [
        pytest.param({"is_active": False}, id="deactivated"),
        pytest.param({"email_confirmed_at": None}, id="unconfirmed"),
    ],
)
def test_me_rechecks_the_user_state(anonymous_client, db, user_kwargs):
    """La sesión sigue viva pero el usuario ya no puede usarla.

    Es el caso que justifica revalidar en `get_current_user` y no solo en el login: la
    sesión dura una semana, y una baja tiene que pegar en el request siguiente.
    """
    user = confirmed_user(db, **user_kwargs)
    make_user_session(db, user_id=user.id, raw_token="vivo")
    anonymous_client.cookies.set(SESSION_COOKIE_NAME, "vivo")

    assert anonymous_client.get("/auth/me").status_code == 401


# --- logout ------------------------------------------------------------------------------


def test_logout_revokes_the_session(client, db, user):
    response = client.post("/auth/logout")

    assert response.status_code == 204
    (session,) = sessions_of(db, user)
    assert session.revoked_at is not None


def test_logout_clears_the_cookie(client):
    """Se mira el `Set-Cookie`, no el cookie jar del cliente.

    `delete_cookie` reescribe la cookie vacía y vencida, que es lo que el navegador lee.
    El jar del TestClient no sirve de oráculo acá: el fixture inyecta la cookie sin dominio
    y el borrado llega con el dominio del request, así que quedan dos entradas distintas y
    `.get` sigue devolviendo la vieja. Lo que importa de verdad — que la sesión ya no
    sirva — lo cubre el test de abajo.
    """
    response = client.post("/auth/logout")

    raw_cookie = response.headers["set-cookie"]
    assert raw_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "Max-Age=0" in raw_cookie


def test_logout_closes_the_session_for_good(client):
    client.post("/auth/logout")

    assert client.get("/auth/me").status_code == 401


def test_logout_without_a_session(anonymous_client):
    assert anonymous_client.post("/auth/logout").status_code == 401


# --- el resto de la API queda detrás de la autenticación ---------------------------------


@pytest.mark.parametrize("path", ["/customers", "/fiscal-identities", "/invoice-templates"])
def test_routers_require_authentication(anonymous_client, path):
    assert anonymous_client.get(path).status_code == 401


def test_health_stays_public(anonymous_client):
    """El health check lo consulta el orquestador, que no tiene sesión."""
    assert anonymous_client.get("/health/").status_code == 200
