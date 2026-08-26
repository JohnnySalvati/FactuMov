"""Verificación de la delegación: `services/wsfe.py` y `POST /{id}/verify-delegation`.

El SOAP está mockeado en el nivel más bajo que tiene sentido —`arca.build_client`— así que lo
que se ejercita de verdad es la lectura de la respuesta de WSFE, que es donde está la decisión
del proyecto: qué códigos son "no estás delegado", cuáles son "sí pero no tenés puntos de
venta" y cuáles son un error que no sabemos leer.

`arca.get_access_ticket` se parchea aparte porque abre su propia sesión contra la base real
—a propósito, para que un ticket recién emitido sobreviva al rollback del request— y en un
test de router eso escribiría filas fuera de la transacción del fixture.
"""

from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from zeep.exceptions import Fault

from factumov.exceptions import ArcaError, WsfeError
from factumov.services import arca, wsfe
from tests.factories import make_fiscal_identity

NOT_DELEGATED_MSG = "ValidacionDeToken: No apareció CUIT en lista de relaciones"

OK = SimpleNamespace(Errors=None, ResultGet=SimpleNamespace(PtoVenta=[]))
NOT_DELEGATED = SimpleNamespace(
    Errors=SimpleNamespace(Err=[SimpleNamespace(Code=600, Msg=NOT_DELEGATED_MSG)])
)
NO_PTOS_VENTA = SimpleNamespace(
    Errors=SimpleNamespace(Err=[SimpleNamespace(Code=602, Msg="No existen datos")])
)
UNEXPECTED = SimpleNamespace(
    Errors=SimpleNamespace(Err=[SimpleNamespace(Code=1000, Msg="Error interno")])
)


@pytest.fixture(autouse=True)
def ticket(monkeypatch):
    """Un TA ya emitido, sin tocar la base ni la red."""
    monkeypatch.setattr(
        arca, "get_access_ticket", lambda service: arca.AccessTicket(token="tk", sign="sg")
    )


@pytest.fixture
def wsfe_returns(monkeypatch):
    """Devuelve una función que fija la respuesta de `FEParamGetPtosVenta` y registra el Auth."""
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
            lambda url: SimpleNamespace(service=SimpleNamespace(FEParamGetPtosVenta=operation)),
        )
        return calls

    return configure


# --- El servicio ----------------------------------------------------------------------


def test_check_delegation_is_granted_when_arca_answers_without_errors(wsfe_returns):
    wsfe_returns(OK)

    assert wsfe.check_delegation("20111111112") == wsfe.DelegationCheck(granted=True)


def test_check_delegation_sends_the_represented_tax_id_as_auth_cuit(wsfe_returns):
    """La brecha entre el CUIT del certificado y el del `Auth` *es* la delegación."""
    calls = wsfe_returns(OK)

    wsfe.check_delegation("30712345678")

    assert calls[0]["Auth"] == {"Token": "tk", "Sign": "sg", "Cuit": "30712345678"}


def test_check_delegation_is_not_granted_on_code_600(wsfe_returns):
    wsfe_returns(NOT_DELEGATED)

    check = wsfe.check_delegation("20111111112")

    assert check.granted is False
    assert check.message is not None
    assert NOT_DELEGATED_MSG in check.message


def test_a_delegated_taxpayer_without_puntos_de_venta_is_still_granted(wsfe_returns):
    """602 es "no hay datos", no "no estás autorizado".

    La prueba de que la delegación está es que ARCA aceptó el Auth y contestó sobre los datos
    del contribuyente en vez de rechazar el token. Tratarlo como falla sería un falso negativo
    justo con el usuario nuevo, que es el que más va a usar este endpoint.
    """
    wsfe_returns(NO_PTOS_VENTA)

    assert wsfe.check_delegation("20111111112").granted is True


def test_an_unknown_error_code_raises_instead_of_answering_no(wsfe_returns):
    """Contestar `granted=False` haría reintentar para siempre una delegación ya otorgada."""
    wsfe_returns(UNEXPECTED)

    with pytest.raises(WsfeError):
        wsfe.check_delegation("20111111112")


