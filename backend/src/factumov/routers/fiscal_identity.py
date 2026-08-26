import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.dependencies import SessionDep, get_current_user
from factumov.exceptions import (
    DuplicateError,
    DuplicateFiscalIdentityNameError,
    DuplicateFiscalIdentityTaxIdError,
    FiscalIdentityInUseError,
    InUseError,
)
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.schemas.fiscal_identity import (
    FiscalIdentityCreate,
    FiscalIdentityRead,
    FiscalIdentityUpdate,
)

router = APIRouter(
    prefix="/fiscal-identities",
    tags=["fiscal_identities"],
    dependencies=[Depends(get_current_user)],
)


def get_fiscal_identity_or_404(fiscal_identity_id: uuid.UUID, db: SessionDep) -> FiscalIdentity:
    fiscal_identity = fiscal_identity_crud.get_by_id(db, fiscal_identity_id)
    if fiscal_identity is None:
        raise HTTPException(status_code=404, detail="Identidad fiscal no encontrada")
    return fiscal_identity


FiscalIdentityDep = Annotated[FiscalIdentity, Depends(get_fiscal_identity_or_404)]


@router.get("", response_model=list[FiscalIdentityRead])
def list_fiscal_identities(db: SessionDep) -> list[FiscalIdentity]:
    return fiscal_identity_crud.get_all(db)


@router.get("/{fiscal_identity_id}", response_model=FiscalIdentityRead)
def get_fiscal_identity(fiscal_identity: FiscalIdentityDep) -> FiscalIdentity:
    return fiscal_identity


@router.post("", response_model=FiscalIdentityRead, status_code=201)
def create_fiscal_identity(data: FiscalIdentityCreate, db: SessionDep) -> FiscalIdentity:
    try:
        fiscal_identity = fiscal_identity_crud.create(db, data)
    except DuplicateFiscalIdentityNameError:
        raise HTTPException(status_code=409, detail="Nombre duplicado")
    except DuplicateFiscalIdentityTaxIdError:
        raise HTTPException(status_code=409, detail="CUIT duplicado")
    except DuplicateError:
        raise HTTPException(status_code=409, detail="Duplicado")
    return fiscal_identity


@router.patch("/{fiscal_identity_id}", response_model=FiscalIdentityRead)
def update_fiscal_identity(
    data: FiscalIdentityUpdate, fiscal_identity: FiscalIdentityDep, db: SessionDep
) -> FiscalIdentity:
    try:
        fiscal_identity = fiscal_identity_crud.update(db, fiscal_identity, data)
    except DuplicateFiscalIdentityNameError:
        raise HTTPException(status_code=409, detail="Nombre duplicado")
    except DuplicateFiscalIdentityTaxIdError:
        raise HTTPException(status_code=409, detail="CUIT duplicado")
    except DuplicateError:
        raise HTTPException(status_code=409, detail="Duplicado")
    return fiscal_identity


@router.delete("/{fiscal_identity_id}", status_code=204)
def delete_fiscal_identity(
    fiscal_identity: FiscalIdentityDep,
    db: SessionDep,
) -> None:
    try:
        fiscal_identity_crud.delete(db, fiscal_identity)
    except FiscalIdentityInUseError:
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar una identidad fiscal con modelos asociados",
        )
    except InUseError:
        raise HTTPException(status_code=409, detail="No se puede eliminar, existen asociaciones")
