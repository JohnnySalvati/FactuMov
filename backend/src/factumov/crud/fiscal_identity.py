"""Acceso a datos de `fiscal_identities`, siempre scopeado al usuario.

Mismo criterio que `crud/customer.py`: el filtro va en la query, no en una comparación
posterior, para que la identidad fiscal de otro usuario no exista desde el punto de vista
del que consulta.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factumov.crud.base import db_flush
from factumov.exceptions import (
    DuplicateFiscalIdentityNameError,
    DuplicateFiscalIdentityTaxIdError,
    FiscalIdentityInUseError,
)
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.schemas.fiscal_identity import FiscalIdentityCreate, FiscalIdentityUpdate

exception_map = {
    "uq_fiscal_identities_user_id_name": DuplicateFiscalIdentityNameError,
    "uq_fiscal_identities_user_id_tax_id": DuplicateFiscalIdentityTaxIdError,
    "invoice_templates_fiscal_identity_id_fkey": FiscalIdentityInUseError,
    # Una identidad fiscal con facturas emitidas no se borra nunca, ni siquiera borrando
    # antes sus modelos: las facturas son el respaldo de comprobantes que existen en ARCA.
    "invoices_fiscal_identity_id_fkey": FiscalIdentityInUseError,
}


def get_all(db: Session, user_id: uuid.UUID) -> list[FiscalIdentity]:
    fiscal_identities = (
        db.execute(select(FiscalIdentity).where(FiscalIdentity.user_id == user_id)).scalars().all()
    )
    return list(fiscal_identities)


def get_by_id(
    db: Session, fiscal_identity_id: uuid.UUID, user_id: uuid.UUID
) -> FiscalIdentity | None:
    return (
        db.execute(
            select(FiscalIdentity).where(
                FiscalIdentity.id == fiscal_identity_id, FiscalIdentity.user_id == user_id
            )
        )
        .scalars()
        .first()
    )


def get_by_tax_id(db: Session, tax_id: str, user_id: uuid.UUID) -> FiscalIdentity | None:
    return (
        db.execute(
            select(FiscalIdentity).where(
                FiscalIdentity.user_id == user_id, FiscalIdentity.tax_id == tax_id
            )
        )
        .scalars()
        .first()
    )


def create(db: Session, data: FiscalIdentityCreate, user_id: uuid.UUID) -> FiscalIdentity:
    fiscal_identity = FiscalIdentity(**data.model_dump(), user_id=user_id)
    db.add(fiscal_identity)
    db_flush(db, exception_map)
    return fiscal_identity


def update(
    db: Session, fiscal_identity: FiscalIdentity, data: FiscalIdentityUpdate
) -> FiscalIdentity:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(fiscal_identity, field, value)
    db_flush(db, exception_map)
    return fiscal_identity


def delete(db: Session, fiscal_identity: FiscalIdentity) -> None:
    db.delete(fiscal_identity)
    db_flush(db, exception_map)


def mark_delegation_verified(db: Session, fiscal_identity: FiscalIdentity) -> FiscalIdentity:
    """Deja sellado que ARCA aceptó la delegación recién ahora.

    `func.now()` y no `datetime.now()`, igual que `user_session.revoke`: el reloj es el de la
    base, que es el mismo con el que se comparan las demás fechas.
    """
    fiscal_identity.delegation_verified_at = func.now()
    db_flush(db, exception_map)
    return fiscal_identity
