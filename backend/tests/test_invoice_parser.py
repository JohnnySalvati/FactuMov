"""Tests for the invoice PDF parser, which reads two layouts.

Three kinds of test live here, and the difference matters. The parametrised cases at
the top read the real PDFs in `samples/`. The round trip in the middle prints an
invoice with `services/invoice_pdf.py` and reads it back, which is the only check
that stays honest when the template changes — `samples/` is gitignored, so a PDF of
our own committed next to it would rot unnoticed. The ones at the bottom feed
hand-written rows straight into `_extract_items`, to reach the columns and rates no
sample carries.

`samples/` holds documents this parser is meant to read, whatever generator printed
them: ARCA "Comprobantes en línea" and the printed voucher of FactuMov and
Balance360, which are the same layout. A PDF nobody can read yet does not belong
there — it would turn `test_every_sample_parses_end_to_end` red for a case that was
never claimed to work.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from factumov.enums import Concepto, CondicionIva, DocType, IvaAliquot, VoucherType
from factumov.models.invoice import Invoice
from factumov.models.invoice_line import InvoiceLine
from factumov.services.invoice_parser import (
    _ARCA,
    _FACTUMOV,
    _detect_layout,
    _extract_items,
    _to_decimal,
    parse_invoice_pdf,
)
from factumov.services.invoice_pdf import render_pdf

SAMPLES = Path(__file__).parent / "samples"


@pytest.mark.parametrize(
    "file, data",
    [
        (
            "20206205297_011_00001_00000205.pdf",
            {
                "voucher_type": VoucherType.C,
                "pos": int(1),
                "number": int(205),
                "customer_doc_type": DocType.CUIT,
                "customer_doc_number": "30714597066",
                "number_of_lines": 1,
                "customer_address": "Ibera 4947 - Capital Federal, Ciudad de Buenos Aires",
                "first_line_unit_price": Decimal(2805000),
            },
        ),
        (
            "20206205297_011_00001_00000207.pdf",
            {
                "voucher_type": VoucherType.C,
                "pos": int(1),
                "number": int(207),
                "customer_doc_type": DocType.CUIT,
                "customer_doc_number": "30714455113",
                "number_of_lines": 1,
                "customer_address": "Rivadavia M. Cdro. 1350 - "
                + "Capital Federal, Ciudad de Buenos Aires",
                "first_line_unit_price": Decimal(1520000),
            },
        ),
        (
            "20182810674_001_00002_00000134.pdf",
            {
                "voucher_type": VoucherType.A,
                "pos": int(2),
                "number": int(134),
                "customer_doc_type": DocType.CUIT,
                "customer_doc_number": "23105048009",
                "number_of_lines": 2,
                "customer_address": "Hubac 4686 - Capital Federal, Ciudad de Buenos Aires",
                "first_line_unit_price": Decimal(35000),
            },
        ),
        (
            "30714597066_006_00010_00000055.pdf",
            {
                "voucher_type": VoucherType.B,
                "pos": int(10),
                "number": int(55),
                "customer_doc_type": DocType.CUIT,
                "customer_doc_number": "30535621159",
                "number_of_lines": 2,
                "customer_address": "Cazadores De Coquimbo 2841 Piso:2 - Munro, Buenos Aires",
                "first_line_unit_price": Decimal(28000),
            },
        ),
        # La única del otro layout: una A de verdad, impresa por Balance360, que es
        # el mismo comprobante que imprime FactuMov. El domicilio del receptor sale
        # None porque el contacto no lo tenía cargado y el rótulo se imprimió vacío.
        (
            "factura_A_00005-00000001.pdf",
            {
                "voucher_type": VoucherType.A,
                "pos": int(5),
                "number": int(1),
                "customer_doc_type": DocType.CUIT,
                "customer_doc_number": "23105048009",
                "number_of_lines": 2,
                "customer_address": None,
                "first_line_unit_price": Decimal(15000),
            },
        ),
    ],
)
def test_invoice_parser(file, data):
    file_bytes = (SAMPLES / file).read_bytes()

    parsed = parse_invoice_pdf(file_bytes)

    assert data["voucher_type"] == parsed.voucher_type
    assert data["pos"] == parsed.pos
    assert data["number"] == parsed.number
    assert data["customer_doc_type"] == parsed.customer_doc_type
    assert data["customer_doc_number"] == parsed.customer_doc_number
    assert data["number_of_lines"] == len(parsed.lines)
    assert data["customer_address"] == parsed.customer_address
    assert data["first_line_unit_price"] == parsed.lines[0].unit_price


@pytest.mark.parametrize("sample", sorted(SAMPLES.glob("*.pdf")), ids=lambda path: path.name)
def test_every_sample_parses_end_to_end(sample):
    """A floor under every sample, so a regex change cannot quietly empty one out.

    The named cases above pin exact values for four of them; this one only asserts
    that nothing came back empty, which is what a broken row pattern looks like.
    """
    parsed = parse_invoice_pdf(sample.read_bytes())

    assert parsed.lines
    assert parsed.needs_manual_items is False
    assert parsed.issuer_cuit is not None
    assert parsed.customer_doc_number is not None
    assert parsed.cae is not None


def test_an_unreadable_pdf_parses_to_an_empty_result():
    """Corrupt or scanned input is not an error: every field comes back None.

    The import endpoint depends on this — it answers 200 with an empty draft and
    lets the UI offer manual entry, instead of turning a bad scan into a 500.
    """
    parsed = parse_invoice_pdf(b"%PDF-1.4 not actually a pdf")

    assert parsed.lines == []
    assert parsed.needs_manual_items is True
    assert parsed.voucher_type is None
    assert parsed.issuer_cuit is None


# --- El comprobante propio, ida y vuelta -------------------------------------
#
# Se imprime con `services/invoice_pdf.py` y se lo lee de vuelta. Es más caro que
# leer un PDF guardado —hay que levantar weasyprint— pero es lo único que sigue
# diciendo la verdad el día que el template cambie: un PDF nuestro guardado en
# `samples/` envejecería sin que nada lo delate, y encima ese directorio está
# gitignoreado. Es también el layout de Balance360, porque el template es un port
# del suyo.


def printed_pdf(
    voucher_type=VoucherType.A, lines=(("Consultoria", "1", "15000", IvaAliquot.standard),), **over
):
    """Una factura impresa por FactuMov, como bytes de PDF.

    En memoria y sin base: la factura ya trae copiados el emisor y el receptor, que
    es de donde el impreso los saca. Mismo criterio que `test_invoice_pdf.py`.
    """
    fields = {
        "voucher_type": voucher_type,
        "pos": 5,
        "number": 134,
        "date": date(2026, 7, 14),
        "concepto": Concepto.products,
        "cae": "86305118301690",
        "cae_expiry": date(2026, 7, 14) + timedelta(days=10),
        "net_total": Decimal("15000.00"),
        "iva_total": Decimal("3150.00"),
        "total": Decimal("18150.00"),
        "issuer_name": "Jose Miguel Salvati",
        "issuer_tax_id": "20182810674",
        "issuer_condicion_iva": CondicionIva.INSCRIPTO,
        "issuer_address": "Aroma Pje. 2312 - CABA",
        "issuer_iibb": "20182810674",
        "issuer_start_date": date(2006, 1, 6),
        "customer_name": "Jazbec Juan Carlos",
        "customer_doc_type": DocType.CUIT,
        "customer_doc_number": "23105048009",
        "customer_condicion_iva": CondicionIva.INSCRIPTO,
        "customer_address": "Hubac 4686 - Capital Federal, Ciudad de Buenos Aires",
    }
    fields.update(over)
    invoice = Invoice(**fields)
    invoice.lines = [
        InvoiceLine(
            position=position,
            description=description,
            quantity=Decimal(quantity),
            unit_price=Decimal(unit_price),
            iva_aliquot=aliquot,
        )
        for position, (description, quantity, unit_price, aliquot) in enumerate(lines)
    ]
    return render_pdf(invoice)


@pytest.mark.parametrize(
    "voucher_type, aliquot",
    [
        (VoucherType.A, IvaAliquot.standard),
        (VoucherType.B, IvaAliquot.standard),
        (VoucherType.C, IvaAliquot.exempt),
    ],
)
def test_a_voucher_we_printed_is_read_back_whole(voucher_type, aliquot):
    """Reimportar una factura propia es el caso natural: se emitió una en julio y en
    agosto se quiere volver a facturar lo mismo. Antes de esto el parser sacaba de
    ese PDF el número y el CAE, y nada más: ni CUIT, ni receptor, ni líneas."""
    parsed = parse_invoice_pdf(printed_pdf(voucher_type, [("Consultoria", "2", "15000", aliquot)]))

    assert parsed.voucher_type == voucher_type
    assert parsed.pos == 5
    assert parsed.number == 134
    assert parsed.date == date(2026, 7, 14)
    assert parsed.cae == "86305118301690"
    assert parsed.issuer_cuit == "20182810674"
    assert parsed.issuer_name == "Jose Miguel Salvati"
    assert parsed.issuer_condicion_iva == CondicionIva.INSCRIPTO
    assert parsed.issuer_address == "Aroma Pje. 2312 - CABA"
    assert parsed.issuer_iibb == "20182810674"
    assert parsed.issuer_start_date == date(2006, 1, 6)
    assert parsed.customer_doc_type == DocType.CUIT
    assert parsed.customer_doc_number == "23105048009"
    assert parsed.customer_name == "Jazbec Juan Carlos"
    assert parsed.customer_address == "Hubac 4686 - Capital Federal, Ciudad de Buenos Aires"
    assert parsed.needs_manual_items is False
    assert [(line.description, line.quantity, line.unit_price) for line in parsed.lines] == [
        ("Consultoria", Decimal("2"), Decimal("15000"))
    ]


def test_the_dashes_of_our_own_tax_ids_do_not_reach_the_columns():
    """El impreso escribe el CUIT como 20-18281067-4 y la columna guarda 11 dígitos.

    Los guiones eran la mitad de la razón por la que este layout no se leía: los
    patrones pedían once dígitos seguidos y no encontraban ninguno.
    """
    parsed = parse_invoice_pdf(
        printed_pdf(customer_doc_type=DocType.DNI, customer_doc_number="18281067")
    )

    assert parsed.issuer_cuit == "20182810674"
    assert parsed.customer_doc_type == DocType.DNI
    assert parsed.customer_doc_number == "18281067"


def test_a_printed_a_keeps_the_aliquot_of_every_line():
    """La A discrimina IVA por línea también en el impreso propio, y hay que leerlo.

    Deducirlo de la letra da 21 para las dos, que es plausible y equivocado.
    """
    parsed = parse_invoice_pdf(
        printed_pdf(
            VoucherType.A,
            [
                ("Consultoria", "1", "100000", IvaAliquot.standard),
                ("Libros tecnicos", "2", "15000", IvaAliquot.reduced),
            ],
        )
    )

    assert [line.iva_rate for line in parsed.lines] == [Decimal("21"), Decimal("10.5")]


def test_a_b_falls_back_to_the_rate_of_the_letter():
    """En B el impreso no tiene columna de alícuota: la letra es todo lo que hay."""
    parsed = parse_invoice_pdf(printed_pdf(VoucherType.B))

    assert [line.iva_rate for line in parsed.lines] == [Decimal("21")]


def test_a_description_that_wraps_comes_back_entire():
    """Una descripción larga parte la celda en varios renglones, y el generador
    centra los números: la fila con las columnas queda en el medio y el principio de
    la descripción, arriba. Perder ese pedazo dejaba la línea con la mitad del texto.
    """
    description = (
        "Servicio integral de mantenimiento preventivo y correctivo de la red de "
        "datos, incluyendo cableado estructurado y certificacion"
    )
    parsed = parse_invoice_pdf(
        printed_pdf(lines=[(description, "1", "15000", IvaAliquot.standard)])
    )

    assert [line.description for line in parsed.lines] == [description]


def test_the_service_period_comes_back_from_our_own_wording():
    """ARCA titula "Fecha de Vto. para el pago:" y el impreso propio, "Vto. para el
    pago:" a secas. El rótulo corto no matcheaba y el período entero se perdía."""
    parsed = parse_invoice_pdf(
        printed_pdf(
            concepto=Concepto.services,
            from_date=date(2026, 7, 1),
            to_date=date(2026, 7, 31),
            due_date=date(2026, 8, 10),
        )
    )

    assert parsed.from_date == date(2026, 7, 1)
    assert parsed.to_date == date(2026, 7, 31)
    assert parsed.due_date == date(2026, 8, 10)


