"""Acceso a datos de `customers`, siempre scopeado al usuario.

Todas las lecturas llevan `user_id` en la firma, incluso `get_by_id`, que antes usaba
`db.get()`. El cambio no es cosmético: `db.get()` busca por clave primaria y no admite
filtro, así que devolvía la fila de cualquier usuario y dejaba la comparación de dueño en
manos del que llamara. Filtrar en la query hace que la fila ajena simplemente no exista
para el que consulta, que es lo que produce el 404 sin ninguna rama que pueda equivocarse
y contestar 403.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from factumov.crud.base import db_flush
from factumov.enums import DocType
from factumov.exceptions import CustomerInUseError, DuplicateCustomerError
from factumov.models.customer import Customer
from factumov.schemas.customer import CustomerCreate, CustomerUpdate

exception_map = {
    "uq_customers_user_id_doc_type_doc_number": DuplicateCustomerError,
    "invoice_templates_customer_id_fkey": CustomerInUseError,
    # Ídem para el cliente: si se le emitió una factura, la fila se queda. El nombre y el
    # domicilio que salieron impresos están copiados en la factura, así que lo que se pierde
    # al no poder borrarlo es solo el orden de la lista de clientes.
    "invoices_customer_id_fkey": CustomerInUseError,
}


def get_all(db: Session, user_id: UUID) -> list[Customer]:
    customers = db.execute(select(Customer).where(Customer.user_id == user_id)).scalars().all()
    return list(customers)


def get_by_id(db: Session, customer_id: UUID, user_id: UUID) -> Customer | None:
    return (
        db.execute(select(Customer).where(Customer.id == customer_id, Customer.user_id == user_id))
        .scalars()
        .first()
    )


def get_by_doc(
    db: Session, doc_type: DocType, doc_number: str | None, user_id: UUID
) -> Customer | None:
    if doc_number is None:
        return None
    return (
        db.execute(
            select(Customer).where(
                Customer.user_id == user_id,
                Customer.doc_type == doc_type,
                Customer.doc_number == doc_number,
            )
        )
        .scalars()
        .first()
    )


def create(db: Session, data: CustomerCreate, user_id: UUID) -> Customer:
    # `user_id` es un argumento y no un campo del schema: sale de la sesión, nunca del
    # body. Aceptarlo por el body dejaría al cliente elegir a nombre de quién escribe.
    db_customer = Customer(**data.model_dump(), user_id=user_id)
    db.add(db_customer)
    db_flush(db, exception_map)
    return db_customer


def update(db: Session, customer: Customer, data: CustomerUpdate) -> Customer:
    # Sin `user_id`: la fila llegó de un getter ya scopeado, así que es del usuario.
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db_flush(db, exception_map)
    return customer


def update_or_create(db: Session, data: CustomerCreate, user_id: UUID) -> Customer:
    db_customer = get_by_doc(db, data.doc_type, data.doc_number, user_id)

    if not db_customer:
        return create(db, data, user_id)

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(db_customer, field, value)
    db_flush(db, exception_map)
    return db_customer


def delete(db: Session, customer: Customer) -> None:
    db.delete(customer)
    db_flush(db, exception_map)
