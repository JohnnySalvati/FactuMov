"""La letra del comprobante, deducida de las dos condiciones frente al IVA.

Port de `allowed_for` de Balance360, con una diferencia que lo cambia todo: **acá no hay notas
de crédito**. FactuMov automatiza el comprobante que se repite todos los meses, y nadie le
emite una NC a sus clientes todos los meses; la NC es la excepción, y la excepción se hace a
mano en el sitio de ARCA. Ver CLAUDE.md.

Sacadas las NC, la intersección de los dos conjuntos **tiene siempre exactamente un elemento**:

| Emisor \\ Receptor | Inscripto | Monotributo | Exento | Consumidor final |
|---|---|---|---|---|
| Inscripto   | A | A | B | B |
| Monotributo | C | C | C | C |
| Exento      | C | C | C | C |

La celda Inscripto → Monotributo decía B hasta el 2026-08-27 y estaba mal: es A, por la Ley
27.618. Lo verificó ARCA rechazando la B — ver el comentario de `_CUSTOMER_ALLOWED`.

O sea que la letra no es una elección del usuario: es una consecuencia de quién le factura a
quién. Por eso `voucher_type` dejó de ser una columna de `invoice_templates` y pasó a ser esto.
Guardarla sería una tercera fuente de verdad capaz de contradecir a sus dos padres — y el día
que un cliente pasa de monotributista a inscripto, el modelo guardado seguiría diciendo B
cuando ARCA ya espera A.
"""

from factumov.enums import CondicionIva, VoucherType
from factumov.exceptions import UndecidableVoucherTypeError

# Lo que cada condición puede **emitir**. El consumidor final no emite nada: el conjunto vacío
# no es un descuido, es lo que hace que `voucher_type_for` no tenga que preguntarlo aparte.
_ISSUER_ALLOWED: dict[CondicionIva, frozenset[VoucherType]] = {
    CondicionIva.INSCRIPTO: frozenset({VoucherType.A, VoucherType.B}),
    CondicionIva.MONOTRIBUTO: frozenset({VoucherType.C}),
    CondicionIva.EXENTO: frozenset({VoucherType.C}),
    CondicionIva.FINAL: frozenset(),
}

# Lo que cada condición puede **recibir**, según la tabla que devuelve
# `FEParamGetCondicionIvaReceptor` — verificada contra ARCA el 2026-08-27, no deducida.
#
# **El monotributista recibe A, no B**, y eso corrige lo que este archivo decía antes. Es la
# Ley 27.618: desde 2021 el responsable inscripto que le factura a un monotributista emite A.
# No es una interpretación nuestra — ARCA **rechaza** la B con el código 10243 ("El campo
# Condicion IVA receptor no es valido para la clase de comprobante informado") y autoriza la A.
# Está probado emitiendo las dos en homologación.
_CUSTOMER_ALLOWED: dict[CondicionIva, frozenset[VoucherType]] = {
    CondicionIva.INSCRIPTO: frozenset({VoucherType.A, VoucherType.C}),
    CondicionIva.MONOTRIBUTO: frozenset({VoucherType.A, VoucherType.C}),
    CondicionIva.EXENTO: frozenset({VoucherType.B, VoucherType.C}),
    CondicionIva.FINAL: frozenset({VoucherType.B, VoucherType.C}),
}


def voucher_type_for(issuer: CondicionIva, customer: CondicionIva) -> VoucherType:
    """La letra que corresponde entre esas dos condiciones.

    Levanta `UndecidableVoucherTypeError` cuando no hay ninguna, que hoy solo puede pasar con
    un emisor consumidor final. Eso ya lo rechaza `FiscalIdentityCreate` con un 422, así que
    por la API no se llega; la excepción está para que el invariante se rompa ruidosamente y
    no en silencio si mañana alguien afloja aquel validador.
    """
    allowed = _ISSUER_ALLOWED[issuer] & _CUSTOMER_ALLOWED[customer]
    if len(allowed) != 1:
        raise UndecidableVoucherTypeError(
            f"No hay una letra de comprobante para un emisor {issuer.name} "
            f"y un receptor {customer.name}"
        )
    return next(iter(allowed))
