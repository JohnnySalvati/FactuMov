"""Autenticación contra WSAA — el paso previo a cualquier llamada a un servicio de ARCA.

Port del `services/arca.py` de Balance360, con tres cambios que no son cosméticos:

1. **Config propia** (`ArcaSettings`), en vez de importar el `settings` global de
   `database.py`. Mismo criterio que `services/email.py`: ese `Settings` es sobre la base, y
   el certificado de ARCA se configura y falla por separado. Se construye adentro de las
   funciones con `lru_cache`, así un `.env` sin certificado no rompe el import del paquete.
2. **El ticket vive en la base** (`arca_tickets`) y no en un `ticket_arca.json` del cwd. El
   porqué está en el docstring del modelo: un solo certificado compartido por N workers, y un
   WSAA que se niega a emitir un ticket nuevo mientras el anterior siga vigente.
3. **El CUIT del certificado no es el CUIT representado.** En Balance360 coinciden —el
   certificado es del propio contribuyente—; acá el certificado es de FactuMov y representa a
   terceros. Por eso `get_certificate_tax_id()` no se usa como `Auth.Cuit`: eso lo decide cada
   llamada a WSFE, y esa brecha es justamente lo que la delegación habilita.
"""

import base64
import hashlib
import secrets
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key, pkcs7
from cryptography.x509 import Certificate, load_pem_x509_certificate
from cryptography.x509.oid import NameOID
from pydantic_settings import BaseSettings, SettingsConfigDict
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.poolmanager import PoolManager
from zeep import Client
from zeep.cache import SqliteCache
from zeep.exceptions import Fault
from zeep.transports import Transport

from factumov import database
from factumov.crud import arca_ticket as arca_ticket_crud
from factumov.exceptions import ArcaError, WsaaError

WSAA_URL = {
    "homo": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL",
    "prod": "https://wsaa.afip.gov.ar/ws/services/LoginCms?WSDL",
}

# ARCA se cuelga: sin timeout el worker espera para siempre. Es más generoso que los 10 s del
# SMTP porque acá hay un usuario esperando la respuesta y WSAA tarda de verdad.
ARCA_TIMEOUT_SECONDS = 30

# El TRA vale diez minutos para adelante y diez para atrás. El margen hacia atrás cubre el
# desfasaje de reloj contra el server de ARCA, que rechaza un generationTime futuro.
TRA_WINDOW = timedelta(minutes=10)


class ArcaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Default "homo" a propósito: si la variable falta, la app pega contra homologación y no
    # contra el ARCA real. Equivocarse hacia el entorno de pruebas es gratis; al revés no.
    arca_env: Literal["homo", "prod"] = "homo"
    arca_cert_path: Path | None = None
    arca_private_key_path: Path | None = None
    # zeep cachea los WSDL en SQLite. Sin path explícito usa el temp del sistema, que en un
    # contenedor efímero se pierde en cada deploy y obliga a bajar el WSDL entero de nuevo.
    arca_wsdl_cache_path: Path | None = None
    # El CUIT al que el contribuyente le delega WSFE: el dueño del certificado de FactuMov.
    # Es el mismo con el que Balance360 ya emite —para sí mismo y para quienes le delegaron—,
    # y tiene los servicios y los certificados dados de alta en ARCA.
    #
    # Tiene default real y no placeholder porque el CUIT es un hecho del proyecto, no de la
    # instalación: el certificado es uno solo para toda la app. La variable existe igual para
    # el día que FactuMov saque un certificado propio y haya que migrar sin tocar código.
    #
    # Vive en `ArcaSettings` y no en `EmailSettings`, que es donde estaba: es un dato de ARCA
    # que el mail *usa*, no un dato del mail. Estaba ahí solo porque el mail fue su primer
    # consumidor y esta clase todavía no existía.
    arca_delegate_tax_id: str = "20182810674"


@lru_cache
def get_arca_settings() -> ArcaSettings:
    return ArcaSettings()


