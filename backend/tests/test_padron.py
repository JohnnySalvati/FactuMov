"""Consulta al padrón de ARCA: `services/padron.py` y `GET /customers/lookup/{tax_id}`.

Lo que hay que probar acá no es el SOAP sino la **traducción**: el padrón contesta en su
vocabulario —`razonSocial`, `domicilioFiscal`, `datosMonotributo`, `idImpuesto`— y el editor
espera el de FactuMov. Cada regla de esa traducción es una decisión que se puede romper sin
que ARCA cambie nada: deducir la condición IVA de los impuestos, armar el domicilio en una
línea, recortarlo al largo de la columna.

Las respuestas se arman con `SimpleNamespace` porque zeep devuelve objetos con atributos, y
`padron.py` los lee con `getattr(..., None)` justamente para que una respuesta a la que le
falta un bloque no explote.
"""

from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from zeep.exceptions import Fault

from factumov.enums import CondicionIva, DocType
from factumov.exceptions import ArcaError, PadronError
from factumov.services import arca, padron

MONOTRIBUTO = 20
INSCRIPTO = 30
EXENTO = 32


def response(
    razon_social="ACME SA",
    nombre=None,
    apellido=None,
    domicilio=None,
    impuestos=(),
    monotributo=False,
    estado="ACTIVO",
):
    general = SimpleNamespace(
        razonSocial=razon_social,
        nombre=nombre,
        apellido=apellido,
        domicilioFiscal=domicilio,
        estadoClave=estado,
    )
    return SimpleNamespace(
        datosGenerales=general,
        datosRegimenGeneral=SimpleNamespace(
            impuesto=[SimpleNamespace(idImpuesto=i) for i in impuestos]
        ),
        datosMonotributo=SimpleNamespace(categoriaMonotributo="C") if monotributo else None,
    )


def domicilio(direccion="Av. Siempreviva 742", localidad="Springfield", provincia=None, cp=None):
    return SimpleNamespace(
        direccion=direccion,
        localidad=localidad,
        descripcionProvincia=provincia,
        codPostal=cp,
    )


@pytest.fixture(autouse=True)
def ticket(monkeypatch):
    monkeypatch.setattr(
        arca, "get_access_ticket", lambda service: arca.AccessTicket(token="tk", sign="sg")
    )
    monkeypatch.setattr(arca, "get_certificate_tax_id", lambda: "20111111112")


@pytest.fixture
def padron_returns(monkeypatch):
    calls = []

    def configure(result):
        def operation(**kwargs):
            calls.append(kwargs)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(
            arca,
            "build_client",
            lambda url: SimpleNamespace(service=SimpleNamespace(getPersona_v2=operation)),
        )
        return calls

    return configure


# --- Traducción de la respuesta -------------------------------------------------------


def test_a_juridical_person_uses_its_razon_social():
    taxpayer = padron.to_taxpayer("30712345678", response(razon_social="ACME SA"))

    assert taxpayer.name == "ACME SA"


def test_a_natural_person_gets_name_and_surname_joined():
    """El padrón deja `razonSocial` vacío para las personas físicas."""
    taxpayer = padron.to_taxpayer(
        "20111111112", response(razon_social="", nombre="Miguel", apellido="Salvati")
    )

    assert taxpayer.name == "Miguel Salvati"


def test_monotributo_wins_over_the_impuestos():
    """El monotributo no figura como impuesto: viene en su propio bloque, y hay que mirarlo
    antes que la lista de impuestos."""
    taxpayer = padron.to_taxpayer("20111111112", response(monotributo=True, impuestos=[INSCRIPTO]))

    assert taxpayer.condicion_iva is CondicionIva.MONOTRIBUTO


def test_impuesto_30_is_responsable_inscripto():
    taxpayer = padron.to_taxpayer("30712345678", response(impuestos=[INSCRIPTO]))

    assert taxpayer.condicion_iva is CondicionIva.INSCRIPTO


def test_impuesto_32_is_exento():
    taxpayer = padron.to_taxpayer("30712345678", response(impuestos=[EXENTO]))

    assert taxpayer.condicion_iva is CondicionIva.EXENTO


def test_without_iva_or_monotributo_it_is_consumidor_final():
    """Para el que emite, un CUIT sin IVA ni monotributo se factura como consumidor final."""
    taxpayer = padron.to_taxpayer("20111111112", response(impuestos=[]))

    assert taxpayer.condicion_iva is CondicionIva.FINAL


def test_the_address_becomes_one_line():
    taxpayer = padron.to_taxpayer(
        "30712345678",
        response(domicilio=domicilio(provincia="Buenos Aires", cp="1704")),
    )

    assert taxpayer.address == "Av. Siempreviva 742, Springfield, Buenos Aires, CP 1704"


