import pytest
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from factumov.database import get_db
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
def client(db):
    """A TestClient whose requests run inside the test's own transaction.

    Overriding `get_db` is what ties the two together: without it the app would open its
    own session against the real database, so nothing the request wrote would be visible
    to `db` and nothing `db` arranged would be visible to the request.

    The override deliberately does not commit, unlike the real `get_db`. Rolling the whole
    thing back is the `db` fixture's job.
    """

    def get_test_db():
        yield db

    app.dependency_overrides[get_db] = get_test_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def fiscal_identity(db):
    return factories.make_fiscal_identity(db)


@pytest.fixture
def customer(db):
    return factories.make_customer(db)
