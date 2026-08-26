"""Tests de `services/arca.py`: TRA, firma, CUIT del certificado y caché del ticket.

Nada de esto sale a la red. Lo que se ejercita es lo que se puede romper sin que ARCA se
entere: el XML que se firma, la lectura del certificado, el parseo de la respuesta y —lo más
importante— que el ticket no se pida dos veces cuando ya hay uno vigente. Pedirlo de más no
falla lento: WSAA se **niega** a emitir uno nuevo mientras el anterior viva, así que el
segundo pedido es un error y la app queda afuera de ARCA hasta doce horas.

La conexión de verdad contra homologación es una prueba manual y no un test: depende de un
certificado que no está en el repo y de que ARCA esté levantado.
"""

import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from factumov import database
from factumov.exceptions import ArcaError, WsaaError
from factumov.models.arca_ticket import ArcaTicket
from factumov.services import arca
from tests.conftest import CERTIFICATE_TAX_ID
from tests.factories import make_arca_ticket


@pytest.fixture
def arca_db(monkeypatch, db):
    """Hace que `get_access_ticket` use la sesión del test en vez de abrir la suya.

    El servicio pide la sesión como `database.SessionLocal()` —el módulo, no el nombre
    importado— justamente para que se pueda parchear desde acá. Sin esto escribiría contra la
    base real, fuera de la transacción del fixture `db`, y las filas quedarían.

    El contextmanager no cierra la sesión al salir: `get_access_ticket` abre dos, y la segunda
    encontraría cerrada la del test. El `commit()` de adentro sí ocurre, pero bajo el
    `join_transaction_mode="create_savepoint"` del fixture solo suelta un savepoint.
    """

    @contextmanager
    def session_without_closing():
        yield db

    monkeypatch.setattr(database, "SessionLocal", session_without_closing)
    return db


def issued(token):
    return arca.IssuedTicket(
        token=token, sign="firma", expires_at=datetime.now(UTC) + timedelta(hours=12)
    )


def stored_tickets(db, env="homo", service="wsfe"):
    return list(
        db.execute(select(ArcaTicket).where(ArcaTicket.env == env, ArcaTicket.service == service))
        .scalars()
        .all()
    )


# --- TRA y firma ----------------------------------------------------------------------


def test_build_tra_names_the_service_and_opens_the_window_backwards():
    """El generationTime va en el pasado: ARCA rechaza uno futuro y los relojes difieren."""
    xml = ET.fromstring(arca.build_tra("wsfe"))

    assert xml.findtext("service") == "wsfe"
    generation = datetime.fromisoformat(xml.findtext("header/generationTime") or "")
    expiration = datetime.fromisoformat(xml.findtext("header/expirationTime") or "")
    assert generation < datetime.now(UTC) < expiration


def test_build_tra_uses_a_different_unique_id_each_time():
    """Dos TRA en el mismo segundo tienen que distinguirse; el timestamp no alcanzaba."""
    ids = {ET.fromstring(arca.build_tra("wsfe")).findtext("header/uniqueId") for _ in range(20)}

    assert len(ids) > 1


def test_sign_tra_signs_with_our_certificate(arca_cert):
    signed = arca.sign_tra(arca.build_tra("wsfe"))

    serial_numbers = [
        attribute.value
        for certificate in pkcs7.load_der_pkcs7_certificates(signed)
        for attribute in certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    ]
    assert f"CUIT {CERTIFICATE_TAX_ID}" in serial_numbers


def test_sign_tra_without_a_certificate_is_an_arca_error():
    """Certificado sin configurar es un problema nuestro, no una respuesta de ARCA."""
    with pytest.raises(ArcaError):
        arca.sign_tra(arca.build_tra("wsfe"))


def test_sign_tra_with_a_key_that_is_not_a_pem_is_an_arca_error(monkeypatch, arca_cert, tmp_path):
    broken = tmp_path / "roto.key"
    broken.write_text("esto no es una clave")
    monkeypatch.setenv("ARCA_PRIVATE_KEY_PATH", str(broken))
    arca.get_arca_settings.cache_clear()

    with pytest.raises(ArcaError):
        arca.sign_tra(arca.build_tra("wsfe"))


# --- CUIT del certificado -------------------------------------------------------------


def test_get_certificate_tax_id_reads_the_serial_number(arca_cert):
    """Se queda con los once dígitos y descarta el prefijo "CUIT " que ARCA le pone."""
    assert arca.get_certificate_tax_id() == CERTIFICATE_TAX_ID


def test_get_certificate_tax_id_without_a_certificate_is_an_arca_error():
    with pytest.raises(ArcaError):
        arca.get_certificate_tax_id()