def test_the_province_is_dropped_when_it_repeats_the_locality():
    """CABA viene dos veces; repetirla en el domicilio impreso queda mal."""
    taxpayer = padron.to_taxpayer(
        "30712345678",
        response(domicilio=domicilio(localidad="CABA", provincia="caba")),
    )

    assert taxpayer.address == "Av. Siempreviva 742, CABA"


def test_a_long_address_is_trimmed_to_the_column(monkeypatch):
    """Preferimos un domicilio incompleto a que el alta explote al guardar."""
    taxpayer = padron.to_taxpayer("30712345678", response(domicilio=domicilio(direccion="x" * 500)))

    assert taxpayer.address is not None
    assert len(taxpayer.address) == padron.ADDRESS_MAX_LENGTH


def test_without_domicilio_the_address_is_none():
    taxpayer = padron.to_taxpayer("30712345678", response(domicilio=None))

    assert taxpayer.address is None


def test_an_inactive_clave_is_reported_as_inactive():
    taxpayer = padron.to_taxpayer("30712345678", response(estado="INACTIVO"))

    assert taxpayer.active is False


def test_a_response_without_datos_generales_is_a_padron_error():
    """La otra forma que tiene ARCA de decir "no tengo a ese CUIT"."""
    with pytest.raises(PadronError):
        padron.to_taxpayer("30712345678", SimpleNamespace(datosGenerales=None))


# --- La consulta ----------------------------------------------------------------------


def test_get_taxpayer_sends_our_tax_id_as_cuit_representada(padron_returns):
    """El padrón se consulta con FactuMov como representada: no hace falta delegación."""
    calls = padron_returns(response())

    padron.get_taxpayer("30-71234567-8")

    assert calls[0]["cuitRepresentada"] == 20111111112
    # Los guiones y puntos se caen antes de consultar.
    assert calls[0]["idPersona"] == 30712345678


def test_a_document_that_is_not_a_cuit_never_reaches_arca(padron_returns):
    padron_returns(response())

    with pytest.raises(PadronError):
        padron.get_taxpayer("12345678")


def test_an_unknown_cuit_is_a_padron_error(padron_returns):
    padron_returns(Fault("No existe persona con ese Id"))

    with pytest.raises(PadronError):
        padron.get_taxpayer("30712345678")


def test_a_network_failure_is_an_arca_error(padron_returns):
    """`PadronError` y `ArcaError` son cosas distintas: 404 contra 502."""
    padron_returns(RequestsConnectionError("sin ruta al host"))

    with pytest.raises(ArcaError):
        padron.get_taxpayer("30712345678")


# --- El endpoint ----------------------------------------------------------------------


def test_lookup_returns_a_prefilled_customer(client, padron_returns):
    padron_returns(response(domicilio=domicilio(cp="1704"), impuestos=[INSCRIPTO]))

    body = client.get("/customers/lookup/30712345678").json()

    assert body == {
        "doc_type": DocType.CUIT.value,
        "doc_number": "30712345678",
        "name": "ACME SA",
        "condicion_iva": CondicionIva.INSCRIPTO.value,
        "address": "Av. Siempreviva 742, Springfield, CP 1704",
        "active": True,
    }


def test_lookup_creates_no_customer(client, db, padron_returns):
    """Es una propuesta, no un alta — igual que el draft de la importación de PDF.

    Sin esto, consultar el mismo CUIT dos veces le dejaría al usuario dos clientes iguales.
    """
    from factumov.models import Customer

    padron_returns(response())
    before = db.query(Customer).count()

    client.get("/customers/lookup/30712345678")

    assert db.query(Customer).count() == before


def test_lookup_of_an_unknown_cuit_is_404(client, padron_returns):
    padron_returns(Fault("No existe persona con ese Id"))

    assert client.get("/customers/lookup/30712345678").status_code == 404


def test_lookup_is_502_when_arca_cannot_be_reached(client, padron_returns):
    padron_returns(RequestsConnectionError("sin ruta al host"))

    response_ = client.get("/customers/lookup/30712345678")

    assert response_.status_code == 502
    assert "sin ruta al host" not in response_.json()["detail"]


def test_lookup_needs_a_session(anonymous_client, padron_returns):
    padron_returns(response())

    assert anonymous_client.get("/customers/lookup/30712345678").status_code == 401


def test_lookup_does_not_shadow_get_customer(client, customer, padron_returns):
    """`/customers/lookup/{tax_id}` y `/customers/{id}` conviven: distinta cantidad de segmentos."""
    padron_returns(response())

    assert client.get(f"/customers/{customer.id}").status_code == 200


def test_lookup_is_rate_limited(client, padron_returns):
    """La cuota del padrón es del certificado, o sea compartida por todos los usuarios."""
    from factumov.routers.customer import _PADRON_LIMITER

    padron_returns(response())
    for _ in range(_PADRON_LIMITER.limit):
        assert client.get("/customers/lookup/30712345678").status_code == 200

    assert client.get("/customers/lookup/30712345678").status_code == 429
