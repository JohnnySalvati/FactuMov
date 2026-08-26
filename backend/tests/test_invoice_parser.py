"""Tests for the ARCA "Comprobantes en línea" parser.

Two kinds of test live here, and the difference matters. The parametrised cases at
the top read the real PDFs in `samples/`. The ones at the bottom feed hand-written
rows straight into `_extract_items`, to reach the rates no sample carries.

`samples/` holds only documents this parser is meant to read, which today means one
layout: ARCA "Comprobantes en línea". A PDF from a different generator belongs in
`samples/unsupported/`, which the glob below does not descend into. That folder is
gitignored, so nothing in the code can enforce the split — it is a sibling folder
rather than a name skipped in a list so that filing a PDF in the wrong place is a
visible mistake, not a red test nobody expected.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from factumov.enums import DocType, IvaAliquot, VoucherType
from factumov.services.invoice_parser import _extract_items, parse_invoice_pdf

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
    """A floor under all ten PDFs, so a regex change cannot quietly empty one out.

    The named cases above pin exact values for three of them; this one only asserts
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
    lines = _extract_items([header, row], default_rate)

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

    lines = _extract_items(rows, Decimal("21"))

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

    assert _extract_items(rows, Decimal("21")) == []


def test_a_wrapped_description_folds_into_the_line_above_it():
    """ARCA splits long descriptions across rows; the continuation has no columns."""
    rows = [
        ITEMS_HEADER_BC,
        "Almuerzos consumidos desde el 169,00 unidades 28000,00 0,00 0,00 4732000,00",
        "29/06/26 al 03/07/26 OC 4701183101",
        "Usuario Responsable: Lorena Del",
    ]

    lines = _extract_items(rows, Decimal("21"))

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
