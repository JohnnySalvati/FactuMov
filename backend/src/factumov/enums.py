from decimal import Decimal
from enum import Enum


class VoucherType(Enum):
    """La letra del comprobante, con el código con el que ARCA la nombra.

    El `arca_code` viaja en `CbteTipo` de WSFE y adentro del QR fiscal. Se agrega como
    atributo y no como valor —igual que `rate` en `IvaAliquot`, y al revés que ahí— para que
    `.value` siga siendo la letra: es lo que guarda la columna, lo que serializa Pydantic y
    lo que espera `types.ts`. Cambiar el valor por el número habría sido una migración y un
    cambio de contrato de la API a cambio de nada.
    """

    A = ("A", 1)
    B = ("B", 6)
    C = ("C", 11)
    NCA = ("NCA", 3)
    NCB = ("NCB", 8)
    NCC = ("NCC", 13)

    arca_code: int

    def __new__(cls, value: str, arca_code: int) -> "VoucherType":
        member = object.__new__(cls)
        member._value_ = value
        member.arca_code = arca_code
        return member

    @classmethod
    def get_by_arca_code(cls, arca_code: int) -> "VoucherType | None":
        """El tipo que ARCA nombra con ese código, o `None` si no es uno que FactuMov maneje.

        `None` para las notas de débito, los recibos y todo lo demás: mejor sin tipo que con
        uno incorrecto. Antes esto era una tabla propia en `invoice_parser.py`, escrita al
        revés; con el código adentro del enum, la inversa se deduce y no hay dos listas que
        puedan discrepar.
        """
        return next((member for member in cls if member.arca_code == arca_code), None)

    @property
    def discriminates_iva(self) -> bool:
        """¿El comprobante muestra el IVA en una columna aparte?

        Solo la A. Es lo que decide cómo se lee `unit_price`: en A el precio va **neto** y el
        IVA se suma; en B y C el precio ya viene con el IVA adentro. Misma convención que usa
        el parser al leer un PDF — ver CLAUDE.md → *Parser*.
        """
        return self in (VoucherType.A, VoucherType.NCA)

    @property
    def applies_iva(self) -> bool:
        """¿Hay IVA en juego?

        En la C no: la emite un monotributista o un exento, que no liquidan IVA. Por eso a
        ARCA se le manda `ImpNeto == ImpTotal`, `ImpIVA = 0` y **sin** array `Iva` — mandarlo
        con alícuota 0 es un rechazo.
        """
        return self in (VoucherType.A, VoucherType.NCA, VoucherType.B, VoucherType.NCB)


class IvaAliquot(Enum):
    exempt = (3, Decimal("0"))
    reduced = (4, Decimal("10.5"))
    standard = (5, Decimal("21"))
    higher = (6, Decimal("27"))

    rate: Decimal

    def __new__(cls, arca_code: int, rate: Decimal) -> "IvaAliquot":
        member = object.__new__(cls)
        member._value_ = arca_code
        member.rate = rate
        return member

    @classmethod
    def get_by_rate(cls, rate: Decimal) -> "IvaAliquot | None":
        return next(
            (aliquot for aliquot in cls if rate == aliquot.rate),
            None,
        )


class Concepto(Enum):
    """Qué se factura, con el código que ARCA usa en `Concepto`.

    Mismo truco que `VoucherType`: el valor sigue siendo el string, que es lo que guarda la
    columna y lo que viaja en el JSON.

    Todo lo que no sea `products` obliga a mandar el período del servicio
    (`FchServDesde`/`Hasta`) y el vencimiento del pago — ver `services/wsfe.py`.
    """

    products = ("products", 1)
    services = ("services", 2)
    both = ("both", 3)

    arca_code: int

    def __new__(cls, value: str, arca_code: int) -> "Concepto":
        member = object.__new__(cls)
        member._value_ = value
        member.arca_code = arca_code
        return member

    @property
    def needs_service_dates(self) -> bool:
        return self is not Concepto.products


class DocType(Enum):
    CUIT = 80
    CUIL = 86
    DNI = 96