def test_a_soap_fault_is_a_wsfe_error(wsfe_returns):
    wsfe_returns(Fault("algo salió mal"))

    with pytest.raises(WsfeError):
        wsfe.check_delegation("20111111112")


def test_a_network_failure_is_an_arca_error(wsfe_returns):
    wsfe_returns(RequestsConnectionError("sin ruta al host"))

    with pytest.raises(ArcaError):
        wsfe.check_delegation("20111111112")


# --- El endpoint ----------------------------------------------------------------------


def verify(client, fiscal_identity):
    return client.post(f"/fiscal-identities/{fiscal_identity.id}/verify-delegation")


def test_verify_delegation_stamps_the_row_when_arca_says_yes(
    client, db, fiscal_identity, wsfe_returns
):
    wsfe_returns(OK)

    response = verify(client, fiscal_identity)

    assert response.status_code == 200
    assert response.json()["granted"] is True
    assert response.json()["delegation_verified_at"] is not None
    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_verified_at is not None


def test_verify_delegation_answers_200_when_the_delegation_is_missing(
    client, db, fiscal_identity, wsfe_returns
):
    """Preguntar y que te contesten "todavía no" no es un error del cliente."""
    wsfe_returns(NOT_DELEGATED)

    response = verify(client, fiscal_identity)

    assert response.status_code == 200
    assert response.json()["granted"] is False
    assert NOT_DELEGATED_MSG in response.json()["message"]
    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_verified_at is None


def test_verify_delegation_tells_which_tax_id_to_authorize(
    client, fiscal_identity, wsfe_returns, arca_cert
):
    """La respuesta negativa lleva el CUIT de FactuMov, que es la instrucción que sigue."""
    wsfe_returns(NOT_DELEGATED)

    assert verify(client, fiscal_identity).json()["delegate_tax_id"] == arca_cert


def test_verify_delegation_survives_a_missing_certificate(client, fiscal_identity, wsfe_returns):
    """Sin certificado configurado la respuesta sale igual, sin el CUIT. Es un extra, no el dato."""
    wsfe_returns(NOT_DELEGATED)

    response = verify(client, fiscal_identity)

    assert response.status_code == 200
    assert response.json()["delegate_tax_id"] is None


def test_verify_delegation_is_502_when_arca_cannot_be_reached(
    client, fiscal_identity, wsfe_returns
):
    wsfe_returns(RequestsConnectionError("sin ruta al host"))

    response = verify(client, fiscal_identity)

    assert response.status_code == 502
    # El detalle de ARCA no se propaga: no le dice nada al usuario y filtra cómo estamos armados.
    assert "ARCA" in response.json()["detail"]
    assert "sin ruta al host" not in response.json()["detail"]


def test_verify_delegation_on_someone_elses_identity_is_404(client, db, other_user, wsfe_returns):
    """Mismo criterio que el resto del scoping: la fila ajena no existe, no da 403."""
    wsfe_returns(OK)
    ajena = make_fiscal_identity(db, user_id=other_user.id)

    assert verify(client, ajena).status_code == 404


def test_verify_delegation_needs_a_session(anonymous_client, fiscal_identity, wsfe_returns):
    wsfe_returns(OK)

    assert verify(anonymous_client, fiscal_identity).status_code == 401


def test_verify_delegation_is_rate_limited(client, fiscal_identity, wsfe_returns):
    """La cuota de ARCA es del certificado, o sea compartida por todos los usuarios.

    El límite se lee del propio limitador en vez de repetir el número: si mañana pasa de 10 a
    20 por hora, este test tiene que seguir probando el límite y no fallar por saberse uno
    viejo de memoria.
    """
    from factumov.routers.fiscal_identity import _VERIFY_DELEGATION_LIMITER

    wsfe_returns(NOT_DELEGATED)
    for _ in range(_VERIFY_DELEGATION_LIMITER.limit):
        assert verify(client, fiscal_identity).status_code == 200

    assert verify(client, fiscal_identity).status_code == 429
