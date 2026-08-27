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

    Borra el aviso del usuario, que ya cumplió su función: existía para explicar por qué una
    delegación que él dice haber otorgado todavía no anda. Contestada esa pregunta, dejarlo
    puesto haría que los tres estados de la pantalla dejaran de ser excluyentes. Y si algún día
    la delegación se revoca, el aviso que corresponde es uno nuevo y no el de hace un año.
    """
    fiscal_identity.delegation_verified_at = func.now()
    fiscal_identity.delegation_claimed_at = None
    db_flush(db, exception_map)
    return fiscal_identity


def mark_delegation_claimed(db: Session, fiscal_identity: FiscalIdentity) -> FiscalIdentity:
    """Registra que el usuario dice haber otorgado la delegación, con ARCA diciendo que no.

    Es lo único que separa "todavía no delegó" de "delegó y falta que FactuMov acepte la
    designación", porque WSFE contesta el mismo 600 en los dos casos — ver
    `models/fiscal_identity.py`.

    No se pisa si ya había uno. La fecha que importa es la del **primer** aviso: es la que
    mide cuánto hace que esa persona está esperando, y es la que acota el reenvío del mail al
    operador. Pisarla con cada click convertiría un botón en un generador de mails.
    """
    if fiscal_identity.delegation_claimed_at is None:
        fiscal_identity.delegation_claimed_at = func.now()
        db_flush(db, exception_map)
    return fiscal_identity


def clear_delegation_verified(db: Session, fiscal_identity: FiscalIdentity) -> FiscalIdentity:
    """ARCA dice que ya no estamos delegados para este CUIT: la verificación deja de valer.

    `delegation_verified_at` siempre significó "esto era verdad en esta fecha" y no "esto es
    verdad" — la delegación se revoca del lado de ARCA sin avisarnos. Esto es lo que hace que
    esa distinción tenga consecuencias en vez de ser una nota al pie: cuando una verificación
    vuelve negativa, la columna se limpia y la identidad deja de poder emitir.

    Solo se llega acá con un `granted=False`, que es el código 600 y nada más. Cualquier otra
    respuesta de ARCA levanta excepción en `wsfe.check_delegation` justamente para que una
    respuesta ambigua no pueda desverificar a nadie.
    """
    fiscal_identity.delegation_verified_at = None
    db_flush(db, exception_map)
    return fiscal_identity
