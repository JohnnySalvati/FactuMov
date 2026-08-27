"""El comprobante impreso: QR, HTML y PDF — `services/invoice_pdf.py`.

Casi todo se afirma sobre el **HTML** y no sobre el PDF. No es por comodidad: el PDF es la
misma información pasada por weasyprint, y abrirlo para leerlo de vuelta probaría weasyprint y
no lo nuestro. Lo que sí tiene su test es que el PDF salga, porque depende de las librerías GTK
del sistema y esa es la parte que se rompe al cambiar de máquina.

El QR se decodifica y se compara contra el JSON que ARCA espera, con los tipos incluidos: un
número donde va un número. Un QR con un string ahí se lee igual y el validador de ARCA lo
rechaza, que es exactamente la clase de error que ningún test superficial encuentra.
"""

import base64
import json
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from factumov.enums import Concepto, CondicionIva, DocType, IvaAliquot, VoucherType
from factumov.models.invoice import Invoice
from factumov.models.invoice_line import InvoiceLine
from factumov.services import invoice_pdf


def make_invoice(voucher_type=VoucherType.B, lines=((Decimal("2"), Decimal("1234.56")),), **over):
    """Una factura en memoria, sin base. El PDF no necesita ninguna fila: la factura ya trae
    copiadas las dos partes, que es la mitad del motivo por el que esas columnas existen."""
    fields = {
        "voucher_type": voucher_type,
        "pos": 1,
        "number": 42,
        "date": date(2026, 8, 27),
        "concepto": Concepto.products,
        "cae": "75123456789012",
        "cae_expiry": date(2026, 9, 6),
        "net_total": Decimal("2469.12"),
        "iva_total": Decimal("0.00"),
        "total": Decimal("2469.12"),
        "issuer_name": "Estudio Salvati",
        "issuer_tax_id": "20182810674",
        "issuer_condicion_iva": CondicionIva.INSCRIPTO,
        "issuer_address": "Corrientes 1234",
        "issuer_iibb": "901-123456-7",
        "issuer_start_date": date(2010, 3, 1),
        "customer_name": "Cliente SA",
        "customer_doc_type": DocType.CUIT,
        "customer_doc_number": "30500010912",
        "customer_condicion_iva": CondicionIva.FINAL,
        "customer_address": "Rivadavia 500",
    }
    fields.update(over)
    invoice = Invoice(**fields)
    invoice.lines = [
        InvoiceLine(
            position=position,
            description=f"Servicio {position + 1}",
            quantity=quantity,
            unit_price=unit_price,
            iva_aliquot=IvaAliquot.standard,
        )
        for position, (quantity, unit_price) in enumerate(lines)
    ]
    return invoice


# --- El QR fiscal --------------------------------------------------------------------------


def test_the_qr_is_a_png_data_uri():
    """Data URI y no un archivo: el PDF se arma en memoria y nadie limpiaría un temporal."""
    assert invoice_pdf.build_qr(make_invoice()).startswith("data:image/png;base64,")


def decode_qr_json(invoice, monkeypatch):
    """El JSON que va adentro del QR, ya parseado.

    Se intercepta lo que se le pasa a segno en vez de decodificar el PNG: lo que puede estar
    mal es el payload, y leerlo del PNG probaría el lector de QR más que lo nuestro.
    """
    captured = {}

    def fake_make(content):
        captured["url"] = content

        class Fake:
            def png_data_uri(self, scale):
                return "data:image/png;base64,AAAA"

        return Fake()

    monkeypatch.setattr(invoice_pdf.segno, "make", fake_make)
    invoice_pdf.build_qr(invoice)
    encoded = parse_qs(urlparse(captured["url"]).query)["p"][0]
    return json.loads(base64.b64decode(encoded))


def test_the_qr_carries_what_arca_asks_for(monkeypatch):
    payload = decode_qr_json(make_invoice(), monkeypatch)

    assert payload["ver"] == 1
    assert payload["fecha"] == "2026-08-27"
    assert payload["ptoVta"] == 1
    assert payload["nroCmp"] == 42
    assert payload["moneda"] == "PES"
    assert payload["tipoCodAut"] == "E"


def test_the_qr_uses_the_arca_voucher_code(monkeypatch):
    """`tipoCmp` es el código de ARCA, no la letra: la B es 6."""
    payload = decode_qr_json(make_invoice(voucher_type=VoucherType.B), monkeypatch)

    assert payload["tipoCmp"] == 6


@pytest.mark.parametrize("field", ["cuit", "nroDocRec", "codAut"])
def test_the_identifiers_travel_as_numbers(monkeypatch, field):
    """Un string donde ARCA espera un número se ve igual y el validador lo rechaza."""
    payload = decode_qr_json(make_invoice(), monkeypatch)

    assert isinstance(payload[field], int)


