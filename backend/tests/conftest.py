import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from factumov.database import get_db
from factumov.dependencies import SESSION_COOKIE_NAME
from factumov.main import app
from factumov.models.base import Base
from factumov.services import email as email_service
from tests import factories


@dataclass
class SentEmail:
    to: str
    subject: str
    body: str


@pytest.fixture(autouse=True)
def email_settings(monkeypatch):
    """Config de mail determinística para toda la suite.

    Autouse porque `EmailSettings` no tiene defaults para `SMTP_HOST` ni `EMAIL_FROM`: sin
    esto, cualquier test que llegue a componer un mail explota con un ValidationError que
    depende del `.env` de la máquina. Fijarlas acá hace que las aserciones sobre el link de
    confirmación puedan comparar contra una URL concreta.

    Desengancha además el `.env`, y eso no es exceso de celo: la config de mail es la
    primera que cada máquina completa con datos propios, y sin esto un `SMTP_USER` real en
    el `.env` de alguien haría fallar el test de "no hace login sin credenciales" en su
    máquina y en ninguna otra. Las variables de entorno pisan al `.env`, así que fijar las
    que el fixture usa alcanzaría para esas; el problema son justamente las que un test
    necesita *ausentes*.

    El `cache_clear` va de los dos lados. Adelante, porque `get_email_settings` está
    cacheada y otro test pudo haberla construido ya; atrás, para no dejarle a los tests
    siguientes una config armada con variables que `monkeypatch` está por deshacer.
    """
    monkeypatch.setitem(email_service.EmailSettings.model_config, "env_file", None)
    for absent in ("SMTP_USER", "SMTP_PASSWORD", "SMTP_PORT", "SMTP_STARTTLS"):
        monkeypatch.delenv(absent, raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("EMAIL_FROM", "FactuMov <no-reply@test>")
    monkeypatch.setenv("APP_BASE_URL", "https://app.test")
    monkeypatch.setenv("ARCA_DELEGATE_TAX_ID", "20-11111111-2")
    email_service.get_email_settings.cache_clear()
    yield
    email_service.get_email_settings.cache_clear()


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch):
    """Intercepta el envío y devuelve la lista de lo que se mandó.

    Autouse y no opcional: un test que se olvidara de pedirlo abriría un socket SMTP de
    verdad contra `smtp.test`, y la falla sería un timeout de diez segundos sin ninguna
    relación aparente con lo que el test estaba probando.

    Parchea el transporte (`email.send_email`) y no las funciones de `notifications`, así
    los asuntos, los cuerpos y la URL de confirmación se siguen armando de verdad y se
    pueden afirmar sobre ellos.
    """
    sent = []

    def fake_send(to, subject, body):
        sent.append(SentEmail(to=to, subject=subject, body=body))

    monkeypatch.setattr(email_service, "send_email", fake_send)
    return sent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_test_url: str


@pytest.fixture(scope="session")
def engine():
    settings = Settings()  # type: ignore
    engine = create_engine(settings.database_test_url)
    return engine


@pytest.fixture(scope="session")
def tables(engine):
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db(engine, tables):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def _db_override(db):
    """Ata los requests del TestClient a la transacción del test.

    Sobreescribir `get_db` es lo que une las dos puntas: sin esto la app abriría su propia
    sesión contra la base real, así que nada de lo que escribiera el request sería visible
    para `db` y nada de lo que `db` armó sería visible para el request.

    El override no commitea a propósito, a diferencia del `get_db` real: revertir todo es
    trabajo del fixture `db`. La limpieza final no es opcional — `app` es un singleton de
    módulo y un override olvidado se filtraría a todos los tests siguientes.
    """

    def get_test_db():
        yield db

    app.dependency_overrides[get_db] = get_test_db
    yield
    app.dependency_overrides.clear()


def _make_client(**kwargs):
    """`base_url` https, no http.

    La cookie de sesión es `Secure` y el cookie jar de Python se niega a mandarla sobre
    http: sin esto la cookie se setea, nunca vuelve, y todos los tests dan 401 por un motivo
    que no se parece en nada a la causa. Los navegadores no tienen el problema en dev,
    porque tratan `http://localhost` como contexto seguro.
    """
    return TestClient(app, base_url="https://testserver", **kwargs)


@pytest.fixture
def anonymous_client(_db_override):
    """Cliente sin sesión, para los tests que ejercitan el 401."""
    return _make_client()


@pytest.fixture
def user(db):
    """El usuario detrás del fixture `client`: activo y con el email confirmado."""
    return factories.make_user(db, email_confirmed_at=datetime.now(UTC))


@pytest.fixture
def client(_db_override, db, user):
    """Cliente autenticado — el default, porque casi todos los endpoints lo exigen.

    Autentica con una cookie real sobre una fila real de `user_sessions` en vez de
    sobreescribir `get_current_user`: así toda la suite de routers ejercita la dependencia
    de verdad, y la unidad de *ownership scoping* va a tener un `users.id` real del cual
    colgar `fiscal_identities.user_id`.

    No se loguea por HTTP a propósito. Verificar argon2 cuesta ~50-100 ms y por sesenta y
    pico de tests duplicaría la suite; el endpoint de login lo ejercitan sus propios tests,
    que es donde ese costo corresponde.
    """
    raw_token = secrets.token_urlsafe(32)
    factories.make_user_session(db, user_id=user.id, raw_token=raw_token)
    return _make_client(cookies={SESSION_COOKIE_NAME: raw_token})


@pytest.fixture
def other_user(db):
    """Un segundo usuario, para los tests que prueban que no ve lo del primero.

    Activo y confirmado a propósito: si estuviera dado de baja, un test que espera 404
    podría estar pasando por el 401 de `get_current_user` y no por el scoping.
    """
    return factories.make_user(db, email_confirmed_at=datetime.now(UTC))


@pytest.fixture
def fiscal_identity(db, user):
    """Identidad fiscal del usuario de `client` — el caso normal de los tests."""
    return factories.make_fiscal_identity(db, user.id)


@pytest.fixture
def customer(db, user):
    return factories.make_customer(db, user.id)
