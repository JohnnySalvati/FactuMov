"""La representación impresa del comprobante: el QR fiscal, el HTML y el PDF.

Port adaptado de `invoice_pdf.py` y `templates/invoices/pdf.html` de Balance360. Lo que cambia
es de dónde salen los datos: acá el `Invoice` ya trae **copiados** el emisor y el receptor, así
que el template no navega relaciones y el PDF de una factura vieja sale idéntico aunque el
cliente haya cambiado de domicilio. Eso último es la mitad del motivo por el que esas columnas
existen.

`pdf_invoice.py` (el parser) e `invoice_pdf.py` (esto) **no son duplicados**: el primero lee
facturas ajenas, el segundo imprime las propias. Los nombres chocan por accidente y así están
en Balance360; se conservan para que buscar uno encuentre el otro.
"""

import base64
import json
from decimal import Decimal
from importlib import resources
from typing import Any

import segno
from jinja2 import Environment, StrictUndefined

from factumov.enums import CondicionIva, VoucherType
from factumov.exceptions import InvoicePrintError
from factumov.models.invoice import Invoice
from factumov.services.invoice_totals import LineAmounts, compute_totals, money

# Cómo ARCA nombra cada condición en el impreso. Es el vocabulario del comprobante y no el
# nuestro: el enum se llama FINAL y el papel tiene que decir "Consumidor Final".
_CONDICION_LABEL = {
    CondicionIva.INSCRIPTO: "IVA Responsable Inscripto",
    CondicionIva.MONOTRIBUTO: "Responsable Monotributo",
    CondicionIva.EXENTO: "IVA Sujeto Exento",
    CondicionIva.FINAL: "Consumidor Final",
}

# La letra grande del recuadro. Una nota de crédito A lleva una "A", no "NCA" — por eso no
# alcanza con `voucher_type.value`. FactuMov no las emite, pero el enum las tiene y el
# template no debería romperse si algún día llega una.
_LETTER = {
    VoucherType.A: "A",
    VoucherType.B: "B",
    VoucherType.C: "C",
    VoucherType.NCA: "A",
    VoucherType.NCB: "B",
    VoucherType.NCC: "C",
}

_QR_BASE_URL = "https://www.arca.gob.ar/fe/qr/?p="


def format_amount(value: Decimal) -> str:
    """`1234.5` → `1.234,50`, que es como se escribe un importe acá.

    A mano y no con `locale`: `locale.setlocale` es global del proceso y depende de que el
    sistema tenga instalado `es_AR`, que en un contenedor no pasa. Son cuatro líneas y no
    dependen de nada.
    """
    entire, _, cents = f"{money(value):.2f}".partition(".")
    negative = entire.startswith("-")
    digits = entire.lstrip("-")
    groups: list[str] = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    return f"{'-' if negative else ''}{'.'.join(groups)},{cents}"


def format_tax_id(tax_id: str) -> str:
    """`20182810674` → `20-18281067-4`, que es como ARCA lo imprime."""
    if len(tax_id) != 11 or not tax_id.isdigit():
        return tax_id
    return f"{tax_id[:2]}-{tax_id[2:10]}-{tax_id[10]}"


