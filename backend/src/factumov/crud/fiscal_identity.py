import uuid

from sqlalchemy import select
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
    "fiscal_identities_name_key": DuplicateFiscalIdentityNameError,
    "fiscal_identities_tax_id_key": DuplicateFiscalIdentityTaxIdError,
    "invoice_templates_fiscal_identity_id_fkey": FiscalIdentityInUseError,
}


def get_all(db: Session) -> list[FiscalIdentity]:
    fiscal_identities = db.execute(select(FiscalIdentity)).scalars().all()
    return list(fiscal_identities)


def get_by_id(db: Session, fiscal_identity_id: uuid.UUID) -> FiscalIdentity | None:
    return db.get(FiscalIdentity, fiscal_identity_id)


def get_by_tax_id(db: Session, tax_id: str) -> FiscalIdentity | None:
    return (
        db.execute(select(FiscalIdentity).where(FiscalIdentity.tax_id == tax_id)).scalars().first()
    )


def create(db: Session, data: FiscalIdentityCreate) -> FiscalIdentity:
    fiscal_identity = FiscalIdentity(**data.model_dump())
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
