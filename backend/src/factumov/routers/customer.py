import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from factumov.crud import customer as customer_crud
from factumov.dependencies import (
    CurrentUserDep,
    SessionDep,
    enforce_rate_limit,
    get_current_user,
)
from factumov.exceptions import (
    ArcaError,
    CustomerInUseError,
    DuplicateCustomerError,
    DuplicateError,
    InUseError,
    PadronError,
)
from factumov.models import Customer
from factumov.schemas.customer import (
    CustomerCreate,
    CustomerRead,
    CustomerUpdate,
    TaxpayerLookup,
)
from factumov.services import padron
from factumov.services.rate_limit import RateLimiter

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

# La cuota del padrón la fija ARCA contra **el certificado**, que es uno solo para toda la
# app: un usuario tecleando CUITs en un loop se la gasta para todos los demás. Por eso el
# límite va por usuario y no por IP —el endpoint está autenticado, así que hay una clave
# mejor que la dirección— y por eso existe aunque acá no haya nada que enumerar.
#
# Treinta por hora es holgado para cargar clientes a mano y corto para un script.
_PADRON_LIMITER = RateLimiter(limit=30, window_seconds=60 * 60)


@router.get("", response_model=list[CustomerRead])
def list_customers(db: SessionDep, user: CurrentUserDep) -> list[Customer]:
    return customer_crud.get_all(db, user.id)


@router.get("/lookup/{tax_id}", response_model=TaxpayerLookup)
def lookup_taxpayer(tax_id: str, user: CurrentUserDep) -> TaxpayerLookup:
    """Los datos de un CUIT según el padrón de ARCA, para prellenar el alta de un cliente.

    **No escribe nada**, igual que `POST /invoice-templates/import`: devuelve una propuesta
    que el usuario revisa y recién después confirma con `POST /customers`. Dar de alta acá
    convertiría una consulta en un efecto secundario, y consultar dos veces el mismo CUIT
    dejaría dos clientes.

    **404** cuando ARCA no tiene datos de ese CUIT, o cuando lo que llegó no es un CUIT: la
    consulta funcionó y la respuesta es que no hay nadie. **502** cuando no se pudo preguntar.
    Son cosas distintas y por eso `PadronError` no baja de `ArcaError`.

    No hace falta que el usuario haya delegado nada: el padrón se consulta con FactuMov como
    `cuitRepresentada`. La delegación hace falta para *emitir* por un CUIT ajeno, no para
    consultar el padrón.

    La ruta lleva el CUIT en el path y no en un query param sobre `/customers/lookup` a
    secas, que colisionaría con `GET /{customer_id}` y daría un 422 por UUID inválido.
    """
    enforce_rate_limit(_PADRON_LIMITER, str(user.id))

    try:
        taxpayer = padron.get_taxpayer(tax_id)
    except PadronError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ArcaError:
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar el padrón de ARCA, reintentá más tarde",
        )

    return TaxpayerLookup(
        doc_number=taxpayer.tax_id,
        name=taxpayer.name,
        condicion_iva=taxpayer.condicion_iva,
        address=taxpayer.address,
        active=taxpayer.active,
    )


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
