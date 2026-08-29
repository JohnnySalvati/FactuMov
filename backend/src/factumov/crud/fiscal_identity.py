"""Acceso a datos de `fiscal_identities`, scopeado al usuario salvo una excepción.

Mismo criterio que `crud/customer.py`: el filtro va en la query, no en una comparación
posterior, para que la identidad fiscal de otro usuario no exista desde el punto de vista
del que consulta.

La excepción es `get_by_claim_token_hash`, que busca por el token del link que le llega al
operador. Ahí no hay sesión de la cual scopear y lo que autoriza es el token — está explicado
en su docstring.
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
    # Y con el aviso se va su link. El del mail al operador existe para acortar *esta* espera:
    # una vez contestada, dejarlo vivo sería una credencial sin dueño, sin vencimiento y capaz
    # de gastar cuota de ARCA —que es del certificado y por lo tanto de todos los usuarios—
    # cada vez que alguien la apriete. La borra este lugar y no el endpoint porque las dos
    # formas de verificar, el click y el barrido, pasan por acá.
    fiscal_identity.delegation_claim_token_hash = None
    db_flush(db, exception_map)
    return fiscal_identity


def mark_delegation_claimed(
    db: Session, fiscal_identity: FiscalIdentity, token_hash: str
) -> FiscalIdentity:
    """Registra que el usuario dice haber otorgado la delegación, con ARCA diciendo que no.

    Es lo único que separa "todavía no delegó" de "delegó y falta que FactuMov acepte la
    designación", porque WSFE contesta el mismo 600 en los dos casos — ver
    `models/fiscal_identity.py`.

    No se pisa si ya había uno. La fecha que importa es la del **primer** aviso: es la que
    mide cuánto hace que esa persona está esperando, y es la que acota el reenvío del mail al
    operador. Pisarla con cada click convertiría un botón en un generador de mails.

    `token_hash` es el SHA-256 del token que va en el link del mail al operador. Lo genera el
    router y no este módulo, igual que el de confirmación de mail: el token crudo tiene que
    llegar al mail y no a la base, así que quien lo emite es quien manda el mail.
    """
    if fiscal_identity.delegation_claimed_at is None:
        fiscal_identity.delegation_claimed_at = func.now()
        # El token del link viaja con el aviso y se guarda en el mismo `if`, que es lo que hace
        # que no puedan desincronizarse: el link se emite exactamente cuando se emite el mail
        # que lo lleva, o sea una sola vez. Guardarlo afuera del `if` pisaría el token del mail
        # que el operador quizás tiene abierto, y ese link dejaría de andar sin que nada lo
        # explique — el mismo problema que `email_confirmations` resuelve con filas.
        fiscal_identity.delegation_claim_token_hash = token_hash
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


def get_by_claim_token_hash(db: Session, token_hash: str) -> FiscalIdentity | None:
    """La identidad que espera aceptación, buscada por el token del link del mail al operador.

    **La única lectura de este módulo sin `user_id`, y es a propósito.** Todas las demás
    scopean porque quien consulta es un usuario logueado y la identidad de otro no tiene que
    existir para él. Acá no hay sesión: quien llega es el operador, que no es el dueño de la
    fila y no podría serlo nunca. Lo que autoriza el pedido es el token, y por eso el token
    tiene los 256 bits que tiene.

    Pide `delegation_claim_token_hash` no nulo además de comparar, para que un `token_hash`
    vacío o `None` que se colara no pudiera enganchar a la primera fila sin token.
    """
    return (
        db.execute(
            select(FiscalIdentity).where(
                FiscalIdentity.delegation_claim_token_hash.is_not(None),
                FiscalIdentity.delegation_claim_token_hash == token_hash,
            )
        )
        .scalars()
        .first()
    )
