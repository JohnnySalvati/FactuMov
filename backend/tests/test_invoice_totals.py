"""Los importes de un comprobante — `services/invoice_totals.py`.

Es aritmética pura, sin base ni red, y es de lo más barato de testear y de lo más caro de
tener mal: un centavo de diferencia entre `ImpTotal` y la suma de sus partes es un rechazo de
WSFE con un mensaje que no nombra el redondeo por ningún lado.

Los tres bloques son las tres lecturas del precio que impone la letra: en A es neto, en B ya
trae el IVA adentro, y en C no hay IVA. Los números están elegidos para que se puedan
verificar de cabeza.
"""

from decimal import Decimal

import pytest

from factumov.enums import IvaAliquot, VoucherType
from factumov.services.invoice_totals import LineAmounts, compute_totals, money


def line(quantity="1", unit_price="100", iva_aliquot=IvaAliquot.standard):
    return LineAmounts(
        quantity=Decimal(quantity), unit_price=Decimal(unit_price), iva_aliquot=iva_aliquot
    )


# --- A: el precio es neto y el IVA se suma encima -----------------------------------------


def test_a_adds_the_iva_on_top():
    """35000 × 1,21 = 42350, que es el número de la muestra A de `tests/samples/`."""
    totals = compute_totals(VoucherType.A, [line(unit_price="35000")])

    assert totals.net == Decimal("35000.00")
    assert totals.iva == Decimal("7350.00")
    assert totals.total == Decimal("42350.00")


def test_a_keeps_one_subtotal_per_aliquot():
    """Una misma factura A puede mezclar 21% y 10,5%, y ARCA quiere un `AlicIva` por cada una."""
    totals = compute_totals(
        VoucherType.A,
        [
            line(unit_price="1000", iva_aliquot=IvaAliquot.standard),
            line(unit_price="1000", iva_aliquot=IvaAliquot.reduced),
        ],
    )

    assert {item.aliquot for item in totals.breakdown} == {
        IvaAliquot.standard,
        IvaAliquot.reduced,
    }
    assert totals.iva == Decimal("315.00")  # 210 + 105


def test_a_groups_lines_that_share_an_aliquot():
    """Dos líneas al 21% son **un** `AlicIva`, no dos: ARCA los quiere agrupados."""
    totals = compute_totals(VoucherType.A, [line(unit_price="1000"), line(unit_price="500")])

    assert len(totals.breakdown) == 1
    assert totals.breakdown[0].net == Decimal("1500.00")


# --- B: el precio ya trae el IVA adentro ---------------------------------------------------


def test_b_extracts_the_iva_from_the_price():
    """121 con IVA incluido son 100 de neto y 21 de IVA."""
    totals = compute_totals(VoucherType.B, [line(unit_price="121")])

    assert totals.net == Decimal("100.00")
    assert totals.iva == Decimal("21.00")
    assert totals.total == Decimal("121.00")


def test_b_still_declares_the_breakdown():
    """La B no **imprime** el IVA, pero sí lo declara: sin el array `Iva`, ARCA rechaza."""
    totals = compute_totals(VoucherType.B, [line(unit_price="121")])

    assert len(totals.breakdown) == 1


def test_b_total_is_exactly_what_was_charged():
    """El total de una B es la suma de los precios tipeados, sin que el redondeo lo mueva.

    Es la propiedad que más fácil se rompe: el neto de 100,01 al 21% no es exacto, así que
    net + iva podría no dar 100,01 si se redondeara mal.
    """
    totals = compute_totals(VoucherType.B, [line(unit_price="100.01")])

    assert totals.total == Decimal("100.01")


# --- C: no hay IVA -------------------------------------------------------------------------


def test_c_has_no_iva_at_all():
    totals = compute_totals(VoucherType.C, [line(unit_price="1000")])

    assert totals.net == Decimal("1000.00")
    assert totals.iva == Decimal("0")
    assert totals.total == Decimal("1000.00")


def test_c_ignores_the_aliquot_left_on_the_line():
    """Un modelo que quedó al 21% de cuando el emisor era inscripto no le inventa IVA a una C.

    Pasa de verdad: el monotributista que se inscribe, o al revés. La alícuota de la línea es
    un dato del modelo; la que manda es la letra.
    """
    totals = compute_totals(VoucherType.C, [line(unit_price="1000")])

    assert totals.iva == Decimal("0")


def test_c_sends_no_breakdown():
    """En una C, mandar `Iva` —aunque sea con alícuota 0— es un rechazo de ARCA."""
    totals = compute_totals(VoucherType.C, [line(unit_price="1000")])

    assert totals.breakdown == []


# --- Lo que ARCA valida --------------------------------------------------------------------


@pytest.mark.parametrize(
    "voucher_type", [VoucherType.A, VoucherType.B, VoucherType.C], ids=lambda v: v.value
)
@pytest.mark.parametrize(
    "prices",
    [["0.01"], ["33.33", "33.33", "33.33"], ["1234.56", "7.77"], ["999999.99"]],
    ids=["un_centavo", "tres_tercios", "mezcla", "grande"],
)
def test_the_total_always_equals_net_plus_iva(voucher_type, prices):
    """La invariante que ARCA chequea: `ImpTotal == ImpNeto + ImpIVA` con dos decimales.

    Es el motivo por el que se redondea cada subtotal por alícuota antes de sumar. Sumando en
    alta precisión y redondeando al final, algunos de estos casos se van un centavo — y el
    rechazo de WSFE no dice nada del redondeo.
    """
    totals = compute_totals(voucher_type, [line(unit_price=price) for price in prices])

    assert totals.total == totals.net + totals.iva
    assert totals.total == money(totals.total)


@pytest.mark.parametrize("voucher_type", [VoucherType.A, VoucherType.B], ids=lambda v: v.value)
def test_the_breakdown_adds_up_to_the_totals(voucher_type):
    """Cada `AlicIva` tiene que cerrar contra `ImpNeto` e `ImpIVA`, o ARCA rechaza."""
    totals = compute_totals(
        voucher_type,
        [
            line(unit_price="333.33", iva_aliquot=IvaAliquot.standard),
            line(unit_price="77.77", iva_aliquot=IvaAliquot.reduced),
            line(unit_price="10.10", iva_aliquot=IvaAliquot.standard),
        ],
    )

    assert sum(item.net for item in totals.breakdown) == totals.net
    assert sum(item.iva for item in totals.breakdown) == totals.iva


def test_fractional_quantities_are_rounded_per_line():
    """El parser captura cantidades como `2,50`, y horas o kilos dan importes con fracción."""
    totals = compute_totals(
        VoucherType.C, [LineAmounts(Decimal("2.5"), Decimal("33.33"), IvaAliquot.exempt)]
    )

    assert totals.total == Decimal("83.33")  # 83,325 → medio hacia arriba


def test_money_rounds_half_up_and_not_half_even():
    """`ROUND_HALF_UP` es lo que hace cualquier calculadora; el banquero sorprende."""
    assert money(Decimal("0.125")) == Decimal("0.13")
    assert money(Decimal("0.135")) == Decimal("0.14")
