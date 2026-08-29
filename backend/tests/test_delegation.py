"""Verificación de la delegación: `services/wsfe.py` y `POST /{id}/verify-delegation`.

El SOAP está mockeado en el nivel más bajo que tiene sentido —`arca.build_client`— así que lo
que se ejercita de verdad es la lectura de la respuesta de WSFE, que es donde está la decisión
del proyecto: qué códigos son "no estás delegado", cuáles son "sí pero no tenés puntos de
venta" y cuáles son un error que no sabemos leer.

`arca.get_access_ticket` se parchea aparte porque abre su propia sesión contra la base real
—a propósito, para que un ticket recién emitido sobreviva al rollback del request— y en un
test de router eso escribiría filas fuera de la transacción del fixture.
"""

import logging
from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from zeep.exceptions import Fault

from factumov.exceptions import ArcaError, WsfeError
from factumov.routers.fiscal_identity import VERIFY_TICKET_MAX_AGE
from factumov.services import arca, wsfe
from factumov.services import email as email_service
from factumov.services.delegation_watch import RECHECK_TICKET_MAX_AGE
from tests.conftest import FALLBACK_DELEGATE_TAX_ID
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
        arca, "get_access_ticket",
        lambda service, max_age=None: arca.AccessTicket(token="tk", sign="sg"),
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


def test_verify_delegation_asks_with_a_fresh_ticket(
    client, fiscal_identity, wsfe_returns, monkeypatch
):
    """El click exige un ticket casi nuevo, mucho más que el barrido.

    Del otro lado del botón hay alguien que acaba de hacer el trámite en ARCA y quiere saber
    si quedó. Contestarle con la lista de relaciones que el TA congeló hace horas es
    responderle sobre un momento anterior al que está preguntando.
    """
    asked = []

    def get_access_ticket(service, max_age=None):
        asked.append(max_age)
        return arca.AccessTicket(token="tk", sign="sg")

    monkeypatch.setattr(arca, "get_access_ticket", get_access_ticket)
    wsfe_returns(NOT_DELEGATED)

    verify(client, fiscal_identity)

    assert asked == [VERIFY_TICKET_MAX_AGE]
    assert VERIFY_TICKET_MAX_AGE < RECHECK_TICKET_MAX_AGE


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


def test_verify_delegation_falls_back_when_there_is_no_certificate(
    client, fiscal_identity, wsfe_returns
):
    """Sin certificado en esta máquina contesta el `ARCA_DELEGATE_TAX_ID` configurado.

    La instrucción es el punto del endpoint: quedarse sin CUIT que nombrar la deja inútil.
    """
    wsfe_returns(NOT_DELEGATED)

    response = verify(client, fiscal_identity)

    assert response.status_code == 200
    assert response.json()["delegate_tax_id"] == FALLBACK_DELEGATE_TAX_ID


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


# --- El aviso del usuario y la revocación ----------------------------------------------
#
# Delegar tiene dos partes y la segunda es de FactuMov: el contribuyente designa, y después hay
# que aceptar esa designación a mano en ARCA. WSFE contesta el mismo código 600 antes y después
# de la designación, así que `delegation_claimed_at` es lo único que separa los dos estados —
# ver `models/fiscal_identity.py`.


def claim(client, fiscal_identity):
    return client.post(f"/fiscal-identities/{fiscal_identity.id}/claim-delegation")


def test_claiming_records_the_notice_when_arca_still_says_no(
    client, db, fiscal_identity, wsfe_returns
):
    wsfe_returns(NOT_DELEGATED)

    response = claim(client, fiscal_identity)

    assert response.status_code == 200
    assert response.json()["granted"] is False
    assert response.json()["delegation_claimed_at"] is not None
    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_claimed_at is not None


def test_claiming_verifies_first_and_records_nothing_when_it_already_works(
    client, db, fiscal_identity, wsfe_returns
):
    """El usuario pudo haber delegado en otra pestaña entre que cargó la pantalla y apretó.

    Anotar el aviso igual dispararía trabajo manual del operador para algo que ya funciona.
    """
    wsfe_returns(OK)

    response = claim(client, fiscal_identity)

    assert response.json()["granted"] is True
    assert response.json()["delegation_claimed_at"] is None
    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_claimed_at is None
    assert fiscal_identity.delegation_verified_at is not None