def test_each_generator_is_recognised_by_what_only_it_prints():
    """La marca de cada layout está en todo comprobante suyo, tenga items o no.

    Reconocerlos por el encabezado de la tabla dejaría sin identificar justo a los
    PDFs cuyas líneas no se pudieron leer, que son los que más interesa ubicar.
    """
    assert _detect_layout("CUIT: 20-18281067-4 Razon Social: X") is _FACTUMOV
    assert _detect_layout("CUIT: 20182810674 Apellido y Nombre / Razón Social: X") is _ARCA
    # Un generador desconocido cae en el de ARCA, que es el que más facturas cubre.
    assert _detect_layout("una factura de cualquier otro sistema") is _ARCA


# --- Item rows ---------------------------------------------------------------
#
# The A layout is covered by a real sample in the parametrisation above. What is
# driven straight through the private `_extract_items` down here is the one thing no
# sample carries: every A invoice in samples/ is 21% throughout, so the reduced and
# higher rates, and the mixed-rate voucher, are typed by hand.
#
# They follow the column widths the real sample confirmed, which differ by letter:
#
#   B and C:  % Bonif | Imp. Bonif. | Subtotal                     -> 3 columns
#   A:        % Bonif | Subtotal | Alícuota IVA | Subtotal c/IVA    -> 4 columns
#
# A does not print Imp. Bonif. and does print the aliquot per line, which is why the
# extractor keys on the count rather than on the letter.