class _AfipTlsAdapter(HTTPAdapter):
    """Baja el nivel de seguridad de OpenSSL solo para la conexión con ARCA.

    Los servidores de ARCA negocian Diffie-Hellman de 1024 bits, que el OpenSSL moderno
    rechaza por defecto (SECLEVEL 2). SECLEVEL=1 lo permite. **No** desactiva la verificación
    del certificado del servidor: solo afloja la fuerza mínima del cifrado.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        context = ssl.create_default_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        self._ssl_context = context
        super().__init__(*args, **kwargs)

    def init_poolmanager(
        self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any
    ) -> None:
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=self._ssl_context,
            **pool_kwargs,
        )


def build_client(url: str) -> Client:
    """Cliente SOAP con el workaround de TLS y el timeout puestos.

    Es una función de módulo y no un cliente global para que un test pueda parchear el nombre
    entero — el mismo criterio que `MAX_UPLOAD_BYTES` y que `notifications.py`.
    """
    settings = get_arca_settings()
    cache = (
        SqliteCache(path=str(settings.arca_wsdl_cache_path))
        if settings.arca_wsdl_cache_path
        else SqliteCache()
    )
    session = requests.Session()
    session.mount("https://", _AfipTlsAdapter())
    transport = Transport(
        session=session,
        timeout=ARCA_TIMEOUT_SECONDS,
        operation_timeout=ARCA_TIMEOUT_SECONDS,
        cache=cache,
    )
    return Client(url, transport=transport)


def _load_certificate() -> Certificate:
    settings = get_arca_settings()
    if settings.arca_cert_path is None:
        raise ArcaError("El certificado de ARCA no está configurado (ARCA_CERT_PATH)")
    try:
        return load_pem_x509_certificate(settings.arca_cert_path.read_bytes())
    except OSError as exc:
        raise ArcaError(f"No se pudo leer el certificado de ARCA: {exc}") from exc
    except ValueError as exc:
        raise ArcaError(f"El certificado de ARCA no es un PEM válido: {exc}") from exc


def build_tra(service: str) -> str:
    """El Ticket Request Access: el XML que se firma y se le manda a WSAA.

    `uniqueId` es aleatorio y no el timestamp que usa Balance360: dos pedidos en el mismo
    segundo generarían el mismo id, y ARCA usa ese número para distinguirlos.
    """
    now = datetime.now(timezone.utc)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<loginTicketRequest>"
        "<header>"
        f"<uniqueId>{secrets.randbelow(2**31)}</uniqueId>"
        f"<generationTime>{(now - TRA_WINDOW).isoformat()}</generationTime>"
        f"<expirationTime>{(now + TRA_WINDOW).isoformat()}</expirationTime>"
        "</header>"
        f"<service>{service}</service>"
        "</loginTicketRequest>"
    )


def sign_tra(xml: str) -> bytes:
    """Firma el TRA como PKCS#7 DER con el certificado y la clave privada de FactuMov."""
    settings = get_arca_settings()
    if settings.arca_private_key_path is None:
        raise ArcaError("La clave privada de ARCA no está configurada (ARCA_PRIVATE_KEY_PATH)")

    certificate = _load_certificate()
    try:
        key_data = settings.arca_private_key_path.read_bytes()
    except OSError as exc:
        raise ArcaError(f"No se pudo leer la clave privada de ARCA: {exc}") from exc
    try:
        private_key = load_pem_private_key(key_data, password=None)
    except (ValueError, TypeError) as exc:
        raise ArcaError(f"La clave privada de ARCA no es un PEM válido: {exc}") from exc

    return (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(xml.encode("utf-8"))
        .add_signer(certificate, private_key, hashes.SHA256())  # type: ignore[arg-type]
        .sign(serialization.Encoding.DER, [])
    )


def get_certificate_tax_id() -> str:
    """El CUIT dueño del certificado, leído del `serialNumber` del subject.

    Es el CUIT de FactuMov: el que el contribuyente autoriza en ARCA al otorgar la delegación.
    Se lee del certificado y no de una variable de entorno justamente para que no puedan
    quedar en desacuerdo — el mail de instrucciones nombra a este número.
    """
    certificate = _load_certificate()
    for attribute in certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER):
        digits = "".join(c for c in str(attribute.value) if c.isdigit())
        if len(digits) == 11:
            return digits
    raise ArcaError("El certificado de ARCA no tiene un CUIT en el subject")


def get_delegate_tax_id() -> str:
    """El CUIT que el usuario tiene que autorizar en ARCA.

    **El certificado manda.** Es la única fuente que no puede mentir: es literalmente el CUIT
    que ARCA va a ver del otro lado, así que mientras haya certificado configurado el mail de
    instrucciones y la verificación de la delegación no pueden nombrar números distintos.

    `ARCA_DELEGATE_TAX_ID` es la respuesta cuando no hay certificado en esta máquina — un
    worker que solo manda mails, por ejemplo. Es un fallback y no una alternativa: si los dos
    están y discrepan, el que vale es el certificado, porque el otro es una variable que
    alguien escribió a mano.
    """
    try:
        return get_certificate_tax_id()
    except ArcaError:
        return get_arca_settings().arca_delegate_tax_id


