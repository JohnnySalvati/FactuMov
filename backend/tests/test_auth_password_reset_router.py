"""Tests HTTP del "olvidé mi contraseña": `/auth/forgot-password` y `/auth/reset-password`.

Todos usan `anonymous_client`: el que no puede entrar es, por definición, alguien sin sesión.

El token se saca del link del mail y no de la tabla, mismo criterio que los tests del
registro. Leer el `token_hash` probaría que el CRUD guardó algo; sacarlo del cuerpo del mail
y postearlo prueba que el link que llega a la casilla cambia la contraseña, que es lo que
puede romperse en el medio — y de hecho se rompió, con `APP_BASE_URL` en http.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from factumov.dependencies import SESSION_COOKIE_NAME
from factumov.models.password_reset import PasswordReset
from factumov.routers.auth import (
    _FORGOT_ACCEPTED_DETAIL,
    PASSWORD_RESET_LIFETIME,
)
from factumov.services import email as email_service
from factumov.services.email import EmailDeliveryError
from tests.conftest import FALLBACK_DELEGATE_TAX_ID
from tests.factories import (
    PASSWORD,
    make_password_reset,
    make_user,
    make_user_session,
)

NEW_PASSWORD = "unaContraseñaNueva"


def forgot(anonymous_client, email):
    return anonymous_client.post("/auth/forgot-password", json={"email": email})


def reset(anonymous_client, token, password=NEW_PASSWORD):
    return anonymous_client.post(
        "/auth/reset-password", json={"token": token, "password": password}
    )


def log_in(anonymous_client, email, password):
    return anonymous_client.post("/auth/login", json={"email": email, "password": password})


def token_from(sent_email):
    """El token tal como lo recibe el usuario: extraído del link del cuerpo del mail."""
    link = next(word for word in sent_email.body.split() if word.startswith("https://app.test"))
    return parse_qs(urlparse(link).query)["token"][0]


def resets_of(db, user):
    return db.execute(select(PasswordReset).where(PasswordReset.user_id == user.id)).scalars().all()


@pytest.fixture
def confirmed_user(db):
    """Una cuenta normal, que sabe su contraseña vieja (`PASSWORD`) y quiere otra."""
    return make_user(db, email="ana@cucu.com", email_confirmed_at=datetime.now(UTC))


# --- pedir el link -------------------------------------------------------------------------


def test_forgot_mails_a_reset_link(anonymous_client, confirmed_user, sent_emails):
    response = forgot(anonymous_client, "ana@cucu.com")

    assert response.status_code == 202
    assert response.json() == {"detail": _FORGOT_ACCEPTED_DETAIL}
    assert len(sent_emails) == 1
    assert sent_emails[0].to == "ana@cucu.com"
    assert "https://app.test/restablecer-password?token=" in sent_emails[0].body


def test_forgot_issues_a_token_with_the_configured_lifetime(anonymous_client, confirmed_user, db):
    forgot(anonymous_client, "ana@cucu.com")

    resets = resets_of(db, confirmed_user)
    assert len(resets) == 1
    expected = datetime.now(UTC) + PASSWORD_RESET_LIFETIME
    assert abs(resets[0].expires_at - expected) < timedelta(minutes=1)


def test_forgot_normalizes_the_email(anonymous_client, confirmed_user, db):
    """Sin esto, `Ana@Cucu.com` no encuentra la cuenta y el usuario recibe el aviso equivocado."""
    forgot(anonymous_client, "Ana@Cucu.com")

    assert len(resets_of(db, confirmed_user)) == 1


def test_forgot_works_on_an_unconfirmed_account(anonymous_client, db, sent_emails):
    """El motivo por el que existe esta unidad.

    Quien se equivocó de contraseña al registrarse no tenía salida: el segundo registro no
    pisa la contraseña —a propósito— así que la cuenta quedaba con una contraseña que nadie
    sabe. Exigir estar confirmado acá dejaría ese callejón sin salida abierto.
    """
    user = make_user(db, email="ana@cucu.com", email_confirmed_at=None)

    forgot(anonymous_client, "ana@cucu.com")

    assert len(resets_of(db, user)) == 1
    assert "restablecer-password?token=" in sent_emails[0].body


# --- las direcciones que no reciben link ---------------------------------------------------
#
# El punto de estos tres es que la respuesta HTTP no cambia. Si alguno empieza a fallar
# porque el status o el body difieren, lo que se rompió es la propiedad anti-enumeración.


@pytest.mark.parametrize("case", ["desconocida", "de un usuario de baja"])
def test_forgot_answers_the_same_without_issuing_a_token(anonymous_client, db, case):
    if case == "de un usuario de baja":
        make_user(db, email="ana@cucu.com", is_active=False, email_confirmed_at=datetime.now(UTC))

    response = forgot(anonymous_client, "ana@cucu.com")

    assert response.status_code == 202
    assert response.json() == {"detail": _FORGOT_ACCEPTED_DETAIL}
    assert db.execute(select(PasswordReset)).scalars().all() == []


def test_forgot_over_an_unknown_address_still_mails_something(anonymous_client, sent_emails):
    """Las dos ramas mandan un mail, y eso es estructural.

    El endpoint contesta 503 cuando el mail no se puede entregar. Si esta rama no mandara
    nada nunca podría fallar, y entonces un 503 pasaría a significar "esa dirección existe".
    """
    forgot(anonymous_client, "nadie@cucu.com")

    assert len(sent_emails) == 1
    assert sent_emails[0].to == "nadie@cucu.com"
    assert "no pudimos" in sent_emails[0].subject.lower()


def test_the_mail_to_an_unknown_address_does_not_claim_it_does_not_exist(
    anonymous_client, db, sent_emails
):
    """Una cuenta dada de baja cae en la misma rama, y su dueño no merece que le mintamos."""
    make_user(db, email="ana@cucu.com", is_active=False, email_confirmed_at=datetime.now(UTC))

    forgot(anonymous_client, "ana@cucu.com")

    assert "no existe" not in sent_emails[0].body.lower()


# --- usar el link --------------------------------------------------------------------------


def test_reset_changes_the_password(anonymous_client, confirmed_user, sent_emails):
    """De punta a punta: el link del mail deja entrar con la contraseña nueva."""
    forgot(anonymous_client, "ana@cucu.com")

    response = reset(anonymous_client, token_from(sent_emails[0]))

    assert response.status_code == 200
    assert log_in(anonymous_client, "ana@cucu.com", NEW_PASSWORD).status_code == 200


def test_reset_retires_the_old_password(anonymous_client, confirmed_user, sent_emails):
    forgot(anonymous_client, "ana@cucu.com")
    reset(anonymous_client, token_from(sent_emails[0]))

    assert log_in(anonymous_client, "ana@cucu.com", PASSWORD).status_code == 401


def test_reset_does_not_open_a_session(anonymous_client, confirmed_user, sent_emails):
    """El token vivió en una casilla de mail: no se convierte en cookie de sesión."""
    forgot(anonymous_client, "ana@cucu.com")

    response = reset(anonymous_client, token_from(sent_emails[0]))

    assert SESSION_COOKIE_NAME not in response.cookies


def test_reset_warns_the_owner_that_the_password_changed(
    anonymous_client, confirmed_user, sent_emails
):
    """Es la única señal que le llega al dueño si el reset lo pidió otro."""
    forgot(anonymous_client, "ana@cucu.com")

    reset(anonymous_client, token_from(sent_emails[0]))

    assert len(sent_emails) == 2
    assert sent_emails[1].to == "ana@cucu.com"
    assert "contraseña" in sent_emails[1].subject.lower()


def test_reset_closes_every_open_session(anonymous_client, confirmed_user, db, sent_emails):
    """Quien resetea porque sospecha que le entraron tiene que quedarse solo adentro."""
    session = make_user_session(db, user_id=confirmed_user.id)
    forgot(anonymous_client, "ana@cucu.com")

    reset(anonymous_client, token_from(sent_emails[0]))

    db.refresh(session)
    assert session.revoked_at is not None


def test_a_used_token_cannot_be_used_again(anonymous_client, confirmed_user, sent_emails):
    forgot(anonymous_client, "ana@cucu.com")
    token = token_from(sent_emails[0])
    reset(anonymous_client, token)

    assert reset(anonymous_client, token, password="otraMasLarga").status_code == 400


def test_asking_twice_leaves_both_links_alive(anonymous_client, confirmed_user, sent_emails):
    """Pedirlo de nuevo no rompe el mail anterior, igual que en la confirmación.

    El usuario que no encuentra el primer mail pide otro, y castigarlo por buscar mal sería
    dejarle dos links muertos y ninguna explicación.
    """
    forgot(anonymous_client, "ana@cucu.com")
    forgot(anonymous_client, "ana@cucu.com")

    assert reset(anonymous_client, token_from(sent_emails[0])).status_code == 200


def test_using_one_link_kills_the_others(anonymous_client, confirmed_user, sent_emails):
    """La diferencia de fondo con la confirmación de email.

    Dos links de confirmación vivos son inofensivos: los dos hacen lo mismo y lo que hacen ya
    está hecho. Dos links de reset vivos son dos oportunidades de cambiar la contraseña, y la
    segunda le queda a quien pidió la primera — que es justamente de quien se está tratando
    de salir cuando el reset se pide por sospecha.
    """
    forgot(anonymous_client, "ana@cucu.com")
    forgot(anonymous_client, "ana@cucu.com")
    first, second = token_from(sent_emails[0]), token_from(sent_emails[1])

    reset(anonymous_client, second)

    assert reset(anonymous_client, first, password="terceraLarga").status_code == 400


@pytest.mark.parametrize(
    "case",
    ["desconocido", "vencido", "ya usado", "de un usuario dado de baja"],
    ids=lambda case: case.replace(" ", "_"),
)
def test_reset_rejects_a_token_that_does_not_serve(anonymous_client, db, case):
    """Las cuatro causas dan el mismo 400: el remedio de todas es pedir un link nuevo."""
    token = "el-token"
    if case == "desconocido":
        pass
    elif case == "vencido":
        make_password_reset(
            db, raw_token=token, expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
    elif case == "ya usado":
        make_password_reset(db, raw_token=token, used_at=datetime.now(UTC))
    else:
        user = make_user(db, is_active=False, email_confirmed_at=datetime.now(UTC))
        make_password_reset(db, user_id=user.id, raw_token=token)

    response = reset(anonymous_client, token)

    assert response.status_code == 400


def test_reset_rejects_a_short_password(anonymous_client, confirmed_user, sent_emails):
    """Acá se **elige** una contraseña, así que la política del alta aplica igual."""
    forgot(anonymous_client, "ana@cucu.com")
    token = token_from(sent_emails[0])

    response = reset(anonymous_client, token, password="corta")

    assert response.status_code == 422
    # El 422 lo corta Pydantic antes del endpoint, así que el token sigue sirviendo.
    assert reset(anonymous_client, token).status_code == 200


# --- lo que el reset arregla para una cuenta sin confirmar ---------------------------------


def test_reset_confirms_the_address(anonymous_client, db, sent_emails):
    """Abrir este link prueba lo mismo que el de confirmación: que la casilla es de quien dice.

    Sin esto la salida sería falsa: el usuario cambia la contraseña y sigue sin poder entrar,
    con el mismo 401 de siempre y sin nada que le explique por qué.
    """
    make_user(db, email="ana@cucu.com", email_confirmed_at=None)
    forgot(anonymous_client, "ana@cucu.com")

    reset(anonymous_client, token_from(sent_emails[0]))

    assert log_in(anonymous_client, "ana@cucu.com", NEW_PASSWORD).status_code == 200


def test_reset_mails_the_delegation_instructions_when_it_confirms(
    anonymous_client, db, sent_emails
):
    """La confirmación es lo que dispara ese mail; si confirma acá, tiene que salir acá."""
    make_user(db, email="ana@cucu.com", email_confirmed_at=None)
    forgot(anonymous_client, "ana@cucu.com")

    reset(anonymous_client, token_from(sent_emails[0]))

    assert any(FALLBACK_DELEGATE_TAX_ID in sent.body for sent in sent_emails)


def test_reset_over_a_confirmed_account_does_not_repeat_the_delegation_mail(
    anonymous_client, confirmed_user, sent_emails
):
    forgot(anonymous_client, "ana@cucu.com")

    reset(anonymous_client, token_from(sent_emails[0]))

    assert not any(FALLBACK_DELEGATE_TAX_ID in sent.body for sent in sent_emails)


# --- cuando el mail no sale ----------------------------------------------------------------


def test_forgot_answers_503_when_the_mail_cannot_be_sent(
    anonymous_client, confirmed_user, broken_mail
):
    """Lo que el 202 alegre ocultaba: la respuesta ahora dice que el mail no salió."""
    response = forgot(anonymous_client, "ana@cucu.com")

    assert response.status_code == 503


def test_an_unknown_address_also_answers_503(anonymous_client, broken_mail):
    """Las dos ramas fallan igual, o el 503 sería el oráculo que el 202 evita."""
    assert forgot(anonymous_client, "nadie@cucu.com").status_code == 503


def test_register_answers_503_when_the_mail_cannot_be_sent(anonymous_client, broken_mail, db):
    """El bug del 2026-08-26 en un test: con el SMTP roto, el registro contestaba 202."""
    response = anonymous_client.post(
        "/auth/register", json={"email": "ana@cucu.com", "password": NEW_PASSWORD}
    )

    assert response.status_code == 503


def test_the_delegation_mail_cannot_break_the_confirmation(
    anonymous_client, db, sent_emails, monkeypatch
):
    """El mail que solo acompaña es best effort: la cuenta ya quedó confirmada.

    Fallar acá mandaría al usuario a reintentar con un token que ya se consumió, o sea a un
    400 sobre una cuenta que en realidad sí quedó confirmada. Es el otro lado de la moneda
    del 503: el rol del mail decide, no su importancia.
    """
    user = make_user(db, email="ana@cucu.com", email_confirmed_at=None)
    anonymous_client.post("/auth/resend-confirmation", json={"email": "ana@cucu.com"})
    token = token_from(sent_emails[0])

    def explode(to, subject, body, attachments=()):
        raise EmailDeliveryError("no salió")

    monkeypatch.setattr(email_service, "send_email", explode)
    response = anonymous_client.post("/auth/confirm", json={"token": token})

    assert response.status_code == 200
    db.refresh(user)
    assert user.email_confirmed_at is not None
