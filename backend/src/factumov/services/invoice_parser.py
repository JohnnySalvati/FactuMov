"""Parser de facturas generadas por Comprobantes en línea de ARCA.

Devuelve un ParsedInvoice; los campos que no se encuentran quedan en None.

Deriva de `services/pdf_invoice.py` de Balance360, con dos diferencias de fondo:

1. Allí se leían facturas de terceros, así que solo interesaba el emisor. Acá el
   emisor es el propio usuario y el dato que hace falta es el receptor: se
   extraen los dos.
2. Balance360 soporta diez layouts de distintos sistemas de facturación. Acá hay
   uno solo, el de ARCA, porque es el único del que tenemos muestras. Un layout
   que no se puede verificar contra un PDF real es un pasivo, no una función.

Lógica pura: sin base de datos, sin red.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


@dataclass
class ParsedInvoiceLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    iva_rate: Decimal


@dataclass
class ParsedInvoice:
    voucher_type: str | None = None
    pos: int | None = None
    number: int | None = None
    date: datetime.date | None = None
    issuer_cuit: str | None = None
    issuer_name: str | None = None
    issuer_condicion_iva: str | None = None
    issuer_address: str | None = None
    issuer_iibb: str | None = None
    issuer_start_date: datetime.date | None = None
    customer_doc_type: str | None = None
    customer_doc_number: str | None = None
    customer_name: str | None = None
    customer_condicion_iva: str | None = None
    customer_address: str | None = None
    from_date: datetime.date | None = None
    to_date: datetime.date | None = None
    due_date: datetime.date | None = None
    cae: str | None = None
    lines: list[ParsedInvoiceLine] = field(default_factory=list)
    # True cuando el PDF no tiene texto extraíble (escaneado) o no se reconoció
    # ninguna línea: la UI debería ofrecer carga manual de los items.
    needs_manual_items: bool = False


# Código de comprobante de ARCA -> tipo. Solo los que FactuMov emite; cualquier
# otro (notas de débito, recibos) queda en None a propósito: mejor sin tipo que
# con uno incorrecto.
_ARCA_VOUCHER_TYPE: dict[int, str] = {
    1: "A",
    3: "NCA",
    6: "B",
    8: "NCB",
    11: "C",
    13: "NCC",
}

# ARCA no imprime la alícuota por línea, así que se deduce de la letra.
# En B el precio impreso ya incluye el IVA; quien arme la factura decide cómo
# interpretarlo, igual que hace Balance360 en Invoice.iva_breakdown.
_IVA_BY_LETTER: dict[str, Decimal] = {
    "A": Decimal("21"),
    "B": Decimal("21"),
    "C": Decimal("0"),
}

# El orden importa: "Responsable Monotributo" e "IVA Responsable Inscripto"
# comparten la palabra "Responsable".
_CONDICION_IVA: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"monotributo", re.I), "MONOTRIBUTO"),
    (re.compile(r"exento", re.I), "EXENTO"),
    (re.compile(r"consumidor\s+final", re.I), "FINAL"),
    (re.compile(r"responsable\s+inscripto", re.I), "INSCRIPTO"),
)

_COD = re.compile(r"^COD\.\s*0*(\d{1,3})\s*$", re.M)
_POS_NUMBER = re.compile(r"Punto de Venta:\s*0*(\d+)\s+Comp\.\s*Nro:\s*0*(\d+)")
_DATE = re.compile(r"Fecha de Emisi[oó]n:\s*(\d{2}/\d{2}/\d{4})")
_CAE = re.compile(r"CAE\s*N[°º]?\.?\s*:\s*(\d{14})")

_ISSUER_NAME = re.compile(r"Raz[oó]n Social:\s*(.+?)\s+Fecha de Emisi[oó]n:")
_ISSUER_CUIT = re.compile(r"CUIT:\s*(\d{11})")
_ISSUER_CONDICION = re.compile(r"Condici[oó]n frente al IVA:\s*(.+?)\s+Fecha de Inicio")
_ISSUER_ADDRESS = re.compile(r"Domicilio Comercial:\s*(.+?)\s+CUIT:")
_ISSUER_IIBB = re.compile(r"Ingresos Brutos:\s*(\S+)")
_ISSUER_START = re.compile(r"Fecha de Inicio de Actividades:\s*(\d{2}/\d{2}/\d{4})")

# El domicilio del emisor puede seguir en la línea de abajo, que arrastra
# pegado el "Ingresos Brutos:" del renglón siguiente.
_ISSUER_ADDRESS_TAIL = re.compile(r"^(.+?)\s+Ingresos Brutos:")

# El receptor ocupa dos líneas seguidas. El documento puede ser CUIT, CUIL o
# DNI: hardcodear CUIT hacía que las facturas a consumidor final quedaran sin
# receptor. El nombre usa `.*?` y no `.+?` porque puede venir vacío.
_CUSTOMER = re.compile(
    r"(?P<doc_type>CUIT|CUIL|DNI):\s*(?P<doc_number>\d+)\s+"
    r"Apellido y Nombre\s*/\s*Raz[oó]n Social:\s*(?P<name>.*?)\s*$",
    re.M,
)
# Se distingue de la línea del emisor porque lleva "Domicilio:" en vez de
# "Fecha de Inicio de Actividades:".
_CUSTOMER_CONDICION = re.compile(r"Condici[oó]n frente al IVA:\s*(.+?)\s+Domicilio:\s*(.+?)\s*$")

# Una línea que empieza con alguna de estas etiquetas abre otro campo, así que
# nunca es la continuación de un domicilio partido en dos renglones.
_NEXT_FIELD = re.compile(
    r"^(Condici[oó]n\b|C[oó]digo\s+Producto|Per[ií]odo\b|CUIT:|CUIL:|DNI:|Domicilio)", re.I
)

_PERIOD = re.compile(
    r"Per[ií]odo Facturado Desde:\s*(\d{2}/\d{2}/\d{4})\s+"
    r"Hasta:\s*(\d{2}/\d{2}/\d{4})\s+"
    r"Fecha de Vto\.\s*para el pago:\s*(\d{2}/\d{2}/\d{4})"
)

# Columnas de ARCA: Cantidad | U. Medida | Precio Unit. | % Bonif | Imp. Bonif. |
# Subtotal. No hay columna de IVA, y esa es justamente la razón por la que el
# layout "arca" de Balance360 no reconocía ninguna línea de estas facturas.
_NUM = r"[\d.,]+"
_ITEMS_HEADER = re.compile(r"C[oó]digo\s+Producto\s*/\s*Servicio\s+Cantidad\s+U\.\s*Medida", re.I)
_ITEM_ROW = re.compile(
    rf"^(?P<desc>.+?)\s+(?P<qty>{_NUM})\s+unidades\s+(?P<price>{_NUM})"
    rf"\s+{_NUM}\s+{_NUM}\s+{_NUM}\s*$"
)
_ITEMS_END = re.compile(r"^\s*(Subtotal:|Importe|R[eé]gimen|P[aá]g\.|CAE\b)", re.I)


def _strip_extra_copies(text: str) -> str:
    """Deja solo la primera copia de la factura.

    ARCA imprime la misma factura tres veces —ORIGINAL, DUPLICADO, TRIPLICADO—
    en un único PDF. Con las tres en el texto, cualquier extracción encuentra
    tres de cada cosa. Cortar en el primer DUPLICADO deja una sola factura y
    hace que todo lo de abajo sea seguro por construcción.
    """
    marker = re.search(r"^\s*DUPLICADO\s*$", text, re.M)
    return text[: marker.start()] if marker else text


def _parse_date(value: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _to_decimal(value: str | None) -> Decimal | None:
    """Convierte '2.805.000,00' o '2805000,00' a Decimal.

    ARCA siempre imprime en formato argentino: '.' agrupa miles y ',' separa
    decimales. Balance360 tenía que adivinar entre formato argentino y
    norteamericano porque leía facturas de cualquier proveedor; acá hay un solo
    emisor de PDFs, así que la ambigüedad no existe.
    """
    if value is None:
        return None
    cleaned = re.sub(r"[^\d,.-]", "", value.strip())
    if not cleaned:
        return None
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _condicion_iva(raw: str | None) -> str | None:
    if not raw:
        return None
    for pattern, value in _CONDICION_IVA:
        if pattern.search(raw):
            return value
    return None


def _find_line(lines: list[str], pattern: re.Pattern[str]) -> tuple[int, re.Match[str]] | None:
    for index, line in enumerate(lines):
        match = pattern.search(line)
        if match:
            return index, match
    return None


def _wrapped_tail(lines: list[str], index: int) -> str:
    """Junta las líneas siguientes que son continuación del campo de `index`."""
    parts: list[str] = []
    for line in lines[index + 1 :]:
        stripped = line.strip()
        if not stripped or _NEXT_FIELD.match(stripped):
            break
        parts.append(stripped)
    return " ".join(parts)


def _extract_items(lines: list[str], iva_rate: Decimal) -> list[ParsedInvoiceLine]:
    result: list[ParsedInvoiceLine] = []
    in_items = False

    for raw_line in lines:
        line = raw_line.strip()

        if not in_items:
            if _ITEMS_HEADER.search(line):
                in_items = True
            continue

        if not line:
            continue
        if _ITEMS_END.match(line):
            break

        match = _ITEM_ROW.match(line)
        if match:
            quantity = _to_decimal(match.group("qty"))
            unit_price = _to_decimal(match.group("price"))
            if quantity is None or unit_price is None:
                continue
            description = re.sub(r"\s+", " ", match.group("desc").strip())
            result.append(ParsedInvoiceLine(description, quantity, unit_price, iva_rate))
        elif result:
            # La descripción puede continuar en las líneas de abajo:
            # "Almuerzos consumidos desde el" / "29/06/26 al 03/07/26 ...".
            result[-1].description = re.sub(r"\s+", " ", f"{result[-1].description} {line}")

    return result


def _extract_issuer(result: ParsedInvoice, lines: list[str], zone: str) -> None:
    issuer_name = _ISSUER_NAME.search(zone)
    if issuer_name:
        result.issuer_name = issuer_name.group(1).strip()

    issuer_cuit = _ISSUER_CUIT.search(zone)
    if issuer_cuit:
        result.issuer_cuit = issuer_cuit.group(1)

    issuer_condicion = _ISSUER_CONDICION.search(zone)
    if issuer_condicion:
        result.issuer_condicion_iva = _condicion_iva(issuer_condicion.group(1))

    issuer_iibb = _ISSUER_IIBB.search(zone)
    if issuer_iibb:
        result.issuer_iibb = issuer_iibb.group(1)

    issuer_start = _ISSUER_START.search(zone)
    if issuer_start:
        result.issuer_start_date = _parse_date(issuer_start.group(1))

    found = _find_line(lines, _ISSUER_ADDRESS)
    if found:
        index, match = found
        address = match.group(1).strip()
        if index + 1 < len(lines):
            tail = _ISSUER_ADDRESS_TAIL.match(lines[index + 1].strip())
            if tail:
                address = f"{address} {tail.group(1).strip()}"
        result.issuer_address = address


def _extract_customer(result: ParsedInvoice, lines: list[str]) -> None:
    found = _find_line(lines, _CUSTOMER)
    if found:
        _, match = found
        result.customer_doc_type = match.group("doc_type")
        result.customer_doc_number = match.group("doc_number")
        result.customer_name = match.group("name").strip() or None

    found = _find_line(lines, _CUSTOMER_CONDICION)
    if found:
        index, match = found
        result.customer_condicion_iva = _condicion_iva(match.group(1))
        address = match.group(2).strip()
        tail = _wrapped_tail(lines, index)
        result.customer_address = f"{address} {tail}".strip() if tail else address


def parse_invoice_pdf(file_bytes: bytes) -> ParsedInvoice:
    import io

    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        # PDF escaneado o corrupto: se devuelve todo vacío y needs_manual_items
        # le indica a la UI que ofrezca carga manual.
        text = ""

    text = _strip_extra_copies(text)
    lines = text.split("\n")
    result = ParsedInvoice()

    cod = _COD.search(text)
    if cod:
        result.voucher_type = _ARCA_VOUCHER_TYPE.get(int(cod.group(1)))

    pos_number = _POS_NUMBER.search(text)
    if pos_number:
        result.pos = int(pos_number.group(1))
        result.number = int(pos_number.group(2))

    date = _DATE.search(text)
    if date:
        result.date = _parse_date(date.group(1))

    cae = _CAE.search(text)
    if cae:
        result.cae = cae.group(1)

    period = _PERIOD.search(text)
    if period:
        result.from_date = _parse_date(period.group(1))
        result.to_date = _parse_date(period.group(2))
        result.due_date = _parse_date(period.group(3))

    # Todo lo anterior a "Apellido y Nombre" pertenece al emisor. Sin este
    # recorte, los datos del receptor contaminan la búsqueda del emisor.
    split_at = text.find("Apellido y Nombre")
    issuer_zone = text[:split_at] if split_at > 0 else text

    _extract_issuer(result, lines, issuer_zone)
    _extract_customer(result, lines)

    letter = (result.voucher_type or "")[-1:]
    result.lines = _extract_items(lines, _IVA_BY_LETTER.get(letter, Decimal("21")))
    result.needs_manual_items = not result.lines

    return result
