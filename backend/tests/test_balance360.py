"""La integración con Balance360: la conexión del usuario y el registro de lo emitido.

**Nada de acá sale a la red.** `requests.get` y `requests.post` se parchean en el módulo del
cliente, que es el nivel más bajo con sentido: así se ejercita de verdad el armado del
payload, la lectura de la respuesta y la traducción de un error HTTP a un estado de la
factura, que es donde están todas las decisiones. Mockear `balance360.register` probaría que
el router llama a una función.

Lo que estos tests cuidan, por encima de todo, es el invariante que da forma al módulo
entero: **un Balance360 caído no puede romper nada de FactuMov.** Un fallo de registro tiene
que terminar siempre en una columna, nunca en una excepción que suba.
"""

import uuid
from decimal import Decimal

import pytest

from factumov.enums import Balance360Status, CondicionIva, IvaAliquot, VoucherType
from factumov.models.balance360_connection import Balance360Connection
from factumov.models.invoice import Invoice
from factumov.services import balance360, secrets
from tests.factories import (
    make_balance360_connection,
    make_customer,
    make_fiscal_identity,
    make_invoice,
)


class FakeResponse:
    """Lo mínimo de `requests.Response` que usa el cliente."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("no es JSON")
        return self._payload


@pytest.fixture
def http(monkeypatch):
    """Intercepta las dos llamadas salientes y devuelve lo que se mandó.

    Guarda url, headers y body de cada request para poder afirmar sobre el contrato: que el
    token viaje como bearer, que los enums vayan por nombre y que los importes vayan como
    string y no como número.
    """

    calls = []
    responses = {"get": FakeResponse(200, []), "post": FakeResponse(201, {})}

    def fake_get(url, headers=None, timeout=None):
        calls.append({"method": "GET", "url": url, "headers": headers or {}})
        result = responses["get"]
        if isinstance(result, Exception):
            raise result
        return result

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"method": "POST", "url": url, "headers": headers or {}, "json": json})
        result = responses["post"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(balance360.requests, "get", fake_get)
    monkeypatch.setattr(balance360.requests, "post", fake_post)
    return {"calls": calls, "responses": responses}


@pytest.fixture
def issuer(db, user):
    identity = make_fiscal_identity(db, user.id, tax_id="20182810674")
    customer = make_customer(db, user.id, condicion_iva=CondicionIva.EXENTO)
    return identity, customer


def registered_response(invoice_id=None, already=False):
    return FakeResponse(
        200 if already else 201,
        {
            "id": str(invoice_id or uuid.uuid4()),
            "entity_id": str(uuid.uuid4()),
            "entity_name": "InSoft",
            "contact_id": str(uuid.uuid4()),
            "already_registered": already,
        },
    )


# --- El payload -------------------------------------------------------------------------


def test_el_payload_manda_los_enums_por_nombre(db, user, issuer):
    """`CondicionIva.FINAL` vale 5 acá y 6 allá. Por valor, un consumidor final entraría
    del otro lado como monotributista sin que nada falle."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)

    payload = balance360.build_payload(invoice)

    assert payload["customer"]["condicion_iva"] == "EXENTO"
    assert payload["customer"]["doc_type"] == "CUIT"
    assert payload["lines"][0]["iva_aliquot"] == "standard"
    # Estos dos sí van por valor: su valor **es** el nombre legible y coincide en las dos apps.
    assert payload["voucher_type"] == "A"
    assert payload["concepto"] == "products"


def test_el_payload_manda_los_importes_como_texto(db, user, issuer):
    """Un float en el JSON convierte 0,1 en binario y el total deja de cerrar contra el CAE."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)

    payload = balance360.build_payload(invoice)

    assert payload["totals"] == {"net": "1000.00", "iva": "210.00", "total": "1210.00"}
    assert payload["lines"][0]["unit_price"] == "1000.00"
    assert isinstance(payload["lines"][0]["quantity"], str)


def test_el_payload_copia_al_receptor_de_la_factura_y_no_de_la_ficha(db, user, issuer):
    """Un registro tardío no puede llevarse del otro lado un domicilio que ya cambió."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    customer.name = "Cambió Después SRL"
    db.flush()

    payload = balance360.build_payload(invoice)

    assert payload["customer"]["name"] == invoice.customer_name
    assert payload["customer"]["name"] != "Cambió Después SRL"


def test_el_id_de_la_factura_es_la_clave_de_idempotencia(db, user, issuer):
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)

    assert balance360.build_payload(invoice)["external_id"] == str(invoice.id)


