"""Tests del rate limiting de los endpoints de auth.

Los límites se leen de los propios limitadores en vez de repetir los números acá: si mañana
el registro pasa de 5 a 10 por hora, estos tests tienen que seguir probando el límite, no
fallar por saberse uno viejo de memoria.

El `reset_rate_limiters` de `conftest.py` es autouse, así que cada test arranca con los
contadores en cero y el orden de colección no influye.
"""

from datetime import UTC, datetime

import pytest

from factumov.dependencies import _RATE_LIMITED_DETAIL
from factumov.routers.auth import (
    _EMAIL_LIMITER,
    _LOGIN_LIMITER,
    _REGISTER_IP_LIMITER,
    _RESEND_IP_LIMITER,
)
from tests.factories import PASSWORD, make_user

NEW_PASSWORD = "unaContraseñaLarga"


def register(anonymous_client, email):
    return anonymous_client.post("/auth/register", json={"email": email, "password": NEW_PASSWORD})


def test_register_stops_a_flood_from_one_ip(anonymous_client):
    """Direcciones distintas, misma IP: lo frena el límite por IP y no el de dirección."""
    for n in range(_REGISTER_IP_LIMITER.limit):
        assert register(anonymous_client, f"ana{n}@cucu.com").status_code == 202

    response = register(anonymous_client, "ana999@cucu.com")

    assert response.status_code == 429
    assert response.json() == {"detail": _RATE_LIMITED_DETAIL}


def test_register_stops_a_flood_against_one_address(anonymous_client):
    """El límite por dirección corta antes que el de IP, que es el punto de tenerlo."""
    assert _EMAIL_LIMITER.limit < _REGISTER_IP_LIMITER.limit

    for _ in range(_EMAIL_LIMITER.limit):
        assert register(anonymous_client, "ana@cucu.com").status_code == 202

    assert register(anonymous_client, "ana@cucu.com").status_code == 429


def test_the_429_says_when_to_come_back(anonymous_client):
    for n in range(_REGISTER_IP_LIMITER.limit):
        register(anonymous_client, f"ana{n}@cucu.com")

    response = register(anonymous_client, "ana999@cucu.com")

    assert int(response.headers["retry-after"]) > 0


def test_the_limit_does_not_depend_on_the_address_existing(anonymous_client, db, sent_emails):
    """Si el contador solo avanzara para direcciones reales, el 429 sería el oráculo de
    enumeración que el 202 evita: llegaría antes para las registradas."""
    make_user(db, email="conocida@cucu.com", email_confirmed_at=datetime.now(UTC))

    for _ in range(_EMAIL_LIMITER.limit):
        register(anonymous_client, "conocida@cucu.com")
    conocida = register(anonymous_client, "conocida@cucu.com")

    _EMAIL_LIMITER.reset()
    for _ in range(_EMAIL_LIMITER.limit):
        register(anonymous_client, "nueva@cucu.com")
    nueva = register(anonymous_client, "nueva@cucu.com")

    assert conocida.status_code == nueva.status_code == 429
    assert conocida.json() == nueva.json()


def test_register_and_resend_share_the_budget_per_address(anonymous_client, db):
    """Los dos le mandan mail a la misma casilla, así que se cuentan juntos.

    Presupuestos separados dejarían que un atacante duplique el bombardeo alternando entre
    los dos endpoints, que es lo primero que se prueba.
    """
    make_user(db, email="ana@cucu.com", email_confirmed_at=None)
    for _ in range(_EMAIL_LIMITER.limit):
        anonymous_client.post("/auth/resend-confirmation", json={"email": "ana@cucu.com"})

    assert register(anonymous_client, "ana@cucu.com").status_code == 429


def test_resend_stops_a_flood_from_one_ip(anonymous_client, db):
    for n in range(_RESEND_IP_LIMITER.limit):
        make_user(db, email=f"ana{n}@cucu.com", email_confirmed_at=None)
        response = anonymous_client.post(
            "/auth/resend-confirmation", json={"email": f"ana{n}@cucu.com"}
        )
        assert response.status_code == 202

    response = anonymous_client.post("/auth/resend-confirmation", json={"email": "ana999@cucu.com"})

    assert response.status_code == 429


def test_login_stops_credential_stuffing(anonymous_client, db):
    make_user(db, email="ana@cucu.com", email_confirmed_at=datetime.now(UTC))

    for _ in range(_LOGIN_LIMITER.limit):
        response = anonymous_client.post(
            "/auth/login", json={"email": "ana@cucu.com", "password": "incorrecta"}
        )
        assert response.status_code == 401

    response = anonymous_client.post(
        "/auth/login", json={"email": "ana@cucu.com", "password": PASSWORD}
    )

    assert response.status_code == 429


@pytest.mark.parametrize(
    "limiter", [_LOGIN_LIMITER, _REGISTER_IP_LIMITER, _RESEND_IP_LIMITER, _EMAIL_LIMITER]
)
def test_the_limits_are_generous_enough_for_a_person(limiter):
    """Guardia contra apretar los números hasta que estorben.

    Nadie se registra cinco veces por hora ni pide tres reenvíos seguidos; el que sí falla
    varias veces seguidas es el que se equivoca de contraseña, y por eso el login es el más
    holgado. Si alguien baja alguno a 1 o 2, esto lo dice antes que un usuario.
    """
    assert limiter.limit >= 3
    assert limiter.window_seconds <= 60 * 60
