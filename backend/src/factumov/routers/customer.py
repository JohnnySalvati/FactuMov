import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from factumov.crud import customer as customer_crud
from factumov.dependencies import CurrentUserDep, SessionDep, get_current_user
from factumov.exceptions import (
    CustomerInUseError,
    DuplicateCustomerError,
    DuplicateError,
    InUseError,
)
from factumov.models import Customer
from factumov.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate

# La dependencia a nivel de router se queda aunque los endpoints ya pidan `CurrentUserDep`:
# es el default-deny para el endpoint que se agregue mañana sin acordarse. FastAPI cachea la
# dependencia por request, así que resolverla dos veces no cuesta nada.
router = APIRouter(
    prefix="/customers",
    tags=["customers"],
    dependencies=[Depends(get_current_user)],
)


def get_customer_or_404(customer_id: uuid.UUID, db: SessionDep, user: CurrentUserDep) -> Customer:
    """404 sobre el cliente de otro usuario, nunca 403.

    No hay ninguna comparación de dueños acá: el getter ya filtra por `user_id`, así que la
    fila ajena y la fila inexistente son el mismo caso y no hay forma de que una rama
    conteste 403 por descuido. Un 403 confirmaría que ese id existe.
    """
    customer = customer_crud.get_by_id(db, customer_id, user.id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return customer


CustomerDep = Annotated[Customer, Depends(get_customer_or_404)]


@router.get("", response_model=list[CustomerRead])
def list_customers(db: SessionDep, user: CurrentUserDep) -> list[Customer]:
    return customer_crud.get_all(db, user.id)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer: CustomerDep) -> Customer:
    return customer


@router.post("", response_model=CustomerRead, status_code=201)
def create_customer(data: CustomerCreate, db: SessionDep, user: CurrentUserDep) -> Customer:
    try:
        customer = customer_crud.create(db, data, user.id)
    except DuplicateCustomerError:
        raise HTTPException(status_code=409, detail="Numero de documento/CUIT duplicado")
    except DuplicateError:
        raise HTTPException(status_code=409, detail="Duplicado")
    return customer


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(data: CustomerUpdate, customer: CustomerDep, db: SessionDep) -> Customer:
    try:
        customer = customer_crud.update(db, customer, data)
    except DuplicateCustomerError:
        raise HTTPException(status_code=409, detail="Numero de documento/CUIT duplicado")
    except DuplicateError:
        raise HTTPException(status_code=409, detail="Duplicado")
    return customer


@router.delete("/{customer_id}", status_code=204)
def delete_customer(
    customer: CustomerDep,
    db: SessionDep,
) -> None:
    try:
        customer_crud.delete(db, customer)
    except CustomerInUseError:
        raise HTTPException(
            status_code=409, detail="No se puede eliminar un cliente con modelos asociados"
        )
    except InUseError:
        raise HTTPException(status_code=409, detail="No se puede eliminar, existen asociaciones")