# --- El registro ------------------------------------------------------------------------


def test_un_registro_exitoso_guarda_el_id_remoto(db, user, issuer, http):
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    connection = make_balance360_connection(db, user.id)
    remote_id = uuid.uuid4()
    http["responses"]["post"] = registered_response(remote_id)

    result = balance360.register(db, invoice)

    assert result is not None
    assert invoice.balance360_status is Balance360Status.REGISTERED
    assert invoice.balance360_invoice_id == remote_id
    assert invoice.balance360_error is None
    assert invoice.balance360_synced_at is not None
    # El token anduvo: la conexión queda verificada sin que nadie haya apretado "probar".
    assert connection.verified_at is not None


def test_el_token_viaja_como_bearer(db, user, issuer, http):
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    make_balance360_connection(db, user.id, token="b360_secreto")
    http["responses"]["post"] = registered_response()

    balance360.register(db, invoice)

    (call,) = http["calls"]
    assert call["url"] == "https://balance.test/api/invoices/issued"
    assert call["headers"]["Authorization"] == "Bearer b360_secreto"


def test_balance360_caido_deja_la_factura_fallada_y_no_levanta(db, user, issuer, http):
    """El invariante del módulo: la copia falla en una columna, nunca en una excepción."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    make_balance360_connection(db, user.id)
    http["responses"]["post"] = balance360.RequestException("connection refused")

    assert balance360.register(db, invoice) is None
    assert invoice.balance360_status is Balance360Status.FAILED
    assert "reintentar" in invoice.balance360_error


def test_el_motivo_que_da_balance360_se_guarda_tal_cual(db, user, issuer, http):
    """"El CUIT no está cargado" es accionable; "error 422" no le dice nada a nadie."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    make_balance360_connection(db, user.id)
    http["responses"]["post"] = FakeResponse(
        422, {"detail": "El CUIT 20182810674 no está cargado en Balance360."}
    )

    balance360.register(db, invoice)

    assert invoice.balance360_status is Balance360Status.FAILED
    assert invoice.balance360_error == "El CUIT 20182810674 no está cargado en Balance360."


def test_un_error_largo_no_rompe_el_guardado_del_error(db, user, issuer, http):
    """Un fallo de registro no se puede convertir en un fallo al *guardar* el fallo."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    make_balance360_connection(db, user.id)
    http["responses"]["post"] = FakeResponse(422, {"detail": "x" * 900})

    balance360.register(db, invoice)

    assert len(invoice.balance360_error) == 300


def test_sin_conexion_la_factura_queda_fuera_del_circuito(db, user, issuer, http):
    """Se desconectó entre la emisión y el registro: no falló nada, no hay nada que copiar."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    invoice.balance360_status = Balance360Status.PENDING

    assert balance360.register(db, invoice) is None
    assert invoice.balance360_status is None
    assert http["calls"] == []


