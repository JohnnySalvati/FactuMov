"""Parser de facturas en PDF, con un registry de dos layouts.

Devuelve un ParsedInvoice; los campos que no se encuentran quedan en None.

Deriva de `services/pdf_invoice.py` de Balance360, con dos diferencias de fondo:

1. Allí se leían facturas de terceros, así que solo interesaba el emisor. Acá el
   emisor es el propio usuario y el dato que hace falta es el receptor: se
   extraen los dos.
2. Balance360 soporta diez layouts de distintos sistemas de facturación, ninguno
   con un PDF a mano contra el cual verificarlo. Acá hay dos, y de los dos hay
   facturas reales:

   - **arca**: "Comprobantes en línea", el sitio de ARCA.
   - **factumov**: el comprobante que imprime `services/invoice_pdf.py`, que es
     también el de Balance360 — el template de acá es un port del de allá y los
     dos salen iguales. Reimportar una factura propia es el caso natural: se
     emitió una, y el mes que viene se quiere volver a facturar lo mismo.

Los dos imprimen **la misma fórmula**. Los rótulos —"Razón Social:", "Condición
frente al IVA:", "Período Facturado Desde:"— los fija la RG 1415 y no el generador,
así que la extracción del emisor y del receptor es **una sola**, con los rótulos que
pueden quedar pegados a la derecha listados como alternativas. Cada alternativa sale
de un PDF real que se leyó: no hay ninguna puesta por las dudas.

Lo que sí cambia de verdad es la **tabla de items**, y es lo único que el `_Layout`
guarda aparte:

- **Columnas.** ARCA imprime `Código` `Producto/Servicio` `Cantidad` `U. Medida`
  `Precio Unit.` `% Bonif` …; el propio, `Producto/Servicio` `Cantidad`
  `Precio Unit.` `Subtotal` … — sin código, sin unidad de medida y sin bonificación.
- **Importes.** `35000,00` contra `$ 35.000,00`.
- **Copias.** ORIGINAL + DUPLICADO + TRIPLICADO contra una sola.

Lógica pura: sin base de datos, sin red.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from factumov.enums import CondicionIva, DocType, VoucherType


@dataclass
class ParsedInvoiceLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    iva_rate: Decimal


@dataclass
class ParsedInvoice:
    voucher_type: VoucherType | None = None
    pos: int | None = None
    number: int | None = None
    date: datetime.date | None = None
    issuer_cuit: str | None = None
    issuer_name: str | None = None
    issuer_condicion_iva: CondicionIva | None = None
    issuer_address: str | None = None
    issuer_iibb: str | None = None
    issuer_start_date: datetime.date | None = None
    customer_doc_type: DocType | None = None
    customer_doc_number: str | None = None
    customer_name: str | None = None
    customer_condicion_iva: CondicionIva | None = None
    customer_address: str | None = None
    from_date: datetime.date | None = None
    to_date: datetime.date | None = None
    due_date: datetime.date | None = None
    cae: str | None = None
    lines: list[ParsedInvoiceLine] = field(default_factory=list)
    # True cuando el PDF no tiene texto extraíble (escaneado) o no se reconoció
    # ninguna línea: la UI debería ofrecer carga manual de los items.
    needs_manual_items: bool = False


# Alícuota deducida de la letra, que es lo único disponible en B y C: esos
# comprobantes no discriminan IVA por línea. En B el precio impreso ya lo trae
# adentro; quien arme la factura decide cómo interpretarlo, igual que hace
# Balance360 en Invoice.iva_breakdown.
#
# En A no se usa salvo como red: ahí la alícuota va impresa por línea y se lee de
# la columna correspondiente, porque una misma factura A puede mezclar líneas al
# 21% y al 10,5%.
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


# --- Los campos que los dos layouts imprimen igual ---------------------------
#
# El encabezado del comprobante son dos columnas, y el texto que sale de pdfplumber
# las mezcla renglón por renglón: qué campo de la derecha queda pegado a qué campo
# de la izquierda depende de dónde cortó cada línea, o sea del largo de la razón
# social y del domicilio. Por eso los campos no terminan en fin de línea sino en el
# rótulo siguiente, y el rótulo siguiente no es siempre el mismo.

# Cada alternativa se vio en un PDF: "Fecha de …" y "CUIT:" en el de ARCA, "COD." e
# "Ingresos Brutos:" en el propio —donde la letra y el código del comprobante van
# montados sobre el encabezado, y una razón social larga desalinea las columnas—.
_NEXT_LABEL = r"(?:Fecha de\b|COD\.|CUIT:|Ingresos Brutos:|Punto de Venta:|Comp\.)"
# Cuando el campo llega hasta el final del renglón, `[ \t]*$` cierra; cuando lo
# sigue otro rótulo, el grupo opcional se come lo que queda.
_UNTIL_NEXT_LABEL = rf"(?:\s+{_NEXT_LABEL}.*)?[ \t]*$"

_COD = re.compile(r"\bCOD\.\s*0*(\d{1,3})\b")
_POS_NUMBER = re.compile(r"Punto de Venta:\s*0*(\d+)\s+Comp\.\s*Nro:\s*0*(\d+)")
_DATE = re.compile(r"Fecha de Emisi[oó]n:\s*(\d{2}/\d{2}/\d{4})")
_CAE = re.compile(r"CAE\s*N[°º]?\.?\s*:\s*(\d{14})")

# "Fecha de Vto. para el pago:" es como lo titula ARCA; el comprobante propio y el
# de Balance360 escriben "Vto. para el pago:" a secas.
_PERIOD = re.compile(
    r"Per[ií]odo Facturado Desde:\s*(\d{2}/\d{2}/\d{4})\s+"
    r"Hasta:\s*(\d{2}/\d{2}/\d{4})\s+"
    r"(?:Fecha de\s+)?Vto\.\s*para el pago:\s*(\d{2}/\d{2}/\d{4})"
)

_ISSUER_NAME = re.compile(rf"Raz[oó]n Social:[ \t]*(.*?){_UNTIL_NEXT_LABEL}", re.M)
# El CUIT va con guiones en el comprobante propio (`invoice_pdf.format_tax_id`) y
# sin ellos en el de ARCA. Se aceptan las dos formas y se guardan solo los dígitos.
_ISSUER_CUIT = re.compile(r"CUIT:\s*(\d{2}-?\d{8}-?\d)\b")
_ISSUER_CONDICION = re.compile(rf"Condici[oó]n frente al IVA:[ \t]*(.*?){_UNTIL_NEXT_LABEL}", re.M)
# El rótulo del domicilio cambia con la letra: B y C imprimen "Domicilio:" y A
# "Domicilio Comercial:". Exigir la forma corta dejaba sin domicilio a toda A.
_ADDRESS = re.compile(rf"Domicilio(?:\s+Comercial)?:[ \t]*(.*?){_UNTIL_NEXT_LABEL}", re.M)
# `[ \t]*` y no `\s*` antes de la captura: `\s` cruza el salto de línea, y un
# "Ingresos Brutos:" vacío —que el comprobante propio imprime cuando la identidad
# fiscal no lo tiene cargado— se llevaba el contenido del renglón de abajo.
_ISSUER_IIBB = re.compile(r"Ingresos Brutos:[ \t]*(\S+)")
_ISSUER_START = re.compile(r"Fecha de Inicio de Actividades:[ \t]*(\d{2}/\d{2}/\d{4})")

# El receptor. El documento puede ser CUIT, CUIL o DNI —hardcodear CUIT dejaba sin
# receptor a las facturas a consumidor final— y con guiones o sin ellos. El rótulo
# largo es el de ARCA; el comprobante propio pone "Razón Social:" solo. El nombre
# usa `.*?` y no `.+?` porque puede venir vacío.
_CUSTOMER = re.compile(
    r"(?P<doc_type>CUIT|CUIL|DNI):\s*(?P<doc_number>[\d-]{7,13})\s+"
    r"(?:Apellido y Nombre\s*/\s*)?Raz[oó]n Social:\s*(?P<name>.*?)\s*$",
    re.M,
)
# La condición del receptor se distingue de la del emisor porque lleva el domicilio
# pegado en el mismo renglón. El domicilio puede venir vacío —Balance360 imprime el
# rótulo igual cuando el contacto no lo tiene— y ahí lo que importa es no perder
# también la condición, que sí está.
_CUSTOMER_CONDICION = re.compile(
    r"Condici[oó]n frente al IVA:\s*(?P<condicion>.+?)\s+"
    r"Domicilio(?:\s+Comercial)?:[ \t]*(?P<address>.*?)[ \t]*$"
)

# Una línea que empieza con alguna de estas etiquetas abre otro campo, así que
# nunca es la continuación de un domicilio partido en dos renglones. Del
# encabezado de la tabla hay cuatro entradas y no una porque el del comprobante
# propio se parte en tres renglones cuando una descripción larga ensancha la
# primera columna, y el que queda pegado abajo del domicilio del receptor es el de
# arriba: "PRECIO ALÍCUOTA SUBTOTAL C/", que no empieza por el título de la tabla.
_NEXT_FIELD = re.compile(
    r"^(Condici[oó]n\b|C[oó]digo\s+Producto|Producto\s*/|Per[ií]odo\b"
    r"|CUIT:|CUIL:|DNI:|Domicilio"
    r"|Cantidad\b|Precio\b|Al[ií]cuota\b|Subtotal\b|Importe\b)",
    re.I,
)
# Lo que el renglón de abajo arrastra pegado de la columna derecha. La continuación
# de un domicilio largo de ARCA viene como "…el resto del domicilio Ingresos Brutos:
# 20182810674": el rótulo y lo que le sigue no son parte del domicilio.
_TRAILING_LABEL = re.compile(rf"\s*{_NEXT_LABEL}.*$")


def _strip_extra_copies(text: str) -> str:
    """Deja solo la primera copia de la factura.

    ARCA imprime la misma factura tres veces —ORIGINAL, DUPLICADO, TRIPLICADO—
    en un único PDF. Con las tres en el texto, cualquier extracción encuentra
    tres de cada cosa. Cortar en el primer DUPLICADO deja una sola factura y
    hace que todo lo de abajo sea seguro por construcción.

    El comprobante propio trae una sola copia —el original electrónico es uno; el
    duplicado y el triplicado son del papel— así que no hay marcador y no se corta
    nada.
    """
    marker = re.search(r"^\s*DUPLICADO\s*$", text, re.M)
    return text[: marker.start()] if marker else text


def _parse_date(value: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


# Un punto seguido de una o dos cifras, en un número sin ninguna coma, es una coma
# decimal escrita a la inglesa. Es lo que sale de imprimir un Decimal crudo, como
# hace Balance360 con la alícuota de cada línea: `Numeric(5, 2)` se escribe "10.50"
# y no "10,5". Con la regla argentina a secas eso se leía 1050, y
# `IvaAliquot.get_by_rate` no encontraba ninguna alícuota con esa tasa.
#
# Tres cifras después del punto siguen siendo un separador de miles ("2.805.000"),
# que es la razón por la que la regla se limita a una o dos.
_ANGLO_DECIMAL = re.compile(r"^-?\d+\.\d{1,2}$")


def _to_decimal(value: str | None) -> Decimal | None:
    """Convierte '2.805.000,00' o '2805000,00' a Decimal.

    El formato argentino —el punto agrupa miles y la coma separa decimales— es el
    de los dos generadores en todo lo que pasa por un formateador. Balance360 tiene
    un campo que no pasa por ninguno, la alícuota, y ahí sale el punto decimal
    inglés: ver `_ANGLO_DECIMAL`.
    """
    if value is None:
        return None
    cleaned = re.sub(r"[^\d,.-]", "", value.strip())
    if not cleaned:
        return None
    if not _ANGLO_DECIMAL.match(cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _digits(value: str) -> str:
    """De 20-18281067-4 a 20182810674. La columna guarda solo los dígitos."""
    return re.sub(r"\D", "", value)


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


def _address_tail(lines: list[str], index: int) -> str:
    """Junta los renglones de abajo que son continuación del domicilio de `index`.

    Corta en el primer renglón que abre otro campo, y de cada uno descarta lo que
    venga pegado de la columna derecha. Los dos cortes hacen falta: en el
    comprobante de ARCA el renglón siguiente al domicilio es "Ingresos Brutos: …",
    que se vacía entero y termina el domicilio ahí.
    """
    parts: list[str] = []
    for line in lines[index + 1 :]:
        stripped = _TRAILING_LABEL.sub("", line.strip())
        if not stripped or _NEXT_FIELD.match(stripped):
            break
        parts.append(stripped)
    return " ".join(parts)


# --- La tabla de items, que es lo que cambia entre un generador y el otro -----

_NUM = r"[\d.,]+"
# La columna "Alícuota IVA" de las A puede venir como "21%", así que las columnas
# de la cola admiten un % final que _to_decimal después descarta.
_COL = r"[\d.,]+%?"
# La unidad de medida no es siempre "unidades": ARCA ofrece horas, kilogramos,
# metros, docenas. Se acepta cualquier token que no empiece con dígito, que es lo
# que la distingue de las columnas numéricas que la rodean. Hardcodear "unidades"
# hacía desaparecer en silencio cualquier línea facturada en otra unidad.
_UNIT = r"[^\d\s]\S*"

_ARCA_ITEMS_HEADER = re.compile(
    r"C[oó]digo\s+Producto\s*/\s*Servicio\s+Cantidad\s+U\.\s*Medida", re.I
)
# Después del precio unitario las columnas dependen de la letra, y no son las
# mismas ni en cantidad ni en orden:
#
#   B y C:  % Bonif | Imp. Bonif. | Subtotal                     -> 3
#   A:      % Bonif | Subtotal | Alícuota IVA | Subtotal c/IVA    -> 4
#
# La A no imprime Imp. Bonif. y sí agrega la alícuota por línea. Se captura la cola
# entera y _arca_line_iva_rate decide según cuántas columnas son. Pedir exactamente
# 3 era lo que hacía que ninguna línea de una factura A matcheara.
#
# Se aceptan solo esos dos anchos a propósito: ante un layout desconocido es
# preferible no matchear —la línea falta, needs_manual_items lo delata— antes que
# matchear corrido y asignarle a la alícuota el número de otra columna.
_ARCA_ITEM_ROW = re.compile(
    rf"^(?P<desc>.+?)\s+(?P<qty>{_NUM})\s+(?P<unit>{_UNIT})\s+(?P<price>{_NUM})"
    rf"\s+(?P<tail>{_COL}(?:\s+{_COL}){{2,3}})\s*$"
)
# Ancho de la cola en A y posición de la alícuota dentro de ella. Verificado contra
# 20182810674_001_00002_00000134.pdf: "... 0,00 35000,00 21% 42350,00", donde
# 35000 × 1,21 = 42350 confirma que el precio unitario de A viene neto.
_A_TAIL_COLUMNS = 4
_A_ALIQUOT_INDEX = 2

# El comprobante propio no imprime ni código, ni unidad de medida, ni bonificación:
# descripción, cantidad, precio y subtotal, más las dos columnas del IVA en la A.
# El encabezado va en mayúsculas por CSS y puede partirse en tres renglones cuando
# una descripción larga ensancha la primera columna, así que se lo reconoce por lo
# único que sobrevive entero a esa partición: el título de las dos primeras
# columnas, que caen juntos en el renglón del medio.
_FACTUMOV_ITEMS_HEADER = re.compile(r"Producto\s*/\s*Servicio\s+Cantidad", re.I)
# Los importes llevan el "$" adelante, y eso es lo que ancla la fila: sin él, una
# descripción terminada en número —"Instalacion 2"— se confundiría con la cantidad.
# La cola es opcional porque en B y C la fila termina en el subtotal.
_FACTUMOV_ITEM_ROW = re.compile(
    rf"^(?P<desc>.+?)\s+(?P<qty>{_NUM})\s+\$\s*(?P<price>{_NUM})\s+\$\s*{_NUM}"
    rf"(?P<tail>\s+{_NUM}%\s+\$\s*{_NUM})?[ \t]*$"
)

_ITEMS_END = re.compile(r"^\s*(Subtotal:|Importe|R[eé]gimen|P[aá]g\.|CAE\b)", re.I)
# Un renglón suelto entre el encabezado y la primera fila es la primera parte de una
# descripción partida en varias: cuando la celda de la descripción ocupa más
# renglones que las de los números, el generador centra los números y la fila con
# las columnas queda en el medio. Los restos del encabezado partido caen en el mismo
# lugar —"IVA" abajo de "Alicuota" en ARCA, "UNIT. IVA IVA" abajo del título en el
# propio— y no son descripción: se los reconoce porque no tienen ni una minúscula,
# que es lo que deja el text-transform del encabezado.
_HEADER_REMNANT = re.compile(r"^[^a-záéíóúüñ]*$")


def _arca_line_iva_rate(tail: str, default_rate: Decimal) -> Decimal:
    """Alícuota de una línea de ARCA, leída de la factura cuando está impresa.

    Solo las A discriminan IVA por línea, y ahí hay que leerlo: una misma factura
    puede mezclar 21% y 10,5%, así que deducirlo de la letra da un número
    plausible y equivocado. Se reconoce el layout por la cantidad de columnas y no
    por el encabezado, que en la A viene partido en dos renglones ("Alicuota"
    arriba e "IVA" abajo) y obligaría a acertarle además al texto del título.
    """
    columns = tail.split()
    if len(columns) != _A_TAIL_COLUMNS:
        return default_rate
    rate = _to_decimal(columns[_A_ALIQUOT_INDEX])
    return default_rate if rate is None else rate


def _factumov_line_iva_rate(tail: str, default_rate: Decimal) -> Decimal:
    """Alícuota de una línea del comprobante propio.

    Acá el ancho no hace falta contarlo: las dos columnas de la derecha —"Alícuota
    IVA" y "Subtotal c/IVA"— existen solo en la A, así que la cola o trae la
    alícuota o viene vacía, y vacía significa caer en la de la letra.
    """
    if not tail.strip():
        return default_rate
    rate = _to_decimal(tail.split()[0])
    return default_rate if rate is None else rate


@dataclass(frozen=True)
class _Layout:
    """Un generador de PDFs, con lo poco que imprime distinto.

    Guarda la tabla de items y la marca que lo identifica, y nada más: los rótulos
    del emisor y del receptor los fija la RG 1415 y salen iguales de los dos, así
    que una copia por layout serían dos listas capaces de discrepar.
    """

    name: str
    marker: re.Pattern[str]
    items_header: re.Pattern[str]
    item_row: re.Pattern[str]
    line_iva_rate: Callable[[str, Decimal], Decimal]


# ARCA imprime el rótulo largo del receptor y nunca pone guiones en el CUIT; el
# comprobante propio hace exactamente al revés. Cualquiera de las dos marcas alcanza
# sola y está en todo comprobante de su generador, tenga items o no — reconocerlos
# por el encabezado de la tabla dejaría sin identificar justo a los PDFs cuyas
# líneas no se pudieron leer, que son los que más interesa saber de dónde salieron.
_ARCA = _Layout(
    name="arca",
    marker=re.compile(r"Apellido y Nombre\s*/\s*Raz[oó]n Social"),
    items_header=_ARCA_ITEMS_HEADER,
    item_row=_ARCA_ITEM_ROW,
    line_iva_rate=_arca_line_iva_rate,
)
_FACTUMOV = _Layout(
    name="factumov",
    marker=re.compile(r"CUIT:\s*\d{2}-\d{8}-\d\b"),
    items_header=_FACTUMOV_ITEMS_HEADER,
    item_row=_FACTUMOV_ITEM_ROW,
    line_iva_rate=_factumov_line_iva_rate,
)
_LAYOUTS: tuple[_Layout, ...] = (_ARCA, _FACTUMOV)


def _detect_layout(text: str) -> _Layout:
    """Qué generador imprimió este PDF.

    Ante uno desconocido devuelve el de ARCA, que es el que más facturas cubre. Lo
    que sale de eso no es un error: las líneas no matchean, `needs_manual_items`
    queda en True y la UI ofrece carga manual — el mismo camino de un PDF escaneado.
    """
    return next((layout for layout in _LAYOUTS if layout.marker.search(text)), _ARCA)


def _extract_items(
    layout: _Layout, lines: list[str], default_rate: Decimal
) -> list[ParsedInvoiceLine]:
    result: list[ParsedInvoiceLine] = []
    pending: list[str] = []
    in_items = False

    for raw_line in lines:
        line = raw_line.strip()

        if not in_items:
            if layout.items_header.search(line):
                in_items = True
            continue

        if not line:
            continue
        if _ITEMS_END.match(line):
            break

        match = layout.item_row.match(line)
        if match:
            quantity = _to_decimal(match.group("qty"))
            unit_price = _to_decimal(match.group("price"))
            if quantity is None or unit_price is None:
                continue
            description = re.sub(r"\s+", " ", " ".join([*pending, match.group("desc").strip()]))
            pending.clear()
            iva_rate = layout.line_iva_rate(match.group("tail") or "", default_rate)
            result.append(ParsedInvoiceLine(description, quantity, unit_price, iva_rate))
        elif result:
            # La descripción puede continuar en las líneas de abajo:
            # "Almuerzos consumidos desde el" / "29/06/26 al 03/07/26 ...".
            result[-1].description = re.sub(r"\s+", " ", f"{result[-1].description} {line}")
        elif not _HEADER_REMNANT.match(line):
            # ...y también arriba, si el generador centró los números.
            pending.append(line)

    return result


# --- Emisor y receptor -------------------------------------------------------


def _extract_issuer(result: ParsedInvoice, lines: list[str]) -> None:
    """Los campos del emisor, buscados solo arriba del renglón del receptor.

    El corte importa: los dos comprobantes imprimen "Razón Social:", "Condición
    frente al IVA:" y "Domicilio Comercial:" una vez para cada parte, y sin él la
    primera búsqueda que fallara para el emisor devolvería el dato del receptor.
    """
    found = _find_line(lines, _CUSTOMER)
    zone = lines[: found[0]] if found else lines
    text = "\n".join(zone)

    issuer_name = _ISSUER_NAME.search(text)
    if issuer_name:
        result.issuer_name = issuer_name.group(1).strip() or None

    issuer_cuit = _ISSUER_CUIT.search(text)
    if issuer_cuit:
        result.issuer_cuit = _digits(issuer_cuit.group(1))

    issuer_condicion = _ISSUER_CONDICION.search(text)
    if issuer_condicion:
        condicion_iva = _condicion_iva(issuer_condicion.group(1))
        result.issuer_condicion_iva = CondicionIva[condicion_iva] if condicion_iva else None

    issuer_iibb = _ISSUER_IIBB.search(text)
    if issuer_iibb:
        result.issuer_iibb = issuer_iibb.group(1)

    issuer_start = _ISSUER_START.search(text)
    if issuer_start:
        result.issuer_start_date = _parse_date(issuer_start.group(1))

    found_address = _find_line(zone, _ADDRESS)
    if found_address:
        index, match = found_address
        address = f"{match.group(1).strip()} {_address_tail(zone, index)}".strip()
        result.issuer_address = address or None


def _extract_customer(result: ParsedInvoice, lines: list[str]) -> None:
    found = _find_line(lines, _CUSTOMER)
    if not found:
        return

    index, match = found
    result.customer_doc_type = DocType[match.group("doc_type")]
    result.customer_doc_number = _digits(match.group("doc_number"))
    result.customer_name = match.group("name").strip() or None

    # Del renglón del receptor para abajo: la condición del emisor lleva el mismo
    # rótulo, y en el comprobante propio puede quedar en un renglón sin nada más.
    zone = lines[index:]
    found_condicion = _find_line(zone, _CUSTOMER_CONDICION)
    if found_condicion:
        condicion_index, condicion = found_condicion
        condicion_iva = _condicion_iva(condicion.group("condicion"))
        result.customer_condicion_iva = CondicionIva[condicion_iva] if condicion_iva else None
        address = condicion.group("address").strip()
        tail = _address_tail(zone, condicion_index)
        result.customer_address = f"{address} {tail}".strip() or None


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

    # El comprobante propio separa el punto de venta del número con `&nbsp;`, que
    # sale del PDF como U+00A0. `\s` lo matchea y `[ \t]` no, así que normalizarlo
    # acá evita tener que acordarse de eso en cada patrón.
    text = _strip_extra_copies(text.replace("\xa0", " "))
    lines = text.split("\n")
    layout = _detect_layout(text)
    result = ParsedInvoice()

    cod = _COD.search(text)
    if cod:
        # Solo los tipos que FactuMov maneja; una nota de débito o un recibo dan `None` a
        # propósito, porque es mejor quedarse sin tipo que con uno incorrecto.
        result.voucher_type = VoucherType.get_by_arca_code(int(cod.group(1)))

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

    _extract_issuer(result, lines)
    _extract_customer(result, lines)

    letter = result.voucher_type.value[-1:] if result.voucher_type else ""
    result.lines = _extract_items(layout, lines, _IVA_BY_LETTER.get(letter, Decimal("21")))
    result.needs_manual_items = not result.lines

    return result
