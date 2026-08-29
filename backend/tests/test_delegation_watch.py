"""El barrido que reverifica las delegaciones pendientes de aceptación.

Existe por la asimetría de toda esta parte del proyecto: el usuario nos avisa que delegó, y
nadie nos avisa cuando la delegación empieza a funcionar. Aceptar la designación es un click
con Clave Fiscal en una página que ningún web service expone, así que no hay evento que
escuchar y lo único que se puede hacer es volver a preguntar.

Mismo montaje que `test_delegation.py`: el SOAP se mockea en `arca.build_client` y el ticket se
parchea aparte. Lo propio de este archivo es que el servicio abre **su propia sesión**, así que
hay que hacerle usar la del test — si no, escribiría contra la base real, fuera de la
transacción del fixture, y las filas quedarían.
"""

import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from factumov import database
from factumov.services import arca
from factumov.services.delegation_watch import (
    CLAIM_MAX_AGE_DAYS,
    RECHECK_TICKET_MAX_AGE,
    recheck_pending,
)
from tests.factories import make_fiscal_identity

OK = SimpleNamespace(Errors=None, ResultGet=SimpleNamespace(PtoVenta=[]))
NOT_DELEGATED = SimpleNamespace(
    Errors=SimpleNamespace(
        Err=[SimpleNamespace(Code=600, Msg="No apareció CUIT en lista de relaciones")]
    )
)


@pytest.fixture(autouse=True)
def ticket(monkeypatch):
    monkeypatch.setattr(
        arca, "get_access_ticket",
        lambda service, max_age=None: arca.AccessTicket(token="tk", sign="sg"),
    )


@pytest.fixture(autouse=True)
def watch_db(monkeypatch, db):
    """Hace que el barrido use la sesión del test — ver `arca_db` en `test_arca.py`."""

    @contextmanager
    def session_without_closing():
        yield db

    monkeypatch.setattr(database, "SessionLocal", session_without_closing)
    return db


@pytest.fixture
def arca_answers(monkeypatch):
    """Fija qué contesta `FEParamGetPtosVenta`, para todos o por CUIT."""

    def configure(default, by_tax_id=None):
        answers = by_tax_id or {}

        def operation(**kwargs):
            result = answers.get(kwargs["Auth"]["Cuit"], default)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(
            arca,
            "build_client",
            lambda url: SimpleNamespace(service=SimpleNamespace(FEParamGetPtosVenta=operation)),
        )

    return configure


def claimed(db, user_id, hours_ago=1, **kwargs):
    """Una identidad fiscal que avisó hace un rato y todavía no está verificada."""
    identity = make_fiscal_identity(db, user_id, **kwargs)
    identity.delegation_claimed_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    db.flush()
    return identity


def test_the_sweep_refuses_to_ask_with_a_stale_ticket(db, user, arca_answers, monkeypatch):
    """El barrido pide un ticket de menos de una hora, y no cualquiera que esté vigente.

    Es lo que separa un rechequeo de una repetición: el TA lleva la lista de relaciones
    congelada en el momento en que se emitió, así que preguntar veinte veces con el mismo
    ticket devuelve veinte veces la misma respuesta. Justo lo que el barrido está esperando
    —que alguien complete el trámite en ARCA— es lo que un ticket viejo no puede ver.
    """
    asked = []

    def get_access_ticket(service, max_age=None):
        asked.append(max_age)
        return arca.AccessTicket(token="tk", sign="sg")

    monkeypatch.setattr(arca, "get_access_ticket", get_access_ticket)
    claimed(db, user.id)
    arca_answers(NOT_DELEGATED)

    recheck_pending()

    assert asked == [RECHECK_TICKET_MAX_AGE]


def test_a_pending_delegation_that_now_works_gets_verified(db, user, arca_answers):
    identity = claimed(db, user.id)
    arca_answers(OK)

    assert recheck_pending() == 1

    db.refresh(identity)
    assert identity.delegation_verified_at is not None
    assert identity.delegation_claimed_at is None


def test_the_user_is_told_it_is_ready(db, user, arca_answers, sent_emails):
    """Es el "ya está" de la única espera que el usuario no puede resolver ni observar."""
    identity = claimed(db, user.id)
    arca_answers(OK)

    recheck_pending()

    assert len(sent_emails) == 1
    assert sent_emails[0].to == user.email
    assert identity.tax_id in sent_emails[0].subject


