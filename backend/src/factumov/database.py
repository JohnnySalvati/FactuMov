from collections.abc import Generator

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


class Settings(BaseSettings):
    # `extra="ignore"` no es cosmético: pydantic-settings prohíbe los extras por default y
    # el .env es uno solo para toda la app. Sin esto, la primera variable de otro dominio
    # —SMTP_HOST, por ejemplo— hace fallar la construcción de Settings, que ocurre al
    # importar este módulo, o sea que se cae la app entera y la suite completa por una
    # variable que este objeto nunca iba a mirar. `EmailSettings` lo lleva por lo mismo,
    # con DATABASE_URL en el rol inverso.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    database_test_url: str | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+psycopg://", 1)
        elif value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql+psycopg://", 1)
        return value


settings = Settings()  # type: ignore
engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session]:
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
