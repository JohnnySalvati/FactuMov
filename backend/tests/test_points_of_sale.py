"""La lista de puntos de venta: el parseo en `services/wsfe.py` y `GET /{id}/points-of-sale`.

Es la misma llamada a WSFE que la verificación de delegación —`FEParamGetPtosVenta`— leída
entera en vez de solo mirarle los errores, así que el SOAP se mockea igual que en
`test_delegation.py`: en `arca.build_client`, que es el nivel más bajo que tiene sentido.

Lo que se ejercita acá es qué se ofrece y qué no: un punto de venta bloqueado o dado de baja
existe en la respuesta de ARCA y no tiene que llegar al desplegable, porque elegirlo daría un
rechazo recién al pedir el CAE.
"""

from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from factumov.services import arca, wsfe
from tests.factories import make_fiscal_identity


def pto_venta(number, *, emission_type="CAE", blocked="N", discharge=""):
    """Una fila de `ResultGet.PtoVenta` como la arma zeep a partir del WSDL."""
    return SimpleNamespace(
        Nro=number, EmisionTipo=emission_type, Bloqueado=blocked, FchBaja=discharge
    )


def answer(*points):
    return SimpleNamespace(Errors=None, ResultGet=SimpleNamespace(PtoVenta=list(points)))


NOT_DELEGATED = SimpleNamespace(
    Errors=SimpleNamespace(
        Err=[SimpleNamespace(Code=600, Msg="No apareció CUIT en lista de relaciones")]
    )
)
NO_PTOS_VENTA = SimpleNamespace(
    Errors=SimpleNamespace(Err=[SimpleNamespace(Code=602, Msg="No existen datos")])
)


@pytest.fixture(autouse=True)
def ticket(monkeypatch):
    monkeypatch.setattr(
        arca, "get_access_ticket", lambda service: arca.AccessTicket(token="tk", sign="sg")
    )


@pytest.fixture
def wsfe_returns(monkeypatch):
    def configure(result):
        def operation(**kwargs):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(
            arca,
            "build_client",
            lambda url: SimpleNamespace(service=SimpleNamespace(FEParamGetPtosVenta=operation)),
        )

    return configure


# --- El parseo ------------------------------------------------------------------------


def test_the_points_of_sale_come_back_with_their_number_and_emission_type(wsfe_returns):
    wsfe_returns(answer(pto_venta(5, emission_type="CAE")))

    check = wsfe.check_delegation("20111111112")

    assert check.granted is True
    assert check.points_of_sale == (wsfe.PointOfSale(number=5, emission_type="CAE"),)


def test_the_points_of_sale_come_sorted_by_number(wsfe_returns):
    """El orden de ARCA no está garantizado y un desplegable desordenado se lee peor."""
    wsfe_returns(answer(pto_venta(13), pto_venta(2), pto_venta(5)))

    numbers = [point.number for point in wsfe.check_delegation("20111111112").points_of_sale]

    assert numbers == [2, 5, 13]


def test_a_blocked_point_of_sale_is_not_offered(wsfe_returns):
    """Existe en ARCA pero está inhabilitado: ofrecerlo sería ofrecer un rechazo."""
    wsfe_returns(answer(pto_venta(1, blocked="S"), pto_venta(5)))

    numbers = [point.number for point in wsfe.check_delegation("20111111112").points_of_sale]

    assert numbers == [5]


@pytest.mark.parametrize("discharge", ["20260101", "2026-01-01"])
def test_a_discharged_point_of_sale_is_not_offered(wsfe_returns, discharge):
    wsfe_returns(answer(pto_venta(1, discharge=discharge), pto_venta(5)))

    numbers = [point.number for point in wsfe.check_delegation("20111111112").points_of_sale]

    assert numbers == [5]


@pytest.mark.parametrize("empty", ["", None, "NULL"])
def test_a_point_of_sale_without_a_discharge_date_is_offered(wsfe_returns, empty):
    """ARCA manda el campo vacío de tres formas distintas y las tres significan "sigue vivo"."""
    wsfe_returns(answer(pto_venta(5, discharge=empty)))

    numbers = [point.number for point in wsfe.check_delegation("20111111112").points_of_sale]

    assert numbers == [5]


def test_an_unreadable_number_is_skipped_instead_of_breaking_the_list(wsfe_returns):
    """Esto alimenta un desplegable: un dato ilegible cuesta un renglón, no la consulta."""
    wsfe_returns(answer(pto_venta("no es un número"), pto_venta(5)))

    numbers = [point.number for point in wsfe.check_delegation("20111111112").points_of_sale]

    assert numbers == [5]


def test_a_delegation_without_points_of_sale_comes_back_empty(wsfe_returns):
    """602 sigue siendo "delegado, pero todavía no dio de alta ninguno"."""
    wsfe_returns(NO_PTOS_VENTA)

    check = wsfe.check_delegation("20111111112")

    assert check.granted is True
    assert check.points_of_sale == ()


# --- El endpoint ----------------------------------------------------------------------


def list_points(client, fiscal_identity):
    return client.get(f"/fiscal-identities/{fiscal_identity.id}/points-of-sale")


def test_the_endpoint_lists_what_arca_answered(client, fiscal_identity, wsfe_returns):
    wsfe_returns(answer(pto_venta(5), pto_venta(1, blocked="S")))

    response = list_points(client, fiscal_identity)

    assert response.status_code == 200
    assert response.json() == {
        "granted": True,
        "points": [{"number": 5, "emission_type": "CAE"}],
    }


def test_a_missing_delegation_is_a_200_with_granted_false(client, fiscal_identity, wsfe_returns):
    """No es un error del cliente: el pedido está bien hecho y la respuesta es que todavía no."""
    wsfe_returns(NOT_DELEGATED)

    response = list_points(client, fiscal_identity)

    assert response.status_code == 200
    assert response.json() == {"granted": False, "points": []}


def test_the_endpoint_does_not_stamp_the_delegation(client, db, fiscal_identity, wsfe_returns):
    """Un GET no escribe, aunque acá la información para hacerlo esté a mano — ver el docstring
    de `verify-delegation`: un GET con efectos es algo que un prefetch puede repetir solo."""
    wsfe_returns(answer(pto_venta(5)))

    list_points(client, fiscal_identity)

    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_verified_at is None


def test_arca_being_unreachable_is_a_502(client, fiscal_identity, wsfe_returns):
    wsfe_returns(RequestsConnectionError("sin ruta al host"))

    assert list_points(client, fiscal_identity).status_code == 502


def test_the_points_of_sale_of_another_users_identity_are_a_404(
    client, db, other_user, wsfe_returns
):
    wsfe_returns(answer(pto_venta(5)))
    theirs = make_fiscal_identity(db, other_user.id)

    assert list_points(client, theirs).status_code == 404