ITEMS_HEADER_BC = (
    "Código Producto / Servicio Cantidad U. Medida Precio Unit. % Bonif Imp. Bonif. Subtotal"
)
ITEMS_HEADER_A = (
    "Código Producto / Servicio Cantidad U. medida Precio Unit. % Bonif Subtotal Subtotal c/IVA"
)


def extract_one(row, header=ITEMS_HEADER_A, default_rate=Decimal("21")):
    """Run the extractor over a single row and hand back the line it produced."""
    lines = _extract_items(_ARCA, [header, row], default_rate)

    assert len(lines) == 1
    return lines[0]


@pytest.mark.parametrize("unit", ["unidades", "horas", "kilogramos", "docenas", "metros"])
def test_a_line_is_read_whatever_its_unit_of_measure(unit):
    """ARCA offers more units than "unidades", and the old pattern hardcoded it.

    A line billed in hours matched nothing, so it vanished from the draft without any
    signal — the worst possible failure for an invoice.
    """
    row = f"Honorarios profesionales 10,00 {unit} 15000,00 0,00 0,00 150000,00"

    line = extract_one(row, header=ITEMS_HEADER_BC)

    assert line.description == "Honorarios profesionales"
    assert line.quantity == Decimal("10.00")
    assert line.unit_price == Decimal("15000.00")


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("21%", Decimal("21")),
        ("10,5%", Decimal("10.5")),
        ("27%", Decimal("27")),
        ("0%", Decimal("0")),
        # The trailing % is not load-bearing: _to_decimal drops whatever is not a digit.
        ("10,50", Decimal("10.5")),
    ],
)
def test_a_type_a_line_takes_its_aliquot_from_the_printed_column(printed, expected):
    """In A the IVA is discriminated per line, so it has to be read, not deduced.

    `default_rate` stays 21 on purpose: were the column being ignored, every case
    would come back 21 and only the 21% one would pass.
    """
    row = f"Servicio 1,00 unidades 100000,00 0,00 100000,00 {printed} 121000,00"

    assert extract_one(row, default_rate=Decimal("21")).iva_rate == expected