# --- Parseo de la respuesta de WSAA ---------------------------------------------------


LOGIN_RESPONSE = """<?xml version="1.0"?>
<loginTicketResponse>
  <header><expirationTime>2026-08-27T10:00:00.000-03:00</expirationTime></header>
  <credentials><token>UNTOKEN</token><sign>UNASIGN</sign></credentials>
</loginTicketResponse>"""


def test_parse_login_response_extracts_token_sign_and_expiry():
    issued_ticket = arca._parse_login_response(LOGIN_RESPONSE)

    assert issued_ticket.token == "UNTOKEN"
    assert issued_ticket.sign == "UNASIGN"
    # Con offset y no naive: la columna es `DateTime(timezone=True)` y compararla con un
    # naive es el TypeError que el proyecto ya se comió una vez con `user_sessions`.
    assert issued_ticket.expires_at == datetime(
        2026, 8, 27, 10, 0, tzinfo=timezone(timedelta(hours=-3))
    )


def test_parse_login_response_without_credentials_is_a_wsaa_error():
    """Una respuesta 200 con el cuerpo cambiado no puede pasar por un ticket vacío."""
    with pytest.raises(WsaaError):
        arca._parse_login_response("<loginTicketResponse></loginTicketResponse>")


def test_parse_login_response_that_is_not_xml_is_a_wsaa_error():
    with pytest.raises(WsaaError):
        arca._parse_login_response("<html>error 503</html")


# --- Caché del ticket -----------------------------------------------------------------


def test_get_access_ticket_reuses_a_valid_ticket(arca_db, monkeypatch):
    """El caso que importa: con un ticket vigente no se le pregunta nada a WSAA.

    `request_ticket` se parchea para que falle el test si alguien la llama. Comparar solo el
    token dejaría pasar una implementación que sale a la red y devuelve lo mismo.
    """
    make_arca_ticket(arca_db, token="guardado", sign="firma")
    monkeypatch.setattr(
        arca, "request_ticket", lambda service: pytest.fail("no tenía que pedir un ticket nuevo")
    )

    assert arca.get_access_ticket("wsfe") == arca.AccessTicket(token="guardado", sign="firma")


def test_get_access_ticket_renews_an_expired_ticket(arca_db, monkeypatch):
    make_arca_ticket(arca_db, token="viejo", expires_at=datetime.now(UTC) - timedelta(hours=1))
    monkeypatch.setattr(arca, "request_ticket", lambda service: issued("nuevo"))

    assert arca.get_access_ticket("wsfe").token == "nuevo"


def test_get_access_ticket_renews_a_ticket_about_to_expire(arca_db, monkeypatch):
    """Un TA que vence en un minuto es inservible: la llamada que lo use tarda más que eso."""
    make_arca_ticket(
        arca_db, token="por-vencer", expires_at=datetime.now(UTC) + timedelta(minutes=1)
    )
    monkeypatch.setattr(arca, "request_ticket", lambda service: issued("nuevo"))

    assert arca.get_access_ticket("wsfe").token == "nuevo"


def test_renewing_replaces_the_row_instead_of_adding_one(arca_db, monkeypatch):
    """Una sola fila por (env, service): el TA viejo no le sirve a nadie y el unique lo impide."""
    make_arca_ticket(arca_db, token="viejo", expires_at=datetime.now(UTC) - timedelta(hours=1))
    monkeypatch.setattr(arca, "request_ticket", lambda service: issued("nuevo"))

    arca.get_access_ticket("wsfe")

    rows = stored_tickets(arca_db)
    assert len(rows) == 1
    assert rows[0].token == "nuevo"


def test_get_access_ticket_keeps_one_ticket_per_service(arca_db, monkeypatch):
    """El padrón y WSFE tienen tickets distintos: el TA se emite por servicio."""
    monkeypatch.setattr(arca, "request_ticket", lambda service: issued(f"token-{service}"))

    assert arca.get_access_ticket("wsfe").token == "token-wsfe"
    assert arca.get_access_ticket("ws_sr_constancia_inscripcion").token == (
        "token-ws_sr_constancia_inscripcion"
    )
    assert len(stored_tickets(arca_db, service="wsfe")) == 1


def test_lock_key_is_stable_and_differs_per_key():
    """Tiene que valer lo mismo en todos los workers: con `hash()` no valdría."""
    assert arca._lock_key("homo", "wsfe") == arca._lock_key("homo", "wsfe")
    assert arca._lock_key("homo", "wsfe") != arca._lock_key("prod", "wsfe")
    # Postgres solo acepta bigint en `pg_advisory_xact_lock`.
    assert -(2**63) <= arca._lock_key("homo", "wsfe") < 2**63