@dataclass(frozen=True)
class AccessTicket:
    """Lo único que los servicios de ARCA necesitan del TA: token y sign."""

    token: str
    sign: str


@dataclass(frozen=True)
class IssuedTicket:
    """Lo que WSAA acaba de emitir, antes de guardarse."""

    token: str
    sign: str
    expires_at: datetime


def _parse_login_response(response: str) -> IssuedTicket:
    try:
        tree = ET.fromstring(response)
    except ET.ParseError as exc:
        raise WsaaError(f"WSAA devolvió un XML que no se pudo parsear: {exc}") from exc

    token = tree.findtext(".//token")
    sign = tree.findtext(".//sign")
    expiration_time = tree.findtext(".//expirationTime")
    if not token or not sign or not expiration_time:
        raise WsaaError("La respuesta de WSAA no trae token, sign o expirationTime")

    try:
        expires_at = datetime.fromisoformat(expiration_time)
    except ValueError as exc:
        raise WsaaError(f"WSAA devolvió un expirationTime ilegible: {expiration_time}") from exc

    return IssuedTicket(token=token, sign=sign, expires_at=expires_at)


def request_ticket(service: str) -> IssuedTicket:
    """Pide un TA nuevo a WSAA. Va siempre a la red: el cacheo es de `get_access_ticket`."""
    settings = get_arca_settings()
    signed = sign_tra(build_tra(service))
    try:
        client = build_client(WSAA_URL[settings.arca_env])
        response: str = client.service.loginCms(in0=base64.b64encode(signed).decode("ascii"))
    except Fault as exc:
        # Acá caen "Computador no autorizado a acceder al servicio" (el certificado no está
        # habilitado para ese WS) y "El CEE ya posee un TA valido". Las dos son nuestras, no
        # del usuario: por eso son WsaaError y terminan en un 502, no en un 400.
        raise WsaaError(f"WSAA rechazó el pedido: {exc}") from exc
    except RequestException as exc:
        raise ArcaError("No se pudo conectar con ARCA, reintentá en unos minutos") from exc
    return _parse_login_response(response)


def _lock_key(env: str, service: str) -> int:
    """Un bigint estable para el advisory lock, derivado de (env, service).

    `hash()` no sirve: Python lo aleatoriza por proceso (PYTHONHASHSEED), así que dos workers
    tomarían candados distintos para la misma clave y el lock no serializaría nada.
    """
    digest = hashlib.blake2b(f"{env}:{service}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def get_access_ticket(service: str) -> AccessTicket:
    """El TA vigente para un servicio, renovándolo contra WSAA si hace falta.

    Corre en **su propia sesión, con su propio commit**, desacoplada de la transacción del
    request. Si el ticket recién emitido se perdiera en el rollback del request, WSAA no
    emitiría otro hasta que venciera el anterior —hasta doce horas— y la app quedaría afuera
    de ARCA sin nada roto que se pueda ver.

    La renovación va detrás de un `pg_advisory_xact_lock` y no de un `SELECT ... FOR UPDATE`:
    la primera vez no hay fila que trabar, así que el FOR UPDATE no bloquearía a nadie y los N
    workers pedirían un TA cada uno. El advisory lock traba la *clave*, exista o no la fila.
    """
    env = get_arca_settings().arca_env

    # Camino rápido, sin candado: es el caso de casi todos los requests.
    with database.SessionLocal() as db:
        cached = arca_ticket_crud.get_valid(db, env=env, service=service)
        if cached is not None:
            return AccessTicket(token=cached.token, sign=cached.sign)

    with database.SessionLocal() as db:
        arca_ticket_crud.lock(db, key=_lock_key(env, service))
        # Segunda lectura, ya adentro del candado: mientras esperábamos, otro worker pudo
        # haber renovado. Sin esto el candado serializa los pedidos en vez de evitarlos.
        cached = arca_ticket_crud.get_valid(db, env=env, service=service)
        if cached is None:
            issued = request_ticket(service)
            cached = arca_ticket_crud.upsert(
                db,
                env=env,
                service=service,
                token=issued.token,
                sign=issued.sign,
                expires_at=issued.expires_at,
            )
        ticket = AccessTicket(token=cached.token, sign=cached.sign)
        db.commit()
    return ticket