def test_one_type_a_voucher_can_mix_aliquots():
    """The case that deducing the rate from the letter gets wrong.

    A single A invoice may carry a 21% line next to a 10,5% one, so any rule keyed on
    the letter alone returns one plausible number for both.
    """
    rows = [
        ITEMS_HEADER_A,
        "Consultoria 1,00 unidades 100000,00 0,00 100000,00 21% 121000,00",
        "Libros tecnicos 2,00 unidades 15000,00 0,00 30000,00 10,5% 33150,00",
    ]

    lines = _extract_items(_ARCA, rows, Decimal("21"))

    assert [line.iva_rate for line in lines] == [Decimal("21"), Decimal("10.5")]


@pytest.mark.parametrize("default_rate", [Decimal("0"), Decimal("21")])
def test_b_and_c_lines_fall_back_to_the_rate_of_the_letter(default_rate):
    """Three trailing columns means no aliquot column, which is B and C.

    Those vouchers do not discriminate IVA per line, so the letter is the only
    information there is.
    """
    row = "Servicio 1,00 unidades 100000,00 0,00 0,00 100000,00"

    assert extract_one(row, header=ITEMS_HEADER_BC, default_rate=default_rate).iva_rate == (
        default_rate
    )


def test_an_unknown_column_layout_is_skipped_rather_than_guessed():
    """A width we do not recognise drops the line instead of matching it shifted.

    Missing lines are visible — `needs_manual_items` goes true and the editor offers
    manual entry. A line matched against the wrong columns would put some other
    number in the aliquot and look perfectly fine.
    """
    rows = [ITEMS_HEADER_A, "Servicio 1,00 unidades 100,00 0,00 0,00 100,00 21% 121,00 9,00"]

    assert _extract_items(_ARCA, rows, Decimal("21")) == []


