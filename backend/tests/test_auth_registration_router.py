"""Tests HTTP del registro, la confirmación y el reenvío.

Todos usan `anonymous_client`: son los tres endpoints que por definición se usan sin sesión.

Los mails no se leen de la base sino de `sent_emails`, el fixture autouse que intercepta el
transporte. El token se saca del link del mail y se postea a `/auth/confirm`, que es
exactamente lo que hace el usuario. Leer el `token_hash` de la tabla probaría que el CRUD
guardó algo; sacarlo del mail prueba que el link que llega a la casilla abre la cuenta, que
es lo que realmente puede romperse en el medio.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from factumov.dependencies import SESSION_COOKIE_NAME
from factumov.models.email_confirmation import EmailConfirmation
from factumov.models.user import User
from factumov.routers.auth import (
    _REGISTRATION_ACCEPTED_DETAIL,
    _RESEND_ACCEPTED_DETAIL,
    CONFIRMATION_LIFETIME,
)
from factumov.services import email as email_service
from tests.factories import PASSWORD, make_email_confirmation, make_user

NEW_PASSWORD = "unaContraseñaLarga"


def register(anonymous_client, email, password=NEW_PASSWORD):
    return anonymous_client.post("/auth/register", json={"email": email, "password": password})


def resend(anonymous_client, email):
    return anonymous_client.post("/auth/resend-confirmation", json={"email": email})


def confirm(anonymous_client, token):
    return anonymous_client.post("/auth/confirm", json={"token": token})


def token_from(sent_email):
    """El token tal como lo recibe el usuario: extraído del link del cuerpo del mail."""
    link = next(word for word in sent_email.body.split() if word.startswith("https://app.test"))
    return parse_qs(urlparse(link).query)["token"][0]


def confirmations_of(db, user):
    return (
        db.execute(select(EmailConfirmation).where(EmailConfirmation.user_id == user.id))
        .scalars()
        .all()
    )


def users_with(db, email):
    return db.execute(select(User).where(User.email == email)).scalars().all()


# --- registro ---------------------------------------------------------------------------


def test_register_accepts_a_new_address(anonymous_client):
    response = register(anonymous_client, "ana@cucu.com")

    assert response.status_code == 202
    assert response.json() == {"detail": _REGISTRATION_ACCEPTED_DETAIL}


def test_register_creates_an_unconfirmed_user(anonymous_client, db):
    register(anonymous_client, "ana@cucu.com")

    users = users_with(db, "ana@cucu.com")
    assert len(users) == 1
    assert users[0].email_confirmed_at is None


def test_register_issues_a_token_with_the_configured_lifetime(anonymous_client, db):
    register(anonymous_client, "ana@cucu.com")

    confirmations = confirmations_of(db, users_with(db, "ana@cucu.com")[0])
    assert len(confirmations) == 1
    expected = datetime.now(UTC) + CONFIRMATION_LIFETIME
    assert abs(confirmations[0].expires_at - expected) < timedelta(minutes=1)


def test_register_mails_a_confirmation_link(anonymous_client, sent_emails):
    register(anonymous_client, "ana@cucu.com")

    assert len(sent_emails) == 1
    assert sent_emails[0].to == "ana@cucu.com"
    assert "https://app.test/confirmar-email?token=" in sent_emails[0].body


def test_register_normalizes_the_email(anonymous_client, db):
    """Sin esto `Ana@Cucu.com` y `ana@cucu.com` son dos cuentas y el unique no lo impide."""
    register(anonymous_client, "Ana@Cucu.com")

    assert len(users_with(db, "ana@cucu.com")) == 1


def test_register_rejects_a_short_password(anonymous_client, db):
    response = register(anonymous_client, "ana@cucu.com", password="corta")

    assert response.status_code == 422
    assert users_with(db, "ana@cucu.com") == []


def test_a_registered_user_cannot_log_in_before_confirming(anonymous_client):
    register(anonymous_client, "ana@cucu.com")

    response = anonymous_client.post(
        "/auth/login", json={"email": "ana@cucu.com", "password": NEW_PASSWORD}
    )

    assert response.status_code == 401


# --- registro sobre una dirección que ya existe -------------------------------------------
#
# El punto de estos tres es que la respuesta HTTP no cambia. Si alguno empieza a fallar
# porque el status o el body difieren, lo que se rompió es la propiedad anti-enumeración,
# no el caso particular que el test nombra.


def test_register_answers_the_same_for_a_confirmed_address(anonymous_client, db):
    make_user(db, email="ana@cucu.com", email_confirmed_at=datetime.now(UTC))

    response = register(anonymous_client, "ana@cucu.com")

    assert response.status_code == 202
    assert response.json() == {"detail": _REGISTRATION_ACCEPTED_DETAIL}


def test_register_over_a_confirmed_address_changes_nothing(anonymous_client, db):
    user = make_user(db, email="ana@cucu.com", email_confirmed_at=datetime.now(UTC))
    original_hash = user.hashed_password

    register(anonymous_client, "ana@cucu.com")

    assert len(users_with(db, "ana@cucu.com")) == 1
    db.refresh(user)
    assert user.hashed_password == original_hash
    assert confirmations_of(db, user) == []


def test_register_over_a_confirmed_address_warns_the_owner(anonymous_client, db, sent_emails):
    """Lo único que puede contar qué pasó es la casilla del dueño de la dirección."""
    make_user(db, email="ana@cucu.com", email_confirmed_at=datetime.now(UTC))

    register(anonymous_client, "ana@cucu.com")

    assert len(sent_emails) == 1
    assert sent_emails[0].to == "ana@cucu.com"
    assert "Ya tenés una cuenta" in sent_emails[0].subject


def test_register_over_an_unconfirmed_address_resends_the_confirmation(
    anonymous_client, db, sent_emails
):
    user = make_user(db, email="ana@cucu.com", email_confirmed_at=None)

    register(anonymous_client, "ana@cucu.com")

    assert len(confirmations_of(db, user)) == 1
    assert "confirmar-email?token=" in sent_emails[0].body


def test_register_over_an_unconfirmed_address_keeps_the_old_password(anonymous_client, db):
    """Pisarla sería tomar la cuenta: el dueño real confirma y queda con la del atacante."""
    user = make_user(db, email="ana@cucu.com", email_confirmed_at=None)
    original_hash = user.hashed_password

    register(anonymous_client, "ana@cucu.com", password="otraContraseñaLarga")

    db.refresh(user)
    assert user.hashed_password == original_hash


# --- confirmación -------------------------------------------------------------------------


def test_confirm_returns_the_user(anonymous_client, db, sent_emails):
    register(anonymous_client, "ana@cucu.com")

    response = confirm(anonymous_client, token_from(sent_emails[0]))

    assert response.status_code == 200
    assert response.json()["email"] == "ana@cucu.com"


def test_confirm_marks_the_address_as_confirmed(anonymous_client, db, sent_emails):
    register(anonymous_client, "ana@cucu.com")

    confirm(anonymous_client, token_from(sent_emails[0]))

    db.expire_all()
    assert users_with(db, "ana@cucu.com")[0].email_confirmed_at is not None


def test_confirm_lets_the_user_log_in(anonymous_client, sent_emails):
    """La prueba de que todo el circuito cierra, de punta a punta."""
    register(anonymous_client, "ana@cucu.com")
    confirm(anonymous_client, token_from(sent_emails[0]))

    response = anonymous_client.post(
        "/auth/login", json={"email": "ana@cucu.com", "password": NEW_PASSWORD}
    )

    assert response.status_code == 200


def test_confirm_does_not_open_a_session(anonymous_client, sent_emails):
    """El token vivió un día en una casilla: no se convierte en cookie de sesión."""
    register(anonymous_client, "ana@cucu.com")

    response = confirm(anonymous_client, token_from(sent_emails[0]))

    assert SESSION_COOKIE_NAME not in response.cookies


def test_confirm_mails_the_delegation_instructions(anonymous_client, sent_emails):
    register(anonymous_client, "ana@cucu.com")

    confirm(anonymous_client, token_from(sent_emails[0]))

    assert len(sent_emails) == 2
    assert "autorizar a FactuMov" in sent_emails[1].subject
    assert "20-11111111-2" in sent_emails[1].body


def test_confirming_twice_does_not_repeat_the_delegation_mail(anonymous_client, sent_emails):
    """Dos tokens vivos son legales; el segundo no tiene que repetir el mail de ARCA."""
    register(anonymous_client, "ana@cucu.com")
    resend(anonymous_client, "ana@cucu.com")
    first, second = token_from(sent_emails[0]), token_from(sent_emails[1])

    confirm(anonymous_client, first)
    mails_after_first = len(sent_emails)
    response = confirm(anonymous_client, second)

    assert response.status_code == 200
    assert len(sent_emails) == mails_after_first


@pytest.mark.parametrize(
    "case",
    ["desconocido", "vencido", "ya usado", "de un usuario dado de baja"],
    ids=lambda case: case.replace(" ", "_"),
)
def test_confirm_rejects_a_token_that_does_not_serve(anonymous_client, db, case):
    """Las cuatro causas dan el mismo 400: el remedio de todas es pedir un link nuevo."""
    token = "el-token"
    if case == "desconocido":
        pass
    elif case == "vencido":
        make_email_confirmation(
            db, raw_token=token, expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
    elif case == "ya usado":
        make_email_confirmation(db, raw_token=token, confirmed_at=datetime.now(UTC))
    else:
        user = make_user(db, is_active=False, email_confirmed_at=None)
        make_email_confirmation(db, user_id=user.id, raw_token=token)

    response = confirm(anonymous_client, token)

    assert response.status_code == 400


def test_a_used_token_cannot_be_used_again(anonymous_client, sent_emails):
    register(anonymous_client, "ana@cucu.com")
    token = token_from(sent_emails[0])
    confirm(anonymous_client, token)

    assert confirm(anonymous_client, token).status_code == 400


# --- reenvío ------------------------------------------------------------------------------


def test_resend_issues_a_new_token_for_an_unconfirmed_address(anonymous_client, db, sent_emails):
    user = make_user(db, email="ana@cucu.com", email_confirmed_at=None)

    response = resend(anonymous_client, "ana@cucu.com")

    assert response.status_code == 202
    assert response.json() == {"detail": _RESEND_ACCEPTED_DETAIL}
    assert len(confirmations_of(db, user)) == 1
    assert len(sent_emails) == 1


def test_resend_does_not_invalidate_the_previous_token(anonymous_client, db, sent_emails):
    """El usuario puede tener dos mails abiertos; romperle el viejo no protege nada."""
    register(anonymous_client, "ana@cucu.com")
    resend(anonymous_client, "ana@cucu.com")

    assert confirm(anonymous_client, token_from(sent_emails[0])).status_code == 200


@pytest.mark.parametrize("case", ["desconocida", "ya confirmada", "de un usuario de baja"])
def test_resend_answers_the_same_and_mails_nothing(anonymous_client, db, sent_emails, case):
    if case == "ya confirmada":
        make_user(db, email="ana@cucu.com", email_confirmed_at=datetime.now(UTC))
    elif case == "de un usuario de baja":
        make_user(db, email="ana@cucu.com", is_active=False, email_confirmed_at=None)

    response = resend(anonymous_client, "ana@cucu.com")

    assert response.status_code == 202
    assert response.json() == {"detail": _RESEND_ACCEPTED_DETAIL}
    assert sent_emails == []


def test_the_three_endpoints_need_no_session(anonymous_client, db):
    """Van en el router de auth, que no lleva `Depends(get_current_user)`."""
    make_user(db, email="ana@cucu.com", email_confirmed_at=None)

    assert register(anonymous_client, "otra@cucu.com").status_code == 202
    assert resend(anonymous_client, "ana@cucu.com").status_code == 202
    assert confirm(anonymous_client, "cualquiera").status_code == 400


def test_the_password_in_a_login_still_works_for_factory_users(anonymous_client, db):
    """Guardia del piso de largo: `PASSWORD` de las factories tiene que seguir pasando."""
    make_user(db, email="ana@cucu.com", email_confirmed_at=datetime.now(UTC))

    response = anonymous_client.post(
        "/auth/login", json={"email": "ana@cucu.com", "password": PASSWORD}
    )

    assert response.status_code == 200


def test_the_token_is_committed_before_the_mail_goes_out(anonymous_client, db, monkeypatch):
    """Guarda del `commit` explícito de `_issue_confirmation`.

    Medido en FastAPI 0.141: los background tasks corren **antes** del cierre de las
    dependencias con `yield`, o sea antes del commit de `get_db`. Sin el commit explícito el
    mail sale con un token que todavía no está en la base y la transacción queda abierta
    durante toda la conexión SMTP.

    Es la clase de línea que se borra por parecer redundante —`get_db` ya commitea— y cuyo
    borrado no rompe ningún otro test: los demás corren dentro de una sola transacción y no
    pueden ver la diferencia. Este mira el orden y no el resultado, que es lo único que la
    distingue.
    """
    order = []
    original_commit = type(db).commit

    def spy_commit(self, *args, **kwargs):
        order.append("commit")
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(type(db), "commit", spy_commit)
    monkeypatch.setattr(email_service, "send_email", lambda **kwargs: order.append("mail"))

    register(anonymous_client, "ana@cucu.com")

    assert "mail" in order
    assert order.index("commit") < order.index("mail")
