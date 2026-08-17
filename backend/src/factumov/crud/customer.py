from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from factumov.crud.base import db_flush
from factumov.enums import DocType
from factumov.exceptions import CustomerInUseError, DocNumberCheckError, DuplicateCustomerError
from factumov.models.customer import Customer
from factumov.schemas.customer import CustomerCreate, CustomerUpdate

exception_map = {
    "ck_customers_doc_number_required": DocNumberCheckError,
    "uq_customers_doc_type_doc_number": DuplicateCustomerError,
    "invoice_templates_customer_id_fkey": CustomerInUseError,
}


def get_all(db: Session) -> list[Customer]:
    customers = db.execute(select(Customer)).scalars().all()
    return list(customers)


def get_by_id(db: Session, customer_id: UUID) -> Customer | None:
    return db.get(Customer, customer_id)


def get_by_doc(db: Session, doc_type: DocType, doc_number: str | None) -> Customer | None:
    if doc_number is None:
        return None
    return (
        db.execute(
            select(Customer).where(Customer.doc_type == doc_type, Customer.doc_number == doc_number)
        )
        .scalars()
        .first()
    )


def create(db: Session, data: CustomerCreate) -> Customer:
    db_customer = Customer(**data.model_dump())
    db.add(db_customer)
    db_flush(db, exception_map)
    return db_customer


def update(db: Session, customer: Customer, data: CustomerUpdate) -> Customer:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db_flush(db, exception_map)
    return customer


def update_or_create(db: Session, data: CustomerCreate) -> Customer:
    if data.doc_type == DocType.FINAL:
        return create(db, data)

    db_customer = get_by_doc(db, data.doc_type, data.doc_number)

    if not db_customer:
        return create(db, data)

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(db_customer, field, value)
    db_flush(db, exception_map)
    return db_customer


def delete(db: Session, customer: Customer) -> None:
    db.delete(customer)
    db_flush(db, exception_map)