def test_a_wrapped_description_folds_into_the_line_above_it():
    """ARCA splits long descriptions across rows; the continuation has no columns."""
    rows = [
        ITEMS_HEADER_BC,
        "Almuerzos consumidos desde el 169,00 unidades 28000,00 0,00 0,00 4732000,00",
        "29/06/26 al 03/07/26 OC 4701183101",
        "Usuario Responsable: Lorena Del",
    ]

    lines = _extract_items(_ARCA, rows, Decimal("21"))

    assert len(lines) == 1
    assert lines[0].description == (
        "Almuerzos consumidos desde el 29/06/26 al 03/07/26 OC 4701183101 "
        "Usuario Responsable: Lorena Del"
    )


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("10.5"), Decimal("21"), Decimal("27")])
def test_every_rate_the_parser_can_produce_has_an_aliquot(rate):
    """The parser hands rates to `IvaAliquot.get_by_rate`, which answers None on a miss.

    Reading 10,5 off an A invoice is only useful if the enum can name it, so this
    catches a drift between what the parser emits and what the schema accepts.
    """
    assert IvaAliquot.get_by_rate(rate) is not None


# --- Las filas del comprobante propio ----------------------------------------
#
# La ida y vuelta de más arriba cubre el caso real. Lo que baja acá directo a
# `_extract_items` son las formas que un impreso propio puede tener y ninguna
# factura de prueba tiene juntas: el encabezado partido en tres renglones, una
# descripción que termina en número y el ancho equivocado.

ITEMS_HEADER_FACTUMOV_A = (
    "PRODUCTO / SERVICIO CANTIDAD PRECIO UNIT. SUBTOTAL ALÍCUOTA IVA SUBTOTAL C/IVA"
)
ITEMS_HEADER_FACTUMOV_BC = "PRODUCTO / SERVICIO CANTIDAD PRECIO UNIT. SUBTOTAL"


