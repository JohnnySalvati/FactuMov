import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from factumov.database import get_db
from factumov.dependencies import SESSION_COOKIE_NAME
from factumov.main import app
from factumov.models.base import Base
from factumov.services import arca as arca_service
from factumov.services import email as email_service
from factumov.services.rate_limit import reset_all as reset_all_limiters
from tests import factories


@dataclass
class SentEmail:
    to: str
    subject: str
    body: str
    # Lo que se adjuntó. Es una lista y no un bool porque los tests de la factura por mail
    # afirman sobre el nombre del archivo y sobre que los bytes sean un PDF de verdad.
    attachments: list = field(default_factory=list)


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Vacía los limitadores entre tests.

    Autouse y obligatorio: los limitadores son globales de módulo y el TestClient se
    presenta siempre con la misma IP, así que sin esto el sexto test que registra algo
    empieza a comer 429 — y no falla el test que rompió nada, sino el que quedó sexto, que
    va cambiando con el orden de colección.
    """
    reset_all_limiters()
    yield
    reset_all_limiters()


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
    email_service.get_email_settings.cache_clear()
    yield
    email_service.get_email_settings.cache_clear()


# El CUIT que lleva el certificado de prueba en el `serialNumber` del subject. No es el de
# nadie, y no es el de FactuMov: el real vive en el default de `ArcaSettings`.
CERTIFICATE_TAX_ID = "20111111112"

# Lo que contesta `get_delegate_tax_id` cuando no hay certificado configurado. Distinto del
# de arriba a propósito: así un test puede probar cuál de los dos gana.
FALLBACK_DELEGATE_TAX_ID = "30999999997"


@pytest.fixture(autouse=True)
def arca_settings(monkeypatch):
    """Config de ARCA determinística, y sin certificado por default.

    Autouse y por el mismo motivo que `email_settings`: desengancha el `.env` para que el
    certificado real de una máquina no cambie el resultado de un test en esa máquina y en
    ninguna otra. Acá pesa más que con el mail — un `.env` con ARCA_CERT_PATH apuntando a un
    certificado de producción convertiría un test en una llamada real a ARCA.

    El default es **sin certificado**, así el test que se olvide de pedir el fixture del
    certificado falla con un `ArcaError` explícito y no con un archivo que no existe.
    """
    monkeypatch.setitem(arca_service.ArcaSettings.model_config, "env_file", None)
    for absent in ("ARCA_CERT_PATH", "ARCA_PRIVATE_KEY_PATH", "ARCA_WSDL_CACHE_PATH"):
        monkeypatch.delenv(absent, raising=False)
    monkeypatch.setenv("ARCA_ENV", "homo")
    # El CUIT del fallback, para el caso sin certificado. No es el real: un test que dependa
    # de ese número tiene que decirlo, no heredarlo del `.env` de la máquina.
    monkeypatch.setenv("ARCA_DELEGATE_TAX_ID", FALLBACK_DELEGATE_TAX_ID)
    arca_service.get_arca_settings.cache_clear()
    yield
    arca_service.get_arca_settings.cache_clear()


@pytest.fixture(scope="session")
def certificate_files(tmp_path_factory):
    """Un certificado autofirmado con un CUIT en el `serialNumber`, y su clave privada.

    Se genera de verdad en vez de guardarse un PEM fijo en el repo: un certificado versionado
    vence, y el día que venza el que falla es un test que no tiene nada que ver. Además nadie
    tiene que preguntarse si ese archivo es una credencial real.

    Scope de sesión porque generar una RSA de 2048 bits cuesta décimas de segundo, y la suite
    entera pesa ocho — el mismo criterio por el que `factories.PASSWORD_HASHED` se calcula una
    sola vez.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "factumov-test"),
            # ARCA escribe el CUIT así, con prefijo. `get_certificate_tax_id` se queda con la
            # corrida de once dígitos, y el prefijo está acá justamente para probarlo.
            x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CUIT {CERTIFICATE_TAX_ID}"),
        ]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )

    directory = tmp_path_factory.mktemp("arca")
    cert_path = directory / "factumov.crt"
    key_path = directory / "factumov.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture
def arca_cert(monkeypatch, arca_settings, certificate_files):
    """Apunta la config de ARCA al certificado de prueba. Devuelve su CUIT.

    Depende de `arca_settings` a propósito y no solo por orden de autouse: ese fixture llama a
    `cache_clear`, y si corriera después dejaría la config sin certificado otra vez.
    """
    cert_path, key_path = certificate_files
    monkeypatch.setenv("ARCA_CERT_PATH", str(cert_path))
    monkeypatch.setenv("ARCA_PRIVATE_KEY_PATH", str(key_path))
    arca_service.get_arca_settings.cache_clear()
    return CERTIFICATE_TAX_ID


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

    def fake_send(to, subject, body, attachments=()):
        sent.append(SentEmail(to=to, subject=subject, body=body, attachments=list(attachments)))

    monkeypatch.setattr(email_service, "send_email", fake_send)
    return sent


@pytest.fixture
def broken_mail(monkeypatch):
    """El transporte falla. Reemplaza al fake de `sent_emails`, que es autouse.

    Vive acá y no en un archivo de tests porque lo usan dos: el reset de contraseña y el envío
    de una factura. Los dos prueban lo mismo desde distinto ángulo — que un mail que **es** el
    producto del request no se pierda en silencio.
    """

    def explode(to, subject, body, attachments=()):
        raise email_service.EmailDeliveryError("no salió")

    monkeypatch.setattr(email_service, "send_email", explode)


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