def test_the_amount_travels_as_a_number(monkeypatch):
    payload = decode_qr_json(make_invoice(), monkeypatch)

    assert payload["importe"] == 2469.12


# --- El HTML -------------------------------------------------------------------------------


def test_the_html_shows_the_copied_parties():
    """Del emisor y el receptor **copiados**, no de las fichas actuales."""
    html = invoice_pdf.render_html(make_invoice())

    assert "Estudio Salvati" in html
    assert "Cliente SA" in html
    assert "Rivadavia 500" in html


def test_the_tax_ids_are_printed_the_way_arca_prints_them():
    html = invoice_pdf.render_html(make_invoice())

    assert "20-18281067-4" in html
    assert "30-50001091-2" in html


def test_the_condition_uses_arcas_wording_and_not_ours():
    """El enum se llama FINAL; el papel tiene que decir "Consumidor Final"."""
    html = invoice_pdf.render_html(make_invoice())

    assert "Consumidor Final" in html
    assert "IVA Responsable Inscripto" in html


def test_the_cae_and_its_expiry_are_at_the_foot():
    html = invoice_pdf.render_html(make_invoice())

    assert "75123456789012" in html
    assert "06/09/2026" in html


def test_an_a_discriminates_the_iva_columns():
    html = invoice_pdf.render_html(
        make_invoice(voucher_type=VoucherType.A, iva_total=Decimal("518.52"))
    )

    assert "Alícuota IVA" in html
    assert "Importe Neto Gravado" in html


def test_a_b_does_not_discriminate():
    """La B declara el IVA ante ARCA y no lo muestra: el precio impreso ya lo incluye."""
    html = invoice_pdf.render_html(make_invoice(voucher_type=VoucherType.B))

    assert "Alícuota IVA" not in html
    assert "Subtotal:" in html


def test_the_service_period_only_shows_for_services():
    with_period = invoice_pdf.render_html(
        make_invoice(
            concepto=Concepto.services,
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 31),
            due_date=date(2026, 9, 10),
        )
    )
    without = invoice_pdf.render_html(make_invoice())

    assert "Período Facturado Desde" in with_period
    assert "Período Facturado Desde" not in without


def test_the_letter_box_shows_the_letter_and_the_code():
    html = invoice_pdf.render_html(make_invoice(voucher_type=VoucherType.B))

    assert "COD. 06" in html


def test_a_missing_variable_would_blow_up_rather_than_print_nothing():
    """`StrictUndefined`: en un comprobante fiscal, un campo que desaparece en silencio es
    peor que un error."""
    from jinja2 import UndefinedError

    environment = invoice_pdf._environment()

    with pytest.raises(UndefinedError):
        environment.from_string("{{ no_existe }}").render()


def test_the_customer_name_is_escaped():
    """El nombre lo cargó una persona y va al HTML sin pasar por ninguna limpieza."""
    html = invoice_pdf.render_html(make_invoice(customer_name="Fulano <script>x</script>"))

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# --- Formato de importes -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "0,00"),
        ("1234.5", "1.234,50"),
        ("1234567.89", "1.234.567,89"),
        ("999.999", "1.000,00"),
        ("-1234.5", "-1.234,50"),
    ],
)
def test_amounts_are_formatted_the_argentine_way(value, expected):
    """A mano y no con `locale`: es global del proceso y depende de que el sistema tenga
    `es_AR`, que en un contenedor no pasa."""
    assert invoice_pdf.format_amount(Decimal(value)) == expected


def test_a_tax_id_that_is_not_eleven_digits_is_left_alone():
    """Un DNI no se formatea como CUIT. Mejor sin guiones que con los guiones equivocados."""
    assert invoice_pdf.format_tax_id("12345678") == "12345678"


# --- El PDF --------------------------------------------------------------------------------


def test_the_pdf_is_actually_a_pdf():
    """Lo único que hay que probar del PDF, y depende de las GTK del sistema: que salga."""
    pdf = invoice_pdf.render_pdf(make_invoice())

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_the_filename_names_the_voucher():
    """Para que el destinatario no junte cinco archivos llamados todos `comprobante.pdf`."""
    assert invoice_pdf.pdf_filename(make_invoice()) == "FactuMov-B-00001-00000042.pdf"


def test_an_invoice_with_many_lines_still_renders():
    """Guarda barata contra un template que se rompa con más de una línea."""
    invoice = make_invoice(lines=[(Decimal("1"), Decimal("100"))] * 12)

    assert invoice_pdf.render_pdf(invoice).startswith(b"%PDF-")


def test_a_cae_about_to_expire_is_still_printable():
    """El vencimiento del CAE no cambia nada del impreso; está para que no falte el caso."""
    invoice = make_invoice(cae_expiry=date.today() - timedelta(days=1))

    assert "%PDF-".encode() in invoice_pdf.render_pdf(invoice)[:10]