def test_the_first_notice_is_the_one_that_counts(client, db, fiscal_identity, wsfe_returns):
    """La fecha mide cuánto hace que esa persona espera. Pisarla con cada click la borraría."""
    wsfe_returns(NOT_DELEGATED)

    first = claim(client, fiscal_identity).json()["delegation_claimed_at"]
    second = claim(client, fiscal_identity).json()["delegation_claimed_at"]

    assert second == first


def test_verifying_does_not_record_a_notice(client, db, fiscal_identity, wsfe_returns):
    """El chequeo automático de la pantalla no puede afirmar nada en nombre del usuario."""
    wsfe_returns(NOT_DELEGATED)

    verify(client, fiscal_identity)

    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_claimed_at is None


def test_getting_verified_clears_the_notice(client, db, fiscal_identity, wsfe_returns):
    """El aviso existía para explicar una espera que ya terminó."""
    wsfe_returns(NOT_DELEGATED)
    claim(client, fiscal_identity)

    wsfe_returns(OK)
    response = verify(client, fiscal_identity)

    assert response.json()["delegation_claimed_at"] is None
    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_claimed_at is None


def test_a_revoked_delegation_stops_being_verified(client, db, fiscal_identity, wsfe_returns):
    """`delegation_verified_at` siempre dijo "esto era verdad en esta fecha".

    Esto es lo que le da consecuencias: cuando ARCA vuelve a decir que no, la identidad deja de
    poder emitir. Sin esto la app se enteraría recién con un rechazo al emitir.
    """
    wsfe_returns(OK)
    verify(client, fiscal_identity)
    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_verified_at is not None

    wsfe_returns(NOT_DELEGATED)
    response = verify(client, fiscal_identity)

    assert response.json()["granted"] is False
    assert response.json()["delegation_verified_at"] is None
    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_verified_at is None


def test_a_transient_arca_failure_does_not_unverify_anything(
    client, db, fiscal_identity, wsfe_returns
):
    """Solo el 600 desverifica. Un ARCA caído es un 502 y no toca la fila.

    Es la contracara del test de arriba, y es lo que hace que desverificar sea seguro: cualquier
    respuesta que no sea "no apareció el CUIT en la lista de relaciones" levanta excepción en
    `check_delegation` justamente para que una respuesta ambigua no le saque a nadie la
    posibilidad de emitir.
    """
    wsfe_returns(OK)
    verify(client, fiscal_identity)

    wsfe_returns(RequestsConnectionError("cortó"))
    assert verify(client, fiscal_identity).status_code == 502

    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_verified_at is not None


def test_claiming_on_someone_elses_identity_is_404(client, db, other_user, wsfe_returns):
    wsfe_returns(NOT_DELEGATED)
    ajena = make_fiscal_identity(db, user_id=other_user.id)

    assert claim(client, ajena).status_code == 404


def test_claiming_needs_a_session(anonymous_client, fiscal_identity, wsfe_returns):
    wsfe_returns(NOT_DELEGATED)

    assert claim(anonymous_client, fiscal_identity).status_code == 401


def test_claiming_shares_the_arca_budget_with_verifying(client, fiscal_identity, wsfe_returns):
    """Los dos salen a ARCA, y la cuota es del certificado: un presupuesto por endpoint dejaría
    gastar el doble alternando entre ellos."""
    from factumov.routers.fiscal_identity import _VERIFY_DELEGATION_LIMITER

    wsfe_returns(NOT_DELEGATED)
    for _ in range(_VERIFY_DELEGATION_LIMITER.limit):
        assert verify(client, fiscal_identity).status_code == 200

    assert claim(client, fiscal_identity).status_code == 429


# --- El aviso al operador --------------------------------------------------------------
#
# Es el único mail de la app que no le va a un usuario. Existe porque aceptar la designación es
# un click con Clave Fiscal que ARCA no expone por ningún web service: la app no puede
# enterarse sola de que alguien la está esperando, y el click del usuario es la única evidencia
# que va a existir nunca.


