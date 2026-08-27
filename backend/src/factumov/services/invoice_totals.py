"""Los importes de un comprobante: neto, IVA y total, discriminados por alícuota.

Port de `Invoice.iva_breakdown` de Balance360, sacado del modelo ORM y puesto en un servicio
que recibe datos planos. Es lógica pura y la necesitan tres lugares que no comparten tipo: el
request a WSFE (que arma un dict), el `Invoice` guardado (que es ORM) y el PDF (que va a
recibir el que se guardó). Colgarla del modelo la habría atado al último.

**La regla de fondo es la convención del proyecto: en A el precio va neto y en B y C ya viene
con el IVA adentro.** No es una decisión de este módulo — es la misma que usa el parser al
leer un PDF, y la misma que aplica el total del editor en el frontend. El precio se guarda tal
como se carga y la letra decide cómo interpretarlo.

**Redondeo: se redondea cada subtotal por alícuota, y recién después se suma.** ARCA valida
que `ImpTotal == ImpNeto + ImpIVA + ImpTrib + ImpOpEx + ImpTotConc` con dos decimales
exactos, así que el orden importa: sumar en alta precisión y redondear al final produce
diferencias de un centavo que WSFE rechaza con un error que no nombra el redondeo por ningún
lado. Cada `AlicIva` que se manda tiene que cerrar contra el total, y por eso el total sale de
sumar los redondeados y no al revés.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from factumov.enums import IvaAliquot, VoucherType

_CENTS = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Redondea a dos decimales, medio hacia arriba.

    `ROUND_HALF_UP` y no el `ROUND_HALF_EVEN` que Python trae por default: el banquero es
    mejor estadísticamente pero no es lo que hace ninguna calculadora ni lo que espera nadie
    mirando una factura, y una diferencia de un centavo contra lo que el cliente calculó a
    mano es una llamada telefónica.
    """
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineAmounts:
    """Lo mínimo que hace falta de una línea para calcular. No es un schema ni un modelo.

    Recibe cantidad y precio en vez del importe ya multiplicado para que el redondeo del
    producto ocurra en un solo lugar.
    """

    quantity: Decimal
    unit_price: Decimal
    iva_aliquot: IvaAliquot

    @property
    def amount(self) -> Decimal:
        """El importe de la línea **tal como se carga**, sin decidir si el IVA está adentro."""
        return money(self.quantity * self.unit_price)


@dataclass(frozen=True)
class AliquotSubtotal:
    aliquot: IvaAliquot
    net: Decimal
    iva: Decimal


@dataclass(frozen=True)
class InvoiceTotals:
    """Lo que se le manda a ARCA y lo que se guarda en la factura.

    `breakdown` va vacío cuando la letra no aplica IVA (la C). No es "no hay líneas": es que
    no hay nada que discriminar, y es exactamente la condición que decide si el request lleva
    el array `Iva` o no.
    """

    net: Decimal
    iva: Decimal
    total: Decimal
    breakdown: list[AliquotSubtotal]


def compute_totals(voucher_type: VoucherType, lines: list[LineAmounts]) -> InvoiceTotals:
    """Neto, IVA y total de un comprobante de esa letra con esas líneas.

    Las tres ramas son las tres formas en que la letra cambia la lectura del precio:

    - **A** — el precio es neto y el IVA se suma encima.
    - **B** — el precio ya trae el IVA; el neto sale de dividir por `1 + alícuota`. Aunque la
      B no imprima el IVA, ARCA igual exige el desglose: el comprobante no lo discrimina de
      cara al cliente, pero sí lo declara.
    - **C** — no hay IVA. El neto es el importe y listo, sin importar qué alícuota tenga
      cargada la línea. Eso último es deliberado: un modelo que quedó con 21% de cuando el
      emisor era responsable inscripto no puede inventarle IVA a una factura C.
    """
    subtotals: dict[IvaAliquot, tuple[Decimal, Decimal]] = {}
    for line in lines:
        net, iva = subtotals.get(line.iva_aliquot, (Decimal(0), Decimal(0)))
        amount = line.amount
        if not voucher_type.applies_iva:
            line_net, line_iva = amount, Decimal(0)
        elif voucher_type.discriminates_iva:
            line_net = amount
            line_iva = money(amount * line.iva_aliquot.rate / 100)
        else:
            line_net = money(amount / (1 + line.iva_aliquot.rate / 100))
            line_iva = amount - line_net
        subtotals[line.iva_aliquot] = (net + line_net, iva + line_iva)

    breakdown = [
        AliquotSubtotal(aliquot=aliquot, net=net, iva=iva)
        for aliquot, (net, iva) in subtotals.items()
    ]
    net_total = sum((item.net for item in breakdown), Decimal(0))
    iva_total = sum((item.iva for item in breakdown), Decimal(0))
    return InvoiceTotals(
        net=net_total,
        iva=iva_total,
        total=net_total + iva_total,
        # Vacío cuando no aplica IVA: es lo que le dice al request de WSFE que no mande `Iva`.
        breakdown=breakdown if voucher_type.applies_iva else [],
    )
