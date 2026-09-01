"""Emitir con CAE: `services/wsfe.authorize_invoice` y `POST /{id}/emit`.

Mismo montaje que `test_delegation.py`: el SOAP se mockea en `arca.build_client`, que es el
nivel más bajo con sentido, así se ejercita de verdad el armado del request y la lectura de
la respuesta — que es donde están todas las decisiones. `arca.get_access_ticket` se parchea
aparte porque abre su propia sesión contra la base real.

**Ningún test de este archivo emite nada.** Es lo único que hay que tener presente al
tocarlo: si un día alguno llegara a `build_client` de verdad, con un certificado real en el
`.env`, estaría dando de alta un comprobante con validez legal. Por eso el fixture del
cliente SOAP es autouse y falla ruidosamente si alguien llama a una operación que no
configuró.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from sqlalchemy import select
from zeep.exceptions import Fault

from factumov import database
from factumov.enums import (
    Balance360Status,
    Concepto,
    CondicionIva,
    DocType,
    IvaAliquot,
    VoucherType,
)
from factumov.exceptions import ArcaError, WsfeError
from factumov.models.invoice import Invoice
from factumov.services import arca, wsfe
from factumov.services.invoice_totals import LineAmounts, compute_totals
from tests.factories import (
    make_customer,
    make_fiscal_identity,
    make_invoice_template,
)

AUTHORIZED = SimpleNamespace(
    Errors=None,
    FeDetResp=SimpleNamespace(
        FECAEDetResponse=[
            SimpleNamespace(Resultado="A", CAE="75123456789012", CAEFchVto="20260906")
        ]
    ),
)


def rejected(code=10016, message="El numero de comprobante ya fue registrado"):
    """ARCA aceptó el request pero no autorizó el comprobante: el motivo va en Observaciones."""
    return SimpleNamespace(
        Errors=None,
        FeDetResp=SimpleNamespace(
            FECAEDetResponse=[
                SimpleNamespace(
                    Resultado="R",
                    Observaciones=SimpleNamespace(Obs=[SimpleNamespace(Code=code, Msg=message)]),
                )
            ]
        ),
    )


@pytest.fixture(autouse=True)
def ticket(monkeypatch):
    """Un TA ya emitido, sin tocar la base ni la red."""
    monkeypatch.setattr(
        arca, "get_access_ticket",
        lambda service, max_age=None: arca.AccessTicket(token="tk", sign="sg"),
    )


@pytest.fixture
def wsfe_calls(monkeypatch):
    """Mockea las dos operaciones de emisión y devuelve lo que se les mandó.

    `FECompUltimoAutorizado` contesta siempre el mismo último número salvo que el test lo
    cambie —y sin fecha, que es el punto de venta que todavía no fija ningún piso—;
    `FECAESolicitar` contesta lo que el test configure. Las llamadas quedan
    registradas porque la mitad de lo que hay que probar acá es **qué se le manda a ARCA**,
    no solo qué se hace con lo que contesta.
    """
    state = {"last_number": 41, "last_date": None, "response": AUTHORIZED}
    calls: dict[str, list] = {"last": [], "cae": []}

    def last_authorized(**kwargs):
        calls["last"].append(kwargs)
        return SimpleNamespace(
            Errors=None, CbteNro=state["last_number"], CbteFch=state["last_date"]
        )

    def request_cae(**kwargs):
        calls["cae"].append(kwargs)
        response = state["response"]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(
        arca,
        "build_client",
        lambda url: SimpleNamespace(
            service=SimpleNamespace(
                FECompUltimoAutorizado=last_authorized, FECAESolicitar=request_cae
            )
        ),
    )
    return SimpleNamespace(calls=calls, state=state)


def voucher_request(voucher_type=VoucherType.B, concepto=Concepto.products, **overrides):
    totals = compute_totals(
        voucher_type, [LineAmounts(Decimal("1"), Decimal("121"), IvaAliquot.standard)]
    )
    fields = {
        "issuer_tax_id": "20182810674",
        "pos": 1,
        "voucher_type": voucher_type,
        "date": date(2026, 8, 27),
        "concepto": concepto,
        "customer_doc_type": DocType.CUIT,
        "customer_doc_number": "30500010912",
        "customer_condicion_iva": CondicionIva.INSCRIPTO.value,
        "totals": totals,
    }
    fields.update(overrides)
    return wsfe.VoucherRequest(**fields)


# --- Lo que se le manda a ARCA -------------------------------------------------------------


def test_the_number_is_the_last_authorized_plus_one(wsfe_calls):
    result = wsfe.authorize_invoice(voucher_request())

    assert result.number == 42
    assert (
        wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0]["CbteDesde"] == 42
    )


def test_the_first_invoice_of_a_new_pos_is_number_one(wsfe_calls):
    """ARCA contesta `CbteNro = 0` para un punto de venta sin comprobantes."""
    wsfe_calls.state["last_number"] = 0

    assert wsfe.authorize_invoice(voucher_request()).number == 1


def test_the_auth_cuit_is_the_represented_taxpayer(wsfe_calls):
    """La brecha entre el CUIT del certificado y el del `Auth` *es* la delegación."""
    wsfe.authorize_invoice(voucher_request(issuer_tax_id="27177624441"))

    assert wsfe_calls.calls["cae"][0]["Auth"]["Cuit"] == "27177624441"
    assert wsfe_calls.calls["last"][0]["Auth"]["Cuit"] == "27177624441"


@pytest.mark.parametrize(
    ("voucher_type", "code"),
    [(VoucherType.A, 1), (VoucherType.B, 6), (VoucherType.C, 11)],
    ids=lambda value: str(value),
)
def test_the_voucher_type_travels_as_the_arca_code(wsfe_calls, voucher_type, code):
    wsfe.authorize_invoice(voucher_request(voucher_type=voucher_type))

    assert wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeCabReq"]["CbteTipo"] == code
    assert wsfe_calls.calls["last"][0]["CbteTipo"] == code


def test_an_a_sends_the_iva_breakdown(wsfe_calls):
    wsfe.authorize_invoice(voucher_request(voucher_type=VoucherType.A))

    detail = wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0]
    assert detail["Iva"]["AlicIva"] == [
        {"Id": IvaAliquot.standard.value, "BaseImp": Decimal("121.00"), "Importe": Decimal("25.41")}
    ]


def test_a_c_sends_no_iva_at_all(wsfe_calls):
    """Mandar `Iva` en una C —aunque sea con alícuota 0— es un rechazo de ARCA."""
    wsfe.authorize_invoice(voucher_request(voucher_type=VoucherType.C))

    detail = wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0]
    assert "Iva" not in detail
    assert detail["ImpIVA"] == Decimal("0")
    assert detail["ImpNeto"] == detail["ImpTotal"]


def test_the_amounts_add_up_the_way_arca_checks(wsfe_calls):
    wsfe.authorize_invoice(voucher_request())

    detail = wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0]
    assert detail["ImpTotal"] == (
        detail["ImpNeto"]
        + detail["ImpIVA"]
        + detail["ImpTrib"]
        + detail["ImpOpEx"]
        + detail["ImpTotConc"]
    )


def test_products_send_no_service_dates(wsfe_calls):
    wsfe.authorize_invoice(voucher_request(concepto=Concepto.products))

    detail = wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0]
    assert "FchServDesde" not in detail


def test_services_send_the_three_dates(wsfe_calls):
    wsfe.authorize_invoice(
        voucher_request(
            concepto=Concepto.services,
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 31),
            due_date=date(2026, 9, 10),
        )
    )

    detail = wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0]
    assert detail["FchServDesde"] == "20260801"
    assert detail["FchServHasta"] == "20260831"
    assert detail["FchVtoPago"] == "20260910"


def test_services_without_dates_is_our_bug_and_says_so(wsfe_calls):
    """El schema del endpoint lo garantiza antes; llegar acá sin fechas sería un bug nuestro."""
    with pytest.raises(WsfeError, match="período"):
        wsfe.authorize_invoice(voucher_request(concepto=Concepto.services))


# --- Lo que se lee de la respuesta ---------------------------------------------------------


def test_the_cae_and_its_expiry_come_back_parsed(wsfe_calls):
    result = wsfe.authorize_invoice(voucher_request())

    assert result.cae == "75123456789012"
    assert result.cae_expiry == date(2026, 9, 6)


def test_an_errors_block_raises(wsfe_calls):
    wsfe_calls.state["response"] = SimpleNamespace(
        Errors=SimpleNamespace(Err=[SimpleNamespace(Code=600, Msg="No autorizado")])
    )

    with pytest.raises(WsfeError, match="600"):
        wsfe.authorize_invoice(voucher_request())


def test_a_rejected_voucher_raises_with_the_observation(wsfe_calls):
    """El otro "no" de ARCA: aceptó el request y no autorizó el comprobante."""
    wsfe_calls.state["response"] = rejected()

    with pytest.raises(WsfeError, match="10016"):
        wsfe.authorize_invoice(voucher_request())


def test_a_soap_fault_raises_wsfe_error(wsfe_calls):
    wsfe_calls.state["response"] = Fault("algo se rompió")

    with pytest.raises(WsfeError):
        wsfe.authorize_invoice(voucher_request())


def test_a_connection_problem_raises_arca_error(wsfe_calls):
    """ARCA homologación corta conexiones cada tanto — ver CLAUDE.md → *Los 502 son
    transitorios*."""
    wsfe_calls.state["response"] = RequestsConnectionError("cortó")

    with pytest.raises(ArcaError):
        wsfe.authorize_invoice(voucher_request())


# --- El endpoint ---------------------------------------------------------------------------


@pytest.fixture
def delegated_identity(db, user):
    """Una identidad fiscal con la delegación ya verificada: el caso normal de emisión."""
    identity = make_fiscal_identity(db, user.id, tax_id="20182810674")
    identity.delegation_verified_at = datetime.now(UTC)
    db.flush()
    return identity


@pytest.fixture
def template(db, user, delegated_identity):
    """Inscripto → exento, o sea una factura B, que es el caso más común de las muestras.

    Exento y no monotributista: desde la Ley 27.618 ese par emite A, y acá conviene ejercitar
    la B — es la letra que lleva el desglose de IVA sin discriminarlo en el impreso, o sea la
    que más partes tiene que salir bien.
    """
    customer = make_customer(db, user.id, condicion_iva=CondicionIva.EXENTO)
    return make_invoice_template(db, delegated_identity, customer, lines=[(0, "Alquiler")])


def emit(client, template_id, **body):
    return client.post(f"/invoice-templates/{template_id}/emit", json=body)


def test_emit_returns_the_invoice_with_its_number_and_cae(client, template, wsfe_calls):
    response = emit(client, template.id)

    assert response.status_code == 201
    body = response.json()
    assert body["number"] == 42
    assert body["cae"] == "75123456789012"
    assert body["label"] == "B-00001-00000042"


def test_emit_saves_the_invoice(client, template, db, wsfe_calls):
    emit(client, template.id)

    invoices = db.execute(select(Invoice)).scalars().all()
    assert len(invoices) == 1
    assert invoices[0].template_id == template.id


def test_the_saved_invoice_copies_the_parties(client, template, db, wsfe_calls):
    """Sin la copia, que el cliente cambie de domicilio reescribe facturas ya emitidas."""
    emit(client, template.id)

    invoice = db.execute(select(Invoice)).scalars().one()
    assert invoice.customer_name == template.customer.name
    assert invoice.customer_doc_number == template.customer.doc_number
    assert invoice.issuer_tax_id == "20182810674"


def test_editing_the_customer_afterwards_does_not_change_the_invoice(
    client, template, db, wsfe_calls
):
    emit(client, template.id)
    template.customer.name = "Otro nombre"
    template.customer.address = "Otra calle 123"
    db.flush()

    invoice = db.execute(select(Invoice)).scalars().one()
    db.refresh(invoice)
    assert invoice.customer_name != "Otro nombre"


def test_the_saved_amounts_are_the_ones_sent_to_arca(client, template, db, wsfe_calls):
    emit(client, template.id)

    invoice = db.execute(select(Invoice)).scalars().one()
    detail = wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0]
    assert invoice.total == detail["ImpTotal"]
    assert invoice.net_total == detail["ImpNeto"]
    assert invoice.iva_total == detail["ImpIVA"]


def test_the_letter_is_the_one_derived_from_the_two_iva_conditions(
    client, template, db, wsfe_calls
):
    """Inscripto → monotributista es B. La letra se deduce al emitir y se congela ahí."""
    emit(client, template.id)

    invoice = db.execute(select(Invoice)).scalars().one()
    assert invoice.voucher_type is VoucherType.B


def test_emit_without_a_verified_delegation_answers_409(client, db, user, wsfe_calls):
    identity = make_fiscal_identity(db, user.id)
    customer = make_customer(db, user.id)
    unverified = make_invoice_template(db, identity, customer)

    response = emit(client, unverified.id)

    assert response.status_code == 409
    assert "delegación" in response.json()["detail"]


def test_a_blocked_emission_calls_nobody(client, db, user, wsfe_calls):
    """El chequeo va antes de salir a la red: no se le pide un CAE a ARCA para que lo rechace."""
    identity = make_fiscal_identity(db, user.id)
    customer = make_customer(db, user.id)
    unverified = make_invoice_template(db, identity, customer)

    emit(client, unverified.id)

    assert wsfe_calls.calls["cae"] == []


def test_emit_answers_502_when_arca_does_not_answer(client, template, wsfe_calls):
    wsfe_calls.state["response"] = RequestsConnectionError("cortó")

    response = emit(client, template.id)

    assert response.status_code == 502


def test_a_failed_emission_saves_nothing(client, template, db, wsfe_calls):
    wsfe_calls.state["response"] = rejected()

    emit(client, template.id)

    assert db.execute(select(Invoice)).scalars().all() == []


def test_a_services_template_needs_the_period(client, db, user, delegated_identity, wsfe_calls):
    customer = make_customer(db, user.id)
    services = make_invoice_template(db, delegated_identity, customer, concepto=Concepto.services)

    response = emit(client, services.id)

    assert response.status_code == 422


def test_a_services_template_emits_with_the_period(
    client, db, user, delegated_identity, wsfe_calls
):
    customer = make_customer(db, user.id)
    services = make_invoice_template(db, delegated_identity, customer, concepto=Concepto.services)

    response = emit(
        client,
        services.id,
        from_date="2026-08-01",
        to_date="2026-08-31",
        due_date="2026-09-10",
    )

    assert response.status_code == 201


def test_half_a_period_is_rejected_by_the_schema(client, template, wsfe_calls):
    """Mandar solo `from_date` es un formulario a medio llenar, no un rechazo de ARCA."""
    response = emit(client, template.id, from_date="2026-08-01")

    assert response.status_code == 422


def test_a_period_that_ends_before_it_starts_is_rejected(client, template, wsfe_calls):
    response = emit(
        client, template.id, from_date="2026-08-31", to_date="2026-08-01", due_date="2026-09-10"
    )

    assert response.status_code == 422


# --- La fecha del comprobante --------------------------------------------------------------
#
# Tres límites, de tres fuentes distintas: el default es hoy, la ventana alrededor de hoy la
# fija el concepto (±5 productos, ±10 servicios), y el piso lo fija el último comprobante
# autorizado de la serie, que solo ARCA conoce.


def test_without_a_date_the_invoice_is_dated_today(client, template, db, wsfe_calls):
    emit(client, template.id)

    assert db.execute(select(Invoice)).scalars().one().date == date.today()


def test_the_chosen_date_is_the_one_saved_and_the_one_declared(client, template, db, wsfe_calls):
    chosen = date.today() - timedelta(days=3)

    emit(client, template.id, date=chosen.isoformat())

    invoice = db.execute(select(Invoice)).scalars().one()
    assert invoice.date == chosen
    detail = wsfe_calls.calls["cae"][0]["FeCAEReq"]["FeDetReq"]["FECAEDetRequest"][0]
    assert detail["CbteFch"] == chosen.strftime("%Y%m%d")


@pytest.mark.parametrize("offset", [-5, 5])
def test_the_edges_of_the_products_window_are_accepted(client, template, wsfe_calls, offset):
    response = emit(client, template.id, date=(date.today() + timedelta(days=offset)).isoformat())

    assert response.status_code == 201


@pytest.mark.parametrize("offset", [-6, 6])
def test_a_date_outside_the_products_window_is_a_422(client, template, wsfe_calls, offset):
    response = emit(client, template.id, date=(date.today() + timedelta(days=offset)).isoformat())

    assert response.status_code == 422
    assert "ARCA solo acepta" in response.json()["detail"]


def test_a_date_outside_the_window_calls_nobody(client, template, wsfe_calls):
    """Un error del request tiene que morir antes de pedirle un CAE a ARCA para que lo rechace."""
    emit(client, template.id, date=(date.today() + timedelta(days=30)).isoformat())

    assert wsfe_calls.calls["cae"] == []


def test_services_get_the_wider_window(client, db, user, delegated_identity, wsfe_calls):
    """±10 días y no ±5: la ventana la fija el concepto, no la letra."""
    customer = make_customer(db, user.id)
    services = make_invoice_template(db, delegated_identity, customer, concepto=Concepto.services)

    response = emit(
        client,
        services.id,
        date=(date.today() - timedelta(days=9)).isoformat(),
        from_date="2026-08-01",
        to_date="2026-08-31",
        due_date="2026-09-10",
    )

    assert response.status_code == 201


def test_the_numbering_cannot_go_back_in_time(client, template, wsfe_calls):
    """ARCA rechaza con el 10016, que no dice cuál era la fecha del último. Este 422 sí."""
    wsfe_calls.state["last_date"] = date.today().strftime("%Y%m%d")

    response = emit(client, template.id, date=(date.today() - timedelta(days=1)).isoformat())

    assert response.status_code == 422
    assert date.today().strftime("%d/%m/%Y") in response.json()["detail"]
    assert wsfe_calls.calls["cae"] == []


def test_the_same_date_as_the_last_voucher_is_fine(client, template, wsfe_calls):
    """El piso es "no anterior", no "posterior": varias facturas del mismo día es lo normal."""
    wsfe_calls.state["last_date"] = date.today().strftime("%Y%m%d")

    assert emit(client, template.id, date=date.today().isoformat()).status_code == 201


def test_a_new_pos_has_no_floor(client, template, wsfe_calls):
    """`CbteNro = 0` y sin fecha: no hay ningún comprobante anterior que respetar."""
    wsfe_calls.state["last_number"] = 0
    wsfe_calls.state["last_date"] = None

    assert (
        emit(client, template.id, date=(date.today() - timedelta(days=5)).isoformat()).status_code
        == 201
    )


def test_the_preview_says_which_dates_are_allowed(client, template):
    """La pantalla no puede ofrecer una fecha que el servidor va a rechazar, así que los
    extremos los calcula el backend con la misma función que después valida."""
    body = client.get(f"/invoice-templates/{template.id}/preview").json()

    assert body["date"] == date.today().isoformat()
    assert body["min_date"] == (date.today() - timedelta(days=5)).isoformat()
    assert body["max_date"] == (date.today() + timedelta(days=5)).isoformat()


def test_emitting_someone_elses_template_is_a_404(client, db, other_user, wsfe_calls):
    identity = make_fiscal_identity(db, other_user.id)
    customer = make_customer(db, other_user.id)
    theirs = make_invoice_template(db, identity, customer)

    assert emit(client, theirs.id).status_code == 404


# --- La vista previa -----------------------------------------------------------------------


def test_the_preview_says_what_would_be_emitted(client, template):
    response = client.get(f"/invoice-templates/{template.id}/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["voucher_type"] == "B"
    assert body["customer_name"] == template.customer.name
    assert body["blocked_reason"] is None


def test_the_preview_emits_nothing(client, template, db, wsfe_calls):
    client.get(f"/invoice-templates/{template.id}/preview")

    assert db.execute(select(Invoice)).scalars().all() == []
    assert wsfe_calls.calls["cae"] == []


def test_the_preview_warns_before_the_button_fails(client, db, user):
    """Que falte la delegación se dice en la pantalla de confirmación, no después de apretar."""
    identity = make_fiscal_identity(db, user.id)
    customer = make_customer(db, user.id)
    unverified = make_invoice_template(db, identity, customer)

    body = client.get(f"/invoice-templates/{unverified.id}/preview").json()

    assert body["blocked_reason"] is not None


def test_the_preview_totals_match_what_gets_emitted(client, template, db, wsfe_calls):
    """Las dos cuentas salen de la misma función; este test fija que sigan saliendo de ahí."""
    preview = client.get(f"/invoice-templates/{template.id}/preview").json()

    emit(client, template.id)

    invoice = db.execute(select(Invoice)).scalars().one()
    assert Decimal(preview["total"]) == invoice.total


# --- Listado -------------------------------------------------------------------------------


def test_the_emitted_invoice_shows_up_in_the_list(client, template, wsfe_calls):
    emit(client, template.id)

    response = client.get("/invoices")

    assert response.status_code == 200
    assert [invoice["label"] for invoice in response.json()] == ["B-00001-00000042"]


def test_invoices_of_another_user_are_invisible(client, db, other_user, wsfe_calls):
    identity = make_fiscal_identity(db, other_user.id)
    identity.delegation_verified_at = datetime.now(UTC)
    customer = make_customer(db, other_user.id)
    theirs = make_invoice_template(db, identity, customer)
    db.flush()
    db.add(
        Invoice(
            fiscal_identity_id=identity.id,
            customer_id=customer.id,
            template_id=theirs.id,
            voucher_type=VoucherType.B,
            pos=1,
            number=1,
            date=date.today(),
            concepto=Concepto.products,
            cae="1",
            cae_expiry=date.today() + timedelta(days=10),
            net_total=Decimal("1"),
            iva_total=Decimal("0"),
            total=Decimal("1"),
            issuer_name=identity.name,
            issuer_tax_id=identity.tax_id,
            issuer_condicion_iva=identity.condicion_iva,
            customer_name=customer.name,
            customer_doc_type=customer.doc_type,
            customer_doc_number=customer.doc_number,
            customer_condicion_iva=customer.condicion_iva,
        )
    )
    db.flush()

    assert client.get("/invoices").json() == []


def test_an_invoice_cannot_be_edited_or_deleted(client, template, wsfe_calls):
    """La ausencia de esos verbos es la decisión: una factura emitida no se corrige."""
    invoice_id = emit(client, template.id).json()["id"]

    assert client.delete(f"/invoices/{invoice_id}").status_code == 405
    assert client.patch(f"/invoices/{invoice_id}", json={}).status_code == 405


def test_a_customer_with_invoices_cannot_be_deleted(client, template, wsfe_calls):
    """La factura copió su nombre, pero la fila igual se queda: es el respaldo de un
    comprobante que existe en ARCA."""
    emit(client, template.id)

    assert client.delete(f"/customers/{template.customer_id}").status_code == 409


# --- Mandar la factura por mail ------------------------------------------------------------
#
# Reenviar es legítimo y frecuente —"no me llegó"— así que estos tests no protegen ninguna
# guarda contra el segundo envío: no hay. Es lo contrario de `/emit`, donde repetir crea un
# comprobante nuevo.


@pytest.fixture
def emitted(client, template, db, wsfe_calls):
    """Una factura ya emitida, con el cliente que tiene mail cargado."""
    template.customer.email = "cliente@cucu.com"
    db.flush()
    return emit(client, template.id).json()


def test_send_mails_the_invoice_with_the_pdf_attached(client, emitted, sent_emails):
    response = client.post(f"/invoices/{emitted['id']}/send")

    assert response.status_code == 200
    assert len(sent_emails) == 1
    assert sent_emails[0].to == "cliente@cucu.com"
    attachment = sent_emails[0].attachments[0]
    assert attachment.filename == "FactuMov-B-00001-00000042.pdf"
    assert attachment.content.startswith(b"%PDF-")


def test_send_copies_the_customers_cc_addresses(client, template, db, wsfe_calls, sent_emails):
    """El CC sale de la ficha del cliente y se lee en vivo, como el destinatario principal."""
    template.customer.email = "cliente@cucu.com"
    template.customer.cc_emails = ["contador@cucu.com", "gestor@cucu.com"]
    db.flush()
    invoice = emit(client, template.id).json()

    assert invoice["customer_cc_emails"] == ["contador@cucu.com", "gestor@cucu.com"]

    client.post(f"/invoices/{invoice['id']}/send")

    assert sent_emails[0].to == "cliente@cucu.com"
    assert sent_emails[0].cc == ["contador@cucu.com", "gestor@cucu.com"]
    # El CC no se congela en la factura: `sent_to` sigue siendo solo el To.
    assert client.get(f"/invoices/{invoice['id']}").json()["sent_to"] == "cliente@cucu.com"


def test_send_leaves_the_primary_address_out_of_the_cc(
    client, template, db, wsfe_calls, sent_emails
):
    """Aunque el mail principal haya cambiado después de cargar el CC, no llega dos veces."""
    template.customer.email = "cliente@cucu.com"
    # Se guarda directo en el modelo para saltear la limpieza del schema y simular el caso
    # en que el mail del To cambió más tarde.
    template.customer.cc_emails = ["cliente@cucu.com", "contador@cucu.com"]
    db.flush()
    invoice = emit(client, template.id).json()

    client.post(f"/invoices/{invoice['id']}/send")

    assert sent_emails[0].cc == ["contador@cucu.com"]


def test_a_customer_without_cc_sends_a_plain_mail(client, emitted, sent_emails):
    client.post(f"/invoices/{emitted['id']}/send")

    assert sent_emails[0].cc == []


def test_the_subject_names_the_voucher_and_the_issuer(client, emitted, sent_emails):
    """Es lo que el destinatario ve en su lista de correo; "Factura" a secas no dice de quién."""
    client.post(f"/invoices/{emitted['id']}/send")

    assert emitted["label"] in sent_emails[0].subject
    assert emitted["issuer_name"] in sent_emails[0].subject


# --- El texto propio del modelo ---
#
# El asunto y el cuerpo se leen del modelo del que salió la factura, en vivo y no copiados al
# emitir: es la misma decisión que el mail del cliente, y por el mismo motivo — a quién y qué
# decirle son preguntas sobre el envío que se está por hacer, no hechos que ARCA autorizó.


@pytest.fixture
def own_text(db, template):
    """El modelo con asunto y cuerpo propios, escritos por el usuario."""
    template.email_subject = "Tu factura de agosto"
    template.email_body = "Hola Ana! Te mando la factura del mes. Gracias!"
    db.flush()
    return template


def test_send_uses_the_templates_own_text(client, own_text, emitted, sent_emails):
    client.post(f"/invoices/{emitted['id']}/send")

    assert sent_emails[0].subject == "Tu factura de agosto"
    assert sent_emails[0].body == "Hola Ana! Te mando la factura del mes. Gracias!"


def test_the_own_text_still_carries_the_pdf(client, own_text, emitted, sent_emails):
    """El texto acompaña al comprobante, no lo reemplaza."""
    client.post(f"/invoices/{emitted['id']}/send")

    assert sent_emails[0].attachments[0].content.startswith(b"%PDF-")


def test_only_the_half_that_was_written_replaces_the_default(
    client, template, db, emitted, sent_emails
):
    """Caen en el default por separado: el que solo cambió el cuerpo conserva el asunto."""
    template.email_body = "Hola! Ahí va."
    db.flush()

    client.post(f"/invoices/{emitted['id']}/send")

    assert sent_emails[0].body == "Hola! Ahí va."
    assert sent_emails[0].subject == f"Factura {emitted['label']} de {emitted['issuer_name']}"


def test_editing_the_text_afterwards_changes_the_resend(
    client, own_text, db, emitted, sent_emails
):
    """Se lee en vivo: corregir el modelo arregla también los reenvíos de lo ya emitido."""
    client.post(f"/invoices/{emitted['id']}/send")
    own_text.email_body = "Corregido"
    db.flush()

    client.post(f"/invoices/{emitted['id']}/send")

    assert [mail.body for mail in sent_emails] == [
        "Hola Ana! Te mando la factura del mes. Gracias!",
        "Corregido",
    ]


def test_deleting_the_template_falls_back_to_the_default_text(
    client, own_text, db, emitted, sent_emails
):
    """`template_id` es SET NULL: el texto se fue con el modelo y no hay dónde buscarlo.

    Es el precio de leerlo en vivo en vez de copiarlo al emitir, y el mismo que ya se paga con
    el mail del cliente. Lo que no puede pasar es que el envío falle por eso.
    """
    assert client.delete(f"/invoice-templates/{own_text.id}").status_code == 204

    response = client.post(f"/invoices/{emitted['id']}/send")

    assert response.status_code == 200
    assert sent_emails[0].subject == f"Factura {emitted['label']} de {emitted['issuer_name']}"


def test_a_free_account_gets_the_default_text(
    client, own_text, emitted, sent_emails, free_plan
):
    """El texto queda guardado y deja de usarse; lo que sale es el de FactuMov.

    Es lo que distingue este límite del de las identidades fiscales, donde el ex-Pro conserva
    las tres que cargó **y las sigue usando**: acá dejar de usar el texto propio no impide
    nada, manda el otro.
    """
    client.post(f"/invoices/{emitted['id']}/send")

    assert sent_emails[0].subject == f"Factura {emitted['label']} de {emitted['issuer_name']}"
    assert "Te adjuntamos la factura" in sent_emails[0].body


def test_send_records_when_it_went_out(client, emitted):
    assert emitted["sent_at"] is None

    response = client.post(f"/invoices/{emitted['id']}/send")

    assert response.json()["sent_at"] is not None


def test_resending_is_allowed_and_overwrites_the_mark(client, emitted, sent_emails):
    """El cliente dice que no le llegó y se lo manda de nuevo. No hay guarda que lo impida."""
    first = client.post(f"/invoices/{emitted['id']}/send").json()["sent_at"]
    second = client.post(f"/invoices/{emitted['id']}/send").json()["sent_at"]

    assert len(sent_emails) == 2
    assert second >= first


def test_a_customer_without_email_answers_409(client, template, db, wsfe_calls, sent_emails):
    template.customer.email = None
    db.flush()
    invoice = emit(client, template.id).json()

    response = client.post(f"/invoices/{invoice['id']}/send")

    assert response.status_code == 409
    assert "email" in response.json()["detail"]
    assert sent_emails == []


def test_loading_the_email_afterwards_makes_the_invoice_sendable(
    client, template, db, wsfe_calls, sent_emails
):
    """El bug que motivó separar `customer_email` de `sent_to`.

    Con el mail copiado al emitir, una factura emitida antes de que el cliente tuviera
    dirección se quedaba sin dirección para siempre: cargarla en la ficha no cambiaba nada, la
    pantalla seguía diciendo "este cliente no tiene email", y la factura tampoco se puede
    editar. Un callejón sin salida cuya única salida era emitir de nuevo — o sea la única
    equivocación cara que se puede cometer en esta app.
    """
    template.customer.email = None
    db.flush()
    invoice = emit(client, template.id).json()
    assert client.post(f"/invoices/{invoice['id']}/send").status_code == 409

    template.customer.email = "recien@cargado.com"
    db.flush()

    assert client.get(f"/invoices/{invoice['id']}").json()["customer_email"] == "recien@cargado.com"
    assert client.post(f"/invoices/{invoice['id']}/send").status_code == 200
    assert sent_emails[0].to == "recien@cargado.com"


def test_the_invoice_records_the_address_it_went_to(client, emitted, db, sent_emails):
    """`sent_to` sí es una copia, y es la que corresponde: a dónde salió **este** envío.

    Es el reverso de `customer_email`: uno contesta a dónde mandarla ahora y el otro a dónde
    se mandó. Que el cliente cambie de casilla después no puede reescribir el segundo.
    """
    assert emitted["sent_to"] is None

    client.post(f"/invoices/{emitted['id']}/send")
    assert client.get(f"/invoices/{emitted['id']}").json()["sent_to"] == "cliente@cucu.com"

    invoice = db.execute(select(Invoice)).scalars().one()
    invoice.customer.email = "otra@casilla.com"
    db.flush()

    refreshed = client.get(f"/invoices/{emitted['id']}").json()
    assert refreshed["sent_to"] == "cliente@cucu.com"
    assert refreshed["customer_email"] == "otra@casilla.com"


def test_send_answers_503_when_the_mail_cannot_go_out(client, emitted, broken_mail, db):
    """La factura sigue emitida: el error es del envío, y el texto lo aclara para que nadie
    vuelva a emitir."""
    response = client.post(f"/invoices/{emitted['id']}/send")

    assert response.status_code == 503
    assert "emitida" in response.json()["detail"]


def test_a_failed_send_does_not_mark_it_as_sent(client, emitted, broken_mail):
    client.post(f"/invoices/{emitted['id']}/send")

    assert client.get(f"/invoices/{emitted['id']}").json()["sent_at"] is None


def test_sending_someone_elses_invoice_is_a_404(client, db, other_user):
    identity = make_fiscal_identity(db, other_user.id)
    customer = make_customer(db, other_user.id)
    theirs = make_invoice_template(db, identity, customer)
    db.flush()
    invoice = Invoice(
        fiscal_identity_id=identity.id,
        customer_id=customer.id,
        template_id=theirs.id,
        voucher_type=VoucherType.B,
        pos=1,
        number=7,
        date=date.today(),
        concepto=Concepto.products,
        cae="1",
        cae_expiry=date.today() + timedelta(days=10),
        net_total=Decimal("1"),
        iva_total=Decimal("0"),
        total=Decimal("1"),
        issuer_name=identity.name,
        issuer_tax_id=identity.tax_id,
        issuer_condicion_iva=identity.condicion_iva,
        customer_name=customer.name,
        customer_doc_type=customer.doc_type,
        customer_doc_number=customer.doc_number,
        customer_condicion_iva=customer.condicion_iva,
    )
    db.add(invoice)
    db.flush()

    assert client.post(f"/invoices/{invoice.id}/send").status_code == 404


def test_the_pdf_endpoint_returns_a_pdf(client, emitted):
    response = client.get(f"/invoices/{emitted['id']}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")


def test_the_pdf_opens_in_the_browser_instead_of_downloading(client, emitted):
    """`inline`: en el celular abre el visor, que es lo que uno quiere antes de mandarlo."""
    response = client.get(f"/invoices/{emitted['id']}/pdf")

    assert response.headers["content-disposition"].startswith("inline")
    assert "FactuMov-B-00001-00000042.pdf" in response.headers["content-disposition"]


# --- El registro en Balance360 ---------------------------------------------------------------
#
# Va acá y no en `test_balance360.py` porque lo que se prueba es el enganche con la emisión, y
# el montaje que hace falta —el SOAP mockeado, la identidad delegada, el modelo— vive en este
# archivo. El `TestClient` corre los `BackgroundTask` como parte del ciclo de la respuesta, así
# que emitir por HTTP ejercita la cadena entera.


@pytest.fixture
def background_session(monkeypatch, db):
    """Ata la sesión del `BackgroundTask` a la transacción del test.

    `register_in_background` abre la suya con `SessionLocal` a propósito —cuando corre, la del
    request ya se cerró—, y eso la deja mirando la base real, donde nada de lo que armó el test
    existe: la tarea no encuentra la factura y se va sin hacer nada. Es el mismo problema que
    resuelve `_db_override` para los requests, y la misma solución.

    El `__exit__` no cierra nada: la sesión es del fixture `db`, que la cierra él.
    """

    class KeepOpen:
        def __enter__(self):
            return db

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(database, "SessionLocal", KeepOpen)


def test_emitir_con_balance360_conectado_registra_la_factura(
    client, db, user, template, wsfe_calls, monkeypatch, background_session
):
    from factumov.services import balance360
    from tests.factories import make_balance360_connection

    make_balance360_connection(db, user.id)
    remote_id = uuid4()
    posted = []

    def fake_post(url, json=None, headers=None, timeout=None):
        posted.append(json)
        return SimpleNamespace(
            status_code=201,
            ok=True,
            json=lambda: {
                "id": str(remote_id),
                "entity_id": str(uuid4()),
                "entity_name": "InSoft",
                "contact_id": str(uuid4()),
                "already_registered": False,
            },
        )

    monkeypatch.setattr(balance360.requests, "post", fake_post)

    response = emit(client, template.id)

    assert response.status_code == 201
    # El 201 sale antes de que el registro ocurra: la respuesta lo dice "pendiente".
    assert response.json()["balance360_status"] == "pending"
    # Y para cuando el request terminó, el background task ya corrió.
    assert posted and posted[0]["cae"] == response.json()["cae"]
    invoice = db.get(Invoice, uuid.UUID(response.json()["id"]))
    db.refresh(invoice)
    assert invoice.balance360_status is Balance360Status.REGISTERED
    assert invoice.balance360_invoice_id == remote_id


def test_balance360_caido_no_impide_emitir(
    client, db, user, template, wsfe_calls, monkeypatch, background_session
):
    """El CAE ya existe cuando esto corre. Un 502 acá dejaría un comprobante huérfano."""
    from factumov.services import balance360
    from tests.factories import make_balance360_connection

    make_balance360_connection(db, user.id)

    def explode(url, json=None, headers=None, timeout=None):
        raise balance360.RequestException("connection refused")

    monkeypatch.setattr(balance360.requests, "post", explode)

    response = emit(client, template.id)

    assert response.status_code == 201
    invoice = db.get(Invoice, uuid.UUID(response.json()["id"]))
    db.refresh(invoice)
    assert invoice.balance360_status is Balance360Status.FAILED


def test_sin_cuenta_conectada_emitir_no_deja_nada_pendiente(client, db, template, wsfe_calls):
    """Estado `NULL`: la factura ni siquiera entra al circuito."""
    response = emit(client, template.id)

    assert response.json()["balance360_status"] is None