def test_a_line_of_our_own_voucher_reads_its_aliquot_from_the_tail():
    rows = [
        ITEMS_HEADER_FACTUMOV_A,
        "Consultoria 1 $ 100.000,00 $ 100.000,00 21% $ 121.000,00",
        "Libros tecnicos 2 $ 15.000,00 $ 30.000,00 10,5% $ 33.150,00",
    ]

    lines = _extract_items(_FACTUMOV, rows, Decimal("21"))

    assert [line.iva_rate for line in lines] == [Decimal("21"), Decimal("10.5")]
    assert [line.unit_price for line in lines] == [Decimal("100000"), Decimal("15000")]


@pytest.mark.parametrize("default_rate", [Decimal("0"), Decimal("21")])
def test_without_the_two_iva_columns_the_letter_decides(default_rate):
    """En B y C la fila termina en el subtotal, y ahí la letra es todo lo que hay."""
    rows = [ITEMS_HEADER_FACTUMOV_BC, "Servicio de soporte 3 $ 28.000,00 $ 84.000,00"]

    lines = _extract_items(_FACTUMOV, rows, default_rate)

    assert [line.iva_rate for line in lines] == [default_rate]


def test_a_description_ending_in_a_number_is_not_taken_for_the_quantity():
    """Lo que separa la descripción de las columnas es el "$" del precio.

    Sin ese ancla, "Instalacion 2" con cantidad 1 se leía como la descripción
    "Instalacion" y la cantidad 2 — una línea plausible y equivocada.
    """
    rows = [ITEMS_HEADER_FACTUMOV_BC, "Instalacion 2 1 $ 35.000,00 $ 35.000,00"]

    lines = _extract_items(_FACTUMOV, rows, Decimal("21"))

    assert [(line.description, line.quantity) for line in lines] == [
        ("Instalacion 2", Decimal("1"))
    ]


def test_the_split_header_does_not_end_up_inside_the_first_description():
    """El encabezado se parte en tres renglones cuando una descripción lo ensancha, y
    el de abajo cae donde caería el principio de una descripción. Se lo distingue
    porque el encabezado va en mayúsculas por CSS y una descripción no."""
    rows = [
        "PRECIO ALÍCUOTA SUBTOTAL C/",
        ITEMS_HEADER_FACTUMOV_A,
        "UNIT. IVA IVA",
        "Servicio integral de mantenimiento preventivo y",
        "correctivo de la red de datos 1 $ 15.000,00 $ 15.000,00 21% $ 18.150,00",
        "con certificacion",
    ]

    lines = _extract_items(_FACTUMOV, rows, Decimal("21"))

    assert [line.description for line in lines] == [
        "Servicio integral de mantenimiento preventivo y correctivo de la red de datos "
        "con certificacion"
    ]


def test_a_row_of_the_other_layout_is_not_matched_by_this_one():
    """Cada layout reconoce solo sus columnas. Una fila de ARCA —sin "$", con unidad
    de medida— no es una fila de acá, y matchearla corrida pondría la bonificación en
    el precio."""
    rows = [ITEMS_HEADER_FACTUMOV_BC, "Servicio 1,00 unidades 100000,00 0,00 0,00 100000,00"]

    assert _extract_items(_FACTUMOV, rows, Decimal("21")) == []


# --- Los números, que no vienen escritos igual en los dos generadores --------


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("2.805.000,00", Decimal("2805000")),
        ("35000,00", Decimal("35000")),
        ("$ 15.000,00", Decimal("15000")),
        ("10,5%", Decimal("10.5")),
        # Balance360 imprime la alícuota sin pasarla por ningún formateador, así que
        # sale el Decimal crudo de una columna `Numeric(5, 2)`: punto decimal inglés.
        # Con la regla argentina a secas esto se leía 1050 y no había alícuota con esa
        # tasa, o sea que toda factura A de Balance360 perdía el IVA de sus líneas.
        ("10.50", Decimal("10.5")),
        ("21.00", Decimal("21")),
        # Tres cifras después del punto siguen siendo miles: 1.500 es mil quinientos.
        ("1.500", Decimal("1500")),
        ("", None),
    ],
)
def test_an_amount_is_read_in_both_the_argentine_and_the_raw_form(printed, expected):
    assert _to_decimal(printed) == expected
