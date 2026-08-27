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

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from sqlalchemy import select
from zeep.exceptions import Fault

from factumov.enums import Concepto, CondicionIva, DocType, IvaAliquot, VoucherType
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
        arca, "get_access_ticket", lambda service: arca.AccessTicket(token="tk", sign="sg")
    )


@pytest.fixture
def wsfe_calls(monkeypatch):
    """Mockea las dos operaciones de emisión y devuelve lo que se les mandó.

    `FECompUltimoAutorizado` contesta siempre el mismo último número salvo que el test lo
    cambie; `FECAESolicitar` contesta lo que el test configure. Las llamadas quedan
    registradas porque la mitad de lo que hay que probar acá es **qué se le manda a ARCA**,
    no solo qué se hace con lo que contesta.
    """
    state = {"last_number": 41, "response": AUTHORIZED}
    calls: dict[str, list] = {"last": [], "cae": []}

    def last_authorized(**kwargs):
        calls["last"].append(kwargs)
        return SimpleNamespace(Errors=None, CbteNro=state["last_number"])

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


def test_the_subject_names_the_voucher_and_the_issuer(client, emitted, sent_emails):
    """Es lo que el destinatario ve en su lista de correo; "Factura" a secas no dice de quién."""
    client.post(f"/invoices/{emitted['id']}/send")

    assert emitted["label"] in sent_emails[0].subject
    assert emitted["issuer_name"] in sent_emails[0].subject


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
        customer_email="ajeno@cucu.com",
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
