import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from factumov.crud import customer as customer_crud
from factumov.database import get_db
from factumov.models import Customer
from factumov.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])


SessionDep = Annotated[Session, Depends(get_db)]


def get_customer_or_404(customer_id: uuid.UUID, db: SessionDep) -> Customer:
    customer = customer_crud.get_by_id(db, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return customer


CustomerDep = Annotated[Customer, Depends(get_customer_or_404)]


@router.get("", response_model=list[CustomerRead])
def list_customers(db: SessionDep) -> list[Customer]:
    return customer_crud.get_all(db)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer: CustomerDep) -> Customer:
    return customer


@router.post("", response_model=CustomerRead, status_code=201)
def create_customer(data: CustomerCreate, db: SessionDep) -> Customer:
    return customer_crud.create(db, data)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(data: CustomerUpdate, customer: CustomerDep, db: SessionDep) -> Customer:
    return customer_crud.update(db, customer, data)


@router.delete("/{customer_id}", status_code=204)
def delete_customer(
    customer: CustomerDep,
    db: SessionDep,
) -> None:
    customer_crud.delete(db, customer)