def test_un_token_que_no_se_puede_descifrar_no_sale_a_la_red(db, user, issuer, http):
    """La clave del servidor cambió. No hay nada que reintentar: hay que pegar el token."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    connection = make_balance360_connection(db, user.id)
    connection.encrypted_token = secrets.encrypt("otro")[:-10] + "0123456789"
    db.flush()

    balance360.register(db, invoice)

    assert invoice.balance360_status is Balance360Status.FAILED
    assert "volvé a conectar" in invoice.balance360_error.lower()
    assert http["calls"] == []


def test_el_reintento_que_encuentra_el_registro_anterior_tambien_es_exito(
    db, user, issuer, http
):
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    make_balance360_connection(db, user.id)
    remote_id = uuid.uuid4()
    http["responses"]["post"] = registered_response(remote_id, already=True)

    result = balance360.register(db, invoice)

    assert result is not None and result.already_registered is True
    assert invoice.balance360_status is Balance360Status.REGISTERED


# --- La conexión, por HTTP --------------------------------------------------------------


def test_sin_conexion_los_ajustes_contestan_conexion_nula(client):
    """No conectado es un estado normal, no un 404."""
    response = client.get("/balance360")

    assert response.status_code == 200
    assert response.json() == {"available": True, "connection": None}


def test_conectar_prueba_el_token_antes_de_guardarlo(client, db, user, http):
    response = client.put(
        "/balance360",
        json={"base_url": "https://balance.test/", "api_token": "b360_unTokenDePrueba"},
    )

    assert response.status_code == 200
    (call,) = http["calls"]
    assert call["method"] == "GET"
    assert call["url"] == "https://balance.test/api/entities"
    connection = db.query(Balance360Connection).one()
    assert connection.verified_at is not None
    # La barra final se normaliza al guardar, no al armar cada URL.
    assert connection.base_url == "https://balance.test"


def test_el_token_no_vuelve_nunca_en_la_respuesta(client, http):
    response = client.put(
        "/balance360",
        json={"base_url": "https://balance.test", "api_token": "b360_unTokenDePrueba"},
    )

    body = response.json()
    assert "b360_unTokenDePrueba" not in response.text
    assert body["connection"]["token_hint"] == "ueba"


def test_un_token_que_balance360_no_acepta_no_se_guarda(client, db, http):
    """Enterarse ahora, con el token en el portapapeles, y no en la próxima emisión."""
    http["responses"]["get"] = FakeResponse(401, {"detail": "Token invalido"})

    response = client.put(
        "/balance360",
        json={"base_url": "https://balance.test", "api_token": "b360_unTokenDePrueba"},
    )

    assert response.status_code == 502
    assert db.query(Balance360Connection).count() == 0


def test_el_token_se_limpia_antes_de_probarlo(client, db, http):
    """Un espacio de más al copiarlo del ssh da el mismo 401 que un token revocado."""
    response = client.put(
        "/balance360",
        json={"base_url": "https://balance.test", "api_token": "  b360_unTokenDePrueba\n"},
    )

    assert response.status_code == 200
    (call,) = http["calls"]
    assert call["headers"]["Authorization"] == "Bearer b360_unTokenDePrueba"
    assert db.query(Balance360Connection).one().token_hint == "ueba"


def test_una_direccion_sin_esquema_se_rechaza_con_422(client, http):
    response = client.put(
        "/balance360", json={"base_url": "balance.test", "api_token": "b360_unToken"}
    )

    assert response.status_code == 422
    assert http["calls"] == []


def test_desconectar_no_falla_aunque_no_haya_nada_conectado(client):
    assert client.delete("/balance360").status_code == 204


def test_desconectar_borra_la_conexion(client, db, user):
    make_balance360_connection(db, user.id)

    assert client.delete("/balance360").status_code == 204
    assert db.query(Balance360Connection).count() == 0


# --- El reintento, por HTTP -------------------------------------------------------------


def test_reintentar_una_factura_devuelve_su_estado(client, db, user, issuer, http):
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    make_balance360_connection(db, user.id)
    http["responses"]["post"] = registered_response()

    response = client.post(f"/invoices/{invoice.id}/register")

    assert response.status_code == 200
    assert response.json()["balance360_status"] == "registered"


def test_un_reintento_que_falla_igual_contesta_200(client, db, user, issuer, http):
    """El resultado del intento no es el resultado del request: la pantalla lee la factura."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    make_balance360_connection(db, user.id)
    http["responses"]["post"] = FakeResponse(422, {"detail": "Falta cargar el CUIT."})

    response = client.post(f"/invoices/{invoice.id}/register")

    assert response.status_code == 200
    body = response.json()
    assert body["balance360_status"] == "failed"
    assert body["balance360_error"] == "Falta cargar el CUIT."


def test_reintentar_sin_cuenta_conectada_contesta_409(client, db, user, issuer, http):
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)

    response = client.post(f"/invoices/{invoice.id}/register")

    assert response.status_code == 409
    assert http["calls"] == []


def test_el_lote_sigue_de_largo_cuando_una_falla(client, db, user, issuer, http, monkeypatch):
    """Los errores no son homogéneos: cortar en la primera dejaría el resto sin intentar."""
    identity, customer = issuer
    first = make_invoice(db, identity, customer, number=101)
    second = make_invoice(db, identity, customer, number=102)
    for invoice in (first, second):
        invoice.balance360_status = Balance360Status.FAILED
    make_balance360_connection(db, user.id)
    db.flush()

    outcomes = iter([FakeResponse(422, {"detail": "Falta cargar el CUIT."}), registered_response()])
    monkeypatch.setattr(
        balance360.requests, "post", lambda *args, **kwargs: next(outcomes)
    )

    response = client.post("/balance360/register-pending")

    assert response.json() == {"attempted": 2, "registered": 1, "failed": 1}
    assert first.balance360_status is Balance360Status.FAILED
    assert second.balance360_status is Balance360Status.REGISTERED


