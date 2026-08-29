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
from factumov.enums import Balance360Status
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
            # El cliente va joineado porque `Invoice.customer_email` lo lee de la relación:
            # sin esto, listar N facturas son N queries más.
            .options(selectinload(Invoice.lines), joinedload(Invoice.customer))
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
            .options(
                selectinload(Invoice.lines),
                joinedload(Invoice.fiscal_identity),
                joinedload(Invoice.customer),
            )
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


def mark_sent(db: Session, invoice: Invoice, address: str) -> None:
    """Deja constancia de que el mail con el PDF salió, y a qué dirección.

    Pisa la marca anterior en vez de acumular envíos: lo que la pantalla necesita contestar es
    "¿esto ya se mandó?", y un historial de reenvíos sería una tabla para una pregunta que
    nadie hace. Si algún día hace falta —"¿cuándo se lo mandé la primera vez?"— eso sí es una
    tabla, no una columna más.

    La dirección se recibe en vez de releerla del cliente porque acá lo que se registra es un
    hecho: a qué casilla salió **este** envío. Si el cliente cambia de mail después, la fila
    tiene que seguir diciendo a dónde fue, no a dónde iría hoy.
    """
    invoice.sent_at = func.now()
    invoice.sent_to = address
    db.flush()


def get_pending_balance360(db: Session, user_id: uuid.UUID) -> list[Invoice]:
    """Las facturas que quedaron sin copiar a Balance360: pendientes o fallidas.

    Las de estado `None` no entran, y esa es toda la gracia de que el estado sea nullable: son
    las que se emitieron antes de conectar la integración, y arrastrarlas acá convertiría
    "reintentar lo que falló" en "registrar retroactivamente todo el historial" — que es una
    decisión del usuario, no algo que un botón de reintento deba hacer por su cuenta.

    Ordenadas de la más vieja a la más nueva: reintentar en el orden en que se emitieron deja
    la numeración de Balance360 en el mismo orden que la de acá.
    """
    invoices = (
        db.execute(
            select(Invoice)
            .join(FiscalIdentity)
            .where(
                FiscalIdentity.user_id == user_id,
                Invoice.balance360_status.in_(
                    [Balance360Status.PENDING, Balance360Status.FAILED]
                ),
            )
            .options(selectinload(Invoice.lines))
            .order_by(Invoice.date, Invoice.number)
        )
        .scalars()
        .all()
    )
    return list(invoices)


def mark_balance360_pending(db: Session, invoice: Invoice) -> None:
    """La factura entra al circuito de registro. Borra el error anterior, si lo había."""
    invoice.balance360_status = Balance360Status.PENDING
    invoice.balance360_error = None
    db.flush()


def mark_balance360_registered(
    db: Session, invoice: Invoice, remote_invoice_id: uuid.UUID
) -> None:
    """Quedó copiada del otro lado. Guarda el id remoto, que es lo que permite linkearla."""
    invoice.balance360_status = Balance360Status.REGISTERED
    invoice.balance360_invoice_id = remote_invoice_id
    invoice.balance360_error = None
    invoice.balance360_synced_at = func.now()
    db.flush()


def mark_balance360_failed(db: Session, invoice: Invoice, error: str) -> None:
    """El intento falló y el motivo se guarda para mostrarlo.

    El mensaje se recorta al largo de la columna en vez de dejar que la base lo rechace: un
    error de registro no puede convertirse en un error al *guardar* el error, que dejaría la
    factura en `PENDING` para siempre y sin explicación.
    """
    invoice.balance360_status = Balance360Status.FAILED
    invoice.balance360_error = error[:300]
    invoice.balance360_synced_at = func.now()
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