def build_qr(invoice: Invoice) -> str:
    """El QR fiscal que ARCA exige en el impreso, como data URI.

    El contenido lo fija ARCA: un JSON con claves y tipos específicos, en base64, colgado de
    una URL suya. Los tipos importan — `cuit`, `nroDocRec` y `codAut` van como **números** y
    no como strings, y `importe` como float. Un QR con un string donde va un número se lee
    igual pero el validador de ARCA lo rechaza.

    Data URI y no un archivo: el PDF se genera en memoria y se manda adjunto, así que no hay
    dónde poner un archivo temporal ni quién lo limpie después.
    """
    payload = {
        "ver": 1,
        "fecha": invoice.date.isoformat(),
        "cuit": int(invoice.issuer_tax_id),
        "ptoVta": invoice.pos,
        "tipoCmp": invoice.voucher_type.arca_code,
        "nroCmp": invoice.number,
        "importe": float(invoice.total),
        "moneda": "PES",
        "ctz": 1,
        "tipoDocRec": invoice.customer_doc_type.value,
        "nroDocRec": int(invoice.customer_doc_number),
        "tipoCodAut": "E",
        "codAut": int(invoice.cae),
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    qr: str = segno.make(_QR_BASE_URL + encoded).png_data_uri(scale=3)
    return qr


def _context(invoice: Invoice) -> dict[str, Any]:
    """Todo lo que el template necesita, ya resuelto. El template no hace cuentas.

    El desglose por alícuota se recalcula con `compute_totals` sobre las líneas guardadas —es
    determinístico y da lo mismo que dio al emitir— pero los **totales** salen de las columnas
    de la factura, que es lo que ARCA autorizó. Si algún día las dos cosas discreparan, lo que
    tiene que salir impreso es lo segundo.
    """
    totals = compute_totals(
        invoice.voucher_type,
        [
            LineAmounts(
                quantity=line.quantity, unit_price=line.unit_price, iva_aliquot=line.iva_aliquot
            )
            for line in invoice.lines
        ],
    )
    discriminates = invoice.voucher_type.discriminates_iva
    return {
        "invoice": invoice,
        "letter": _LETTER[invoice.voucher_type],
        "voucher_code": f"{invoice.voucher_type.arca_code:02d}",
        "discriminates": discriminates,
        "issuer_condicion": _CONDICION_LABEL[invoice.issuer_condicion_iva],
        "customer_condicion": _CONDICION_LABEL[invoice.customer_condicion_iva],
        "issuer_tax_id": format_tax_id(invoice.issuer_tax_id),
        "customer_doc": format_tax_id(invoice.customer_doc_number),
        "customer_doc_label": invoice.customer_doc_type.name,
        # En A el precio guardado es neto y el impreso lo muestra así, con su columna de IVA
        # al lado. En B y C el precio ya trae el IVA adentro y el impreso muestra ese mismo
        # número, sin desglosar. Es la convención del proyecto, la misma del parser.
        "lines": [
            {
                "description": line.description,
                "quantity": _trim(line.quantity),
                "unit_price": format_amount(line.unit_price),
                "subtotal": format_amount(line.quantity * line.unit_price),
                "rate": _trim(line.iva_aliquot.rate),
                "with_iva": format_amount(
                    line.quantity * line.unit_price * (1 + line.iva_aliquot.rate / 100)
                ),
            }
            for line in invoice.lines
        ],
        "iva_breakdown": [
            {"rate": _trim(item.aliquot.rate), "amount": format_amount(item.iva)}
            for item in totals.breakdown
            if item.iva
        ],
        "net_total": format_amount(invoice.net_total),
        "total": format_amount(invoice.total),
        "qr": build_qr(invoice),
    }


def _trim(value: Decimal) -> str:
    """`21.0` → `21`, `2.50` → `2,5`. Los ceros de la escala de la columna no van al papel."""
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


def _environment() -> Environment:
    """El entorno de Jinja, con autoescape y `StrictUndefined`.

    `StrictUndefined` para que una variable mal escrita en el template explote en vez de
    imprimir vacío: en un comprobante fiscal, un campo que desaparece en silencio es peor que
    un error. `autoescape` porque el nombre y el domicilio del cliente son texto que cargó
    alguien, y van al HTML sin pasar por ninguna validación que los limpie.
    """
    return Environment(autoescape=True, undefined=StrictUndefined)


def render_html(invoice: Invoice) -> str:
    """El comprobante como HTML, que es lo que se convierte a PDF.

    El template vive en un archivo aparte y no en un string de este módulo: son 150 líneas de
    HTML y CSS, y en un `.py` no hay resaltado ni nadie las lee. Se carga con
    `importlib.resources` y no con una ruta relativa a `__file__` para que siga funcionando
    desde un wheel, donde el paquete puede no estar desplegado en el disco.
    """
    source = resources.files("factumov.templates").joinpath("invoice.html").read_text("utf-8")
    return _environment().from_string(source).render(**_context(invoice))


def render_pdf(invoice: Invoice) -> bytes:
    """El comprobante como PDF.

    El import de weasyprint va **adentro** de la función a propósito: al importarse carga las
    librerías GTK del sistema, y en una máquina sin ellas el import falla. Arriba del módulo,
    eso se llevaría puesta la app entera al arrancar en vez de solo esta operación — que es
    exactamente el criterio de `EmailSettings` y del `lifespan` de `main.py`: lo que rompe una
    función no tiene que romper el resto.
    """
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        raise InvoicePrintError(
            "No se puede generar el PDF: falta weasyprint o sus librerías GTK"
        ) from exc

    pdf: bytes = HTML(string=render_html(invoice)).write_pdf()
    return pdf


def pdf_filename(invoice: Invoice) -> str:
    """`FactuMov-B-00001-00000042.pdf`.

    Lleva letra, punto de venta y número para que el destinatario no termine con cinco
    archivos llamados todos `comprobante.pdf` en la carpeta de descargas.
    """
    return f"FactuMov-{invoice.label}.pdf"