def test_el_lote_no_toca_las_facturas_de_antes_de_la_integracion(client, db, user, issuer, http):
    """Estado `NULL` no es "pendiente": es una factura que nunca entró al circuito.

    Sin esto, el botón de reintentar sería un botón de registrar retroactivamente todo el
    historial — que es una decisión del usuario y no algo que un reintento pueda hacer solo.
    """
    identity, customer = issuer
    make_invoice(db, identity, customer)
    make_balance360_connection(db, user.id)

    response = client.post("/balance360/register-pending")

    assert response.json() == {"attempted": 0, "registered": 0, "failed": 0}
    assert http["calls"] == []


def test_las_facturas_de_otro_usuario_no_entran_en_el_lote(client, db, other_user, http):
    identity = make_fiscal_identity(db, other_user.id, tax_id="27111111114")
    customer = make_customer(db, other_user.id)
    invoice = make_invoice(db, identity, customer)
    invoice.balance360_status = Balance360Status.FAILED
    db.flush()
    make_balance360_connection(db, other_user.id)

    # La conexión es del otro usuario; el que pide es el del fixture `client`.
    assert client.post("/balance360/register-pending").status_code == 409


# --- El cifrado del token ---------------------------------------------------------------


def test_el_token_guardado_no_esta_en_claro_en_la_base(db, user):
    connection = make_balance360_connection(db, user.id, token="b360_secretisimo")

    assert "b360_secretisimo" not in connection.encrypted_token
    assert secrets.decrypt(connection.encrypted_token) == "b360_secretisimo"


def test_sin_clave_de_cifrado_la_pantalla_lo_dice_en_vez_de_reventar(
    client, monkeypatch, http
):
    monkeypatch.delenv("SECRET_ENCRYPTION_KEY", raising=False)
    secrets.get_secrets_settings.cache_clear()
    secrets._cipher.cache_clear()

    assert client.get("/balance360").json()["available"] is False
    response = client.put(
        "/balance360", json={"base_url": "https://balance.test", "api_token": "b360_unToken"}
    )
    assert response.status_code == 503
    assert http["calls"] == []


# --- Detalles del contrato --------------------------------------------------------------


def test_una_b_manda_el_precio_con_el_iva_adentro_sin_traducir(db, user, http):
    """FactuMov guarda el precio como se carga; traducirlo es trabajo de Balance360.

    Si tradujera el que llama, cambiar el modelo de datos de la otra app obligaría a
    redeployar esta.
    """
    from factumov.models.invoice_line import InvoiceLine

    identity = make_fiscal_identity(db, user.id, tax_id="20182810674")
    customer = make_customer(db, user.id, condicion_iva=CondicionIva.FINAL)
    invoice = make_invoice(
        db,
        identity,
        customer,
        voucher_type=VoucherType.B,
        lines=[
            InvoiceLine(
                position=0,
                description="Servicio",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                iva_aliquot=IvaAliquot.standard,
            )
        ],
        net_total=Decimal("82.64"),
        iva_total=Decimal("17.36"),
        total=Decimal("100.00"),
    )

    payload = balance360.build_payload(invoice)

    assert payload["lines"][0]["unit_price"] == "100.00"
    assert payload["totals"]["total"] == "100.00"


def test_el_background_task_con_una_factura_que_no_existe_no_explota(db, user):
    """Corre fuera del request: una excepción acá no la ve nadie y puede tirar el worker."""
    balance360.register_in_background(uuid.uuid4(), user.id)


def test_la_factura_no_registrada_sale_en_la_api_con_los_campos_en_null(
    client, db, user, issuer
):
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)

    body = client.get(f"/invoices/{invoice.id}").json()

    assert body["balance360_status"] is None
    assert body["balance360_invoice_id"] is None
    assert body["balance360_error"] is None


def test_la_grilla_de_facturas_trae_el_estado(client, db, user, issuer):
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    invoice.balance360_status = Balance360Status.FAILED
    invoice.balance360_error = "Falta cargar el CUIT."
    db.flush()

    (row,) = client.get("/invoices").json()

    assert row["balance360_status"] == "failed"
    assert row["balance360_error"] == "Falta cargar el CUIT."


def test_el_estado_pendiente_se_persiste_como_nombre(db, user, issuer):
    """La columna guarda el nombre del miembro; el JSON manda el valor."""
    identity, customer = issuer
    invoice = make_invoice(db, identity, customer)
    invoice.balance360_status = Balance360Status.PENDING
    db.flush()

    stored = db.query(Invoice).filter(Invoice.id == invoice.id).one()
    assert stored.balance360_status is Balance360Status.PENDING
