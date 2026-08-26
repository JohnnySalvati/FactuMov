import secrets
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
from tests import factories


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
def fiscal_identity(db):
    return factories.make_fiscal_identity(db)


@pytest.fixture
def customer(db):
    return factories.make_customer(db)
