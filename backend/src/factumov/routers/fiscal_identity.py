import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.dependencies import (
    CurrentUserDep,
    SessionDep,
    enforce_rate_limit,
    get_current_user,
)
from factumov.exceptions import (
    ArcaError,
    DuplicateError,
    DuplicateFiscalIdentityNameError,
    DuplicateFiscalIdentityTaxIdError,
    FiscalIdentityInUseError,
    InUseError,
)
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.schemas.fiscal_identity import (
    DelegationStatus,
    FiscalIdentityCreate,
    FiscalIdentityRead,
    FiscalIdentityUpdate,
)
from factumov.services import arca, wsfe
from factumov.services.rate_limit import RateLimiter

router = APIRouter(
    prefix="/fiscal-identities",
    tags=["fiscal_identities"],
    dependencies=[Depends(get_current_user)],
)


def get_fiscal_identity_or_404(
    fiscal_identity_id: uuid.UUID, db: SessionDep, user: CurrentUserDep
) -> FiscalIdentity:
    """404 sobre la identidad fiscal de otro usuario — ver `routers/customer.py`."""
    fiscal_identity = fiscal_identity_crud.get_by_id(db, fiscal_identity_id, user.id)
    if fiscal_identity is None:
        raise HTTPException(status_code=404, detail="Identidad fiscal no encontrada")
    return fiscal_identity


FiscalIdentityDep = Annotated[FiscalIdentity, Depends(get_fiscal_identity_or_404)]

# Verificar la delegación sale a WSAA y a WSFE, y esa cuota la fija ARCA contra el
# certificado de FactuMov, que es uno solo para todos los usuarios. Diez por hora es de sobra
# para alguien que acaba de entrar a ARCA y viene a apretar "ya está": la delegación no
# cambia varias veces por hora.
_VERIFY_DELEGATION_LIMITER = RateLimiter(limit=10, window_seconds=60 * 60)


@router.get("", response_model=list[FiscalIdentityRead])
def list_fiscal_identities(db: SessionDep, user: CurrentUserDep) -> list[FiscalIdentity]:
    return fiscal_identity_crud.get_all(db, user.id)


@router.get("/{fiscal_identity_id}", response_model=FiscalIdentityRead)
def get_fiscal_identity(fiscal_identity: FiscalIdentityDep) -> FiscalIdentity:
    return fiscal_identity


@router.post("", response_model=FiscalIdentityRead, status_code=201)
def create_fiscal_identity(
    data: FiscalIdentityCreate, db: SessionDep, user: CurrentUserDep
) -> FiscalIdentity:
    try:
        fiscal_identity = fiscal_identity_crud.create(db, data, user.id)
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


@router.post("/{fiscal_identity_id}/verify-delegation", response_model=DelegationStatus)
def verify_delegation(
    fiscal_identity: FiscalIdentityDep, db: SessionDep, user: CurrentUserDep
) -> DelegationStatus:
    """Le pregunta a ARCA si FactuMov ya puede emitir por este CUIT.

    **200 con `granted=False`** cuando la delegación no está: el request estaba bien hecho y
    la respuesta es simplemente que no. Un 4xx haría que la UI tuviera que distinguir "te
    equivocaste" de "todavía no autorizaste", que son cosas distintas.

    **502** cuando no se pudo preguntar —ARCA caído, certificado mal configurado, respuesta
    ilegible—. El detalle no se propaga: "WSAA rechazó el TRA" no le dice nada al usuario y sí
    filtra cómo está armado nuestro lado. El traceback queda en el log.

    Es POST y no GET aunque parezca una consulta: sale a la red, tarda segundos y **escribe**
    `delegation_verified_at`. Un GET con esos tres atributos es algo que un proxy o un
    prefetch del navegador pueden repetir solos.
    """
    enforce_rate_limit(_VERIFY_DELEGATION_LIMITER, str(user.id))

    # El commit cierra la transacción del request *antes* de la llamada SOAP, que puede tardar
    # decenas de segundos. Sin esto, la conexión a Postgres se queda tomada y con una
    # transacción abierta todo ese rato — el mismo problema, y la misma solución, que el
    # commit explícito del registro antes de mandar el mail. `rollback()` no sirve: bajo el
    # `join_transaction_mode="create_savepoint"` del fixture de tests revertiría al savepoint
    # y se llevaría puestas las filas que el test armó.
    tax_id = fiscal_identity.tax_id
    db.commit()

    try:
        check = wsfe.check_delegation(tax_id)
    except ArcaError:
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar el estado de la delegación en ARCA, reintentá más tarde",
        )

    if not check.granted:
        return DelegationStatus(
            granted=False,
            message=check.message,
            delegation_verified_at=fiscal_identity.delegation_verified_at,
            delegate_tax_id=arca.get_delegate_tax_id(),
        )

    fiscal_identity_crud.mark_delegation_verified(db, fiscal_identity)
    # Refresca el `func.now()` que quedó como expresión SQL sin evaluar, para poder
    # devolver el timestamp real y no un objeto de SQLAlchemy.
    db.commit()
    db.refresh(fiscal_identity)
    return DelegationStatus(
        granted=True,
        delegation_verified_at=fiscal_identity.delegation_verified_at,
    )
