"""Acceso a datos de `invoices`, scopeado por join contra `fiscal_identities`.

Misma forma que `crud/invoice_template.py` y por el mismo motivo: la tabla no tiene `user_id`
propio, cuelga de `fiscal_identity_id` —que ya está indexado— y el scoping sale del join.

**No hay `update` ni `delete`.** No es un olvido: una factura emitida no se corrige ni se
borra. Lo que existe para dejarla sin efecto es una nota de crédito, que FactuMov no emite, y
que tampoco sería una edición de esta fila. Un CRUD con esas dos funciones invitaría a que
alguna pantalla las use.
"""

import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from factumov.crud.base import db_flush
from factumov.exceptions import DuplicateInvoiceNumberError
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.models.invoice import Invoice

exception_map: dict[str, type[Exception]] = {
    "uq_invoices_fiscal_identity_id_pos_voucher_type_number": DuplicateInvoiceNumberError,
}


def get_all(db: Session, user_id: uuid.UUID) -> list[Invoice]:
    invoices = (
        db.execute(
            select(Invoice)
            .join(Invoice.fiscal_identity)
            .where(FiscalIdentity.user_id == user_id)
            # Las más nuevas primero: la pantalla de facturas se abre para ver la última
            # emitida o para reenviarla, no para recorrer el historial desde 2019.
            .order_by(Invoice.date.desc(), Invoice.number.desc())
            .options(selectinload(Invoice.lines))
        )
        .scalars()
        .all()
    )
    return list(invoices)


def get_by_id(db: Session, invoice_id: uuid.UUID, user_id: uuid.UUID) -> Invoice | None:
    return (
        db.execute(
            select(Invoice)
            .join(Invoice.fiscal_identity)
            .where(Invoice.id == invoice_id, FiscalIdentity.user_id == user_id)
            .options(selectinload(Invoice.lines), joinedload(Invoice.fiscal_identity))
        )
        .scalars()
        .first()
    )


def create(db: Session, invoice: Invoice) -> Invoice:
    """Guarda la factura ya armada.

    Recibe el objeto en vez de un schema, al revés que el resto de los CRUD del proyecto. Es
    deliberado: los campos de esta tabla no salen de un body sino de tres fuentes distintas
    —el modelo, la respuesta de ARCA y el cálculo de importes— y un `InvoiceCreate` que las
    juntara sería un schema de entrada que ningún cliente puede mandar. Quien la arma es
    `services/emission.py`, que es el único que tiene las tres cosas a la vez.
    """
    db.add(invoice)
    db_flush(db, exception_map)
    return invoice


def mark_sent(db: Session, invoice: Invoice) -> None:
    """Deja constancia de que el mail con el PDF salió.

    Pisa la marca anterior en vez de acumular envíos: lo que la pantalla necesita contestar es
    "¿esto ya se mandó?", y un historial de reenvíos sería una tabla para una pregunta que
    nadie hace. Si algún día hace falta —"¿cuándo se lo mandé la primera vez?"— eso sí es una
    tabla, no una columna más.
    """
    invoice.sent_at = func.now()
    db.flush()


def numbering_lock_key(fiscal_identity_id: uuid.UUID, pos: int, voucher_type: str) -> int:
    """Un bigint estable para el advisory lock de la numeración.

    `blake2b` y no `hash()`, por lo mismo que en `services/arca.py`: Python aleatoriza `hash`
    por proceso, así que dos workers tomarían candados distintos para la misma clave y el
    candado no serializaría nada.

    La clave es el trío que define una serie de comprobantes. Trabar por identidad fiscal
    sola serializaría emisiones que no compiten —dos puntos de venta distintos numeran por
    separado— y trabar por algo más fino no existiría.
    """
    material = f"invoice-number:{fiscal_identity_id}:{pos}:{voucher_type}"
    digest = hashlib.blake2b(material.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def lock_numbering(db: Session, key: int) -> None:
    """Toma el candado de una serie hasta el fin de la transacción.

    A diferencia del de `arca_tickets`, este candado tiene que **sobrevivir a la llamada a
    ARCA**: lo que protege es la secuencia entera —preguntar el último número, pedir el CAE
    para el siguiente, guardarlo— y soltarlo en el medio no protege nada. Ver
    `services/emission.py`, que explica por qué acá se sostiene la transacción abierta
    mientras se habla con ARCA, contra lo que hace el resto del proyecto.
    """
    db.execute(select(func.pg_advisory_xact_lock(key)))
