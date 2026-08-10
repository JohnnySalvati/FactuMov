from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from factumov.enums import DocType
from factumov.models.customer import Customer
from factumov.schemas.customer import CustomerCreate, CustomerUpdate


def get_all(db: Session) -> list[Customer]:
    customers = db.execute(select(Customer)).scalars().all()
    return list(customers)


def get_by_id(db: Session, customer_id: UUID) -> Customer | None:
    return db.get(Customer, customer_id)


def create(db: Session, data: CustomerCreate) -> Customer:
    db_customer = Customer(**data.model_dump())
    db.add(db_customer)
    db.flush()
    return db_customer


def update(db: Session, customer: Customer, data: CustomerUpdate) -> Customer:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db.flush()
    return customer


def update_or_create(db: Session, data: CustomerCreate) -> Customer:
    if data.doc_type == DocType.FINAL:
        return create(db, data)

    db_customer = (
        db.execute(
            select(Customer).where(
                Customer.doc_type == data.doc_type, Customer.doc_number == data.doc_number
            )
        )
        .scalars()
        .first()
    )

    if not db_customer:
        return create(db, data)

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(db_customer, field, value)
    db.flush()
    return db_customer


def delete(db: Session, customer: Customer) -> None:
    db.delete(customer)
    db.flush()