def test_a_delegation_that_still_does_not_work_is_left_alone(db, user, arca_answers, sent_emails):
    identity = claimed(db, user.id)
    arca_answers(NOT_DELEGATED)

    assert recheck_pending() == 0

    db.refresh(identity)
    assert identity.delegation_verified_at is None
    assert identity.delegation_claimed_at is not None
    assert sent_emails == []


def test_an_identity_that_never_claimed_is_not_swept(db, user, arca_answers):
    """Barrer todo sería multiplicar por N una cuota de ARCA que es de todos los usuarios."""
    identity = make_fiscal_identity(db, user.id)
    arca_answers(OK)

    assert recheck_pending() == 0

    db.refresh(identity)
    assert identity.delegation_verified_at is None


def test_an_already_verified_identity_is_not_swept(db, user, arca_answers):
    """La revocación la detecta la pantalla al abrir, que es cuando a alguien le importa."""
    identity = make_fiscal_identity(db, user.id)
    identity.delegation_verified_at = datetime.now(UTC)
    db.flush()
    arca_answers(NOT_DELEGATED)

    assert recheck_pending() == 0

    db.refresh(identity)
    assert identity.delegation_verified_at is not None


def test_a_stale_claim_stops_being_rechecked(db, user, arca_answers):
    """Un aviso de hace un mes que sigue sin verificar no se arregla preguntando para siempre.

    La pantalla lo sigue rechequeando al abrir, así que el usuario no queda sin salida.
    """
    identity = claimed(db, user.id, hours_ago=24 * (CLAIM_MAX_AGE_DAYS + 1))
    arca_answers(OK)

    assert recheck_pending() == 0

    db.refresh(identity)
    assert identity.delegation_verified_at is None


def test_a_deactivated_user_is_not_swept(db, user, arca_answers, sent_emails):
    """Gastar ARCA para mandarle un mail a una cuenta dada de baja no le sirve a nadie."""
    identity = claimed(db, user.id)
    user.is_active = False
    db.flush()
    arca_answers(OK)

    assert recheck_pending() == 0
    assert sent_emails == []
    db.refresh(identity)
    assert identity.delegation_verified_at is None


def test_one_failure_does_not_stop_the_others(db, user, arca_answers, caplog):
    """ARCA homologación corta conexiones cada tanto — ver CLAUDE.md, *Los 502 son
    transitorios*. La que falla se reintenta en el próximo barrido; las demás no esperan."""
    broken = claimed(db, user.id, name="Rota", tax_id="20111111112")
    fine = claimed(db, user.id, name="Sana", tax_id="30500010912")
    arca_answers(OK, by_tax_id={broken.tax_id: RequestsConnectionError("cortó")})

    with caplog.at_level(logging.ERROR):
        assert recheck_pending() == 1

    db.refresh(broken)
    db.refresh(fine)
    assert broken.delegation_verified_at is None
    assert fine.delegation_verified_at is not None
    assert broken.tax_id in caplog.text


def test_another_users_pending_delegation_is_swept_too(db, user, other_user, arca_answers):
    """El barrido no tiene sesión: no está scopeado a nadie, y no debe estarlo.

    Es lo contrario de todos los endpoints. Acá el que consulta es el sistema, y lo que se barre
    son todas las esperas que existan, sean de quien sean.
    """
    mine = claimed(db, user.id, name="Mía", tax_id="20111111112")
    theirs = claimed(db, other_user.id, name="Suya", tax_id="30500010912")
    arca_answers(OK)

    assert recheck_pending() == 2

    db.refresh(mine)
    db.refresh(theirs)
    assert mine.delegation_verified_at is not None
    assert theirs.delegation_verified_at is not None


def test_a_dead_mail_does_not_undo_the_verification(db, user, arca_answers, broken_mail):
    """El mail acompaña algo ya guardado: el usuario se entera igual al abrir la pantalla."""
    identity = claimed(db, user.id)
    arca_answers(OK)

    assert recheck_pending() == 1

    db.refresh(identity)
    assert identity.delegation_verified_at is not None


def test_nothing_pending_calls_nobody(db, user, monkeypatch):
    """El caso normal es que no haya nada que barrer, y ahí no se toca ARCA."""
    make_fiscal_identity(db, user.id)

    def explode(url):
        raise AssertionError("el barrido salió a ARCA sin nada pendiente")

    monkeypatch.setattr(arca, "build_client", explode)

    assert recheck_pending() == 0
