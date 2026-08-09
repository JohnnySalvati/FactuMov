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

    def __init__(self, arca_code: int, rate: Decimal):
        self.arca_code = arca_code
        self.rate = rate


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