@pytest.fixture
def operator(monkeypatch):
    """Un `OPERATOR_EMAIL` configurado. Por default la suite no tiene, como la app."""
    monkeypatch.setenv("OPERATOR_EMAIL", "operador@factumov.com.ar")
    email_service.get_email_settings.cache_clear()
    yield "operador@factumov.com.ar"
    email_service.get_email_settings.cache_clear()


def test_claiming_mails_the_operator(client, fiscal_identity, wsfe_returns, operator, sent_emails):
    wsfe_returns(NOT_DELEGATED)

    claim(client, fiscal_identity)

    assert len(sent_emails) == 1
    assert sent_emails[0].to == operator
    assert fiscal_identity.tax_id in sent_emails[0].subject


def test_the_notice_names_who_is_waiting(
    client, fiscal_identity, user, wsfe_returns, operator, sent_emails
):
    """El operador tiene que poder encontrar la fila en ARCA y saber a quién está frenando."""
    wsfe_returns(NOT_DELEGATED)

    claim(client, fiscal_identity)

    body = sent_emails[0].body
    assert fiscal_identity.tax_id in body
    assert user.email in body
    assert "Aceptación de Designación" in body


def test_the_notice_asks_for_the_second_step_too(
    client, fiscal_identity, wsfe_returns, operator, sent_emails
):
    """Aceptar la designación **no alcanza**, y el mail que decía que sí costó una producción.

    La designación aceptada habilita a la persona; WSAA le emite el ticket al certificado, y la
    lista de relaciones que WSFE valida es la del certificado. Falta crear la relación que la
    aceptación no crea, con el computador como representante. Sin ese paso ARCA sigue
    contestando 600 —indistinguible de no haber hecho nada— y el operador se queda mirando una
    designación que dice "Aceptada: SI" mientras el usuario espera. Ver *Delegar tiene dos
    partes* en `docs/arca.md`.
    """
    wsfe_returns(NOT_DELEGATED)

    claim(client, fiscal_identity)

    body = sent_emails[0].body
    assert "Nueva Relación" in body
    assert "COMPUTADOR" in body
    # Que sea por cada CUIT es la mitad que hace que el trámite no se pueda dar por hecho.
    assert "por cada CUIT" in body


def test_only_the_first_claim_mails(client, fiscal_identity, wsfe_returns, operator, sent_emails):
    """Un usuario impaciente apretando el botón no puede convertirse en veinte mails."""
    wsfe_returns(NOT_DELEGATED)

    claim(client, fiscal_identity)
    claim(client, fiscal_identity)
    claim(client, fiscal_identity)

    assert len(sent_emails) == 1


def test_a_claim_that_verifies_mails_nobody(
    client, fiscal_identity, wsfe_returns, operator, sent_emails
):
    """No hay nada que aceptar: la delegación ya andaba cuando el usuario apretó."""
    wsfe_returns(OK)

    claim(client, fiscal_identity)

    assert sent_emails == []


def test_verifying_mails_nobody(client, fiscal_identity, wsfe_returns, operator, sent_emails):
    """El chequeo automático de la pantalla no puede generar trabajo manual del operador."""
    wsfe_returns(NOT_DELEGATED)

    verify(client, fiscal_identity)

    assert sent_emails == []


def test_without_an_operator_the_claim_still_works(
    client, db, fiscal_identity, wsfe_returns, sent_emails, caplog
):
    """No hay a quién avisarle, y eso no puede romperle el request al usuario.

    El aviso queda en el log, que es donde lo va a ver quien configura el `.env` — misma
    política que `send_email_best_effort`, un escalón antes.
    """
    wsfe_returns(NOT_DELEGATED)

    with caplog.at_level(logging.WARNING):
        response = claim(client, fiscal_identity)

    assert response.status_code == 200
    assert sent_emails == []
    db.refresh(fiscal_identity)
    assert fiscal_identity.delegation_claimed_at is not None
    assert fiscal_identity.tax_id in caplog.text