class CondicionIva(Enum):
    """Condición frente al IVA, con el código de `CondicionIVAReceptorId` de WSFE.

    **Los valores salen de la tabla de ARCA, verificados contra `FEParamGetCondicionIvaReceptor`
    el 2026-08-27.** Hasta ese día `FINAL` valía 6 y `MONOTRIBUTO` valía 13, heredados de
    Balance360, y los dos estaban mal: para ARCA el 6 es "Responsable Monotributo" y el 13 es
    "Monotributista Social", que es otra categoría. O sea que el nombre y el código decían
    cosas distintas.

    No era teórico. Con `FINAL = 6`, emitir una factura B a un consumidor final —el caso más
    común que hay, y la mitad de las facturas B de `tests/samples/`— la rechazaba ARCA con el
    código 10243, porque "Responsable Monotributo" no es un receptor válido para una B.
    Corregido a 5, ARCA la autoriza.

    El cambio **no toca la base**: la columna guarda el nombre del miembro (`Enum(CondicionIva)`
    sin `values_callable`), no su valor. Lo que sí cambia es el número que viaja en el JSON,
    así que `api/types.ts` va de la mano.
    """

    INSCRIPTO = 1
    EXENTO = 4
    # 5 es "Consumidor Final". El 6 —que estaba acá antes— es "Responsable Monotributo".
    FINAL = 5
    # 6 es "Responsable Monotributo". El 13 —que estaba acá antes— es "Monotributista Social",
    # una categoría distinta y mucho más chica.
    MONOTRIBUTO = 6


class SubscriptionStatus(Enum):
    """En qué anda la relación comercial con el usuario.

    **No hay miembro `FREE`, y esa ausencia es la decisión de diseño de la tabla.** Free no es
    un estado de la suscripción: es lo que queda cuando ninguno de estos cuatro está vigente.
    Guardarlo como un quinto miembro haría que el plan efectivo estuviera escrito en dos
    lugares —el estado y la fecha de vencimiento— capaces de contradecirse, que es el mismo
    problema por el que `voucher_type` dejó de ser columna en `invoice_templates`. Acá se
    deduce: ver `services/subscription.py`.

    `PAST_DUE` no corta el acceso. Es el estado en el que queda una suscripción cuyo cobro
    falló, y durante la gracia el usuario sigue siendo Pro: las tarjetas se vencen y se
    reemiten todo el tiempo, y cortar al primer rechazo pierde clientes que sí querían pagar.

    `CANCELED` tampoco corta el acceso por sí solo. El que da de baja el 3 y tenía pagado
    hasta el 28 sigue siendo Pro hasta el 28: ya lo pagó. Lo que `CANCELED` significa es que
    no se va a renovar.
    """

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class BillingInterval(Enum):
    """Cada cuánto se cobra. `None` en la columna es el trial, que no se cobra."""

    MONTHLY = "monthly"
    YEARLY = "yearly"


class BillingProvider(Enum):
    """Por dónde entró la plata.

    `MANUAL` es la transferencia bancaria, que se concilia a mano y solo se ofrece para el
    plan anual: no renueva sola, así que como cobro mensual sería un recordatorio por mes y
    una baja por olvido. `MERCADO_PAGO` es el camino normal, con débito automático.
    """

    MERCADO_PAGO = "mercado_pago"
    MANUAL = "manual"


class Balance360Status(Enum):
    """En qué anda la copia de una factura emitida hacia Balance360.

    `NULL` en la columna es un cuarto estado y el más común: la factura se emitió sin que el
    usuario tuviera la integración conectada, así que nunca entró al circuito. No es
    `FAILED` —no falló nada— ni `PENDING` —no hay nada esperando—, y la pantalla no muestra
    ningún indicador. Que sea la ausencia de valor y no un miembro más deja además la
    consulta de reintentos ("todas las `FAILED`") sin arrastrar las viejas.

    `PENDING` es el estado en el que la factura sale de `/emit`: el registro ocurre después
    y desacoplado, así que entre el CAE y la copia hay una ventana real, no instantánea.
    """

    PENDING = "pending"
    REGISTERED = "registered"
    FAILED = "failed"
