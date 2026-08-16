from decimal import Decimal
from pathlib import Path

import pytest

from factumov.services.invoice_parser import parse_invoice_pdf


@pytest.mark.parametrize(
    "file, data",
    [
        (
            "20206205297_011_00001_00000205.pdf",
            {
                "voucher_type": "C",
                "pos": int(1),
                "number": int(205),
                "customer_doc_type": "CUIT",
                "customer_doc_number": "30714597066",
                "number_of_lines": 1,
                "customer_address": "Ibera 4947 - Capital Federal, Ciudad de Buenos Aires",
                "first_line_unit_price": Decimal(2805000),
            },
        ),
        (
            "20206205297_011_00001_00000207.pdf",
            {
                "voucher_type": "C",
                "pos": int(1),
                "number": int(207),
                "customer_doc_type": "CUIT",
                "customer_doc_number": "30714455113",
                "number_of_lines": 1,
                "customer_address": "Rivadavia M. Cdro. 1350 - "
                + "Capital Federal, Ciudad de Buenos Aires",
                "first_line_unit_price": Decimal(1520000),
            },
        ),
        (
            "30714597066_006_00010_00000055.pdf",
            {
                "voucher_type": "B",
                "pos": int(10),
                "number": int(55),
                "customer_doc_type": "CUIT",
                "customer_doc_number": "30535621159",
                "number_of_lines": 2,
                "customer_address": "Cazadores De Coquimbo 2841 Piso:2 - Munro, Buenos Aires",
                "first_line_unit_price": Decimal(28000),
            },
        ),
    ],
)
def test_invoice_parser(file, data):
    file_bytes = (Path(__file__).parent / "samples" / file).read_bytes()

    parsed = parse_invoice_pdf(file_bytes)

    assert data["voucher_type"] == parsed.voucher_type
    assert data["pos"] == parsed.pos
    assert data["number"] == parsed.number
    assert data["customer_doc_type"] == parsed.customer_doc_type
    assert data["customer_doc_number"] == parsed.customer_doc_number
    assert data["number_of_lines"] == len(parsed.lines)
    assert data["customer_address"] == parsed.customer_address
    assert data["first_line_unit_price"] == parsed.lines[0].unit_price
