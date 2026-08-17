from decimal import Decimal
from enum import Enum


class VoucherType(Enum):
    A = "A"
    B = "B"
    C = "C"
    NCA = "NCA"
    NCB = "NCB"
    NCC = "NCC"


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
    products = "products"
    services = "services"
    both = "both"


class DocType(Enum):
    CUIT = 80
    CUIL = 86
    DNI = 96
    FINAL = 99


class CondicionIva(Enum):
    INSCRIPTO = 1
    EXENTO = 4
    FINAL = 6
    MONOTRIBUTO = 13
