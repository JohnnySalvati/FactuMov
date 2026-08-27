"""Acceso a datos de `password_resets`.

Calcado de `crud/email_confirmation.py`, con una función de más: `invalidate_all_for_user`.
El vencimiento se compara en SQL (`func.now()`) y no trayendo la fila a Python, por las
mismas dos razones de siempre —una sola fuente de verdad para "ahora", y nada de mezclar un
`datetime` naive con uno aware—. El detalle está en CLAUDE.md → *Autenticación → Sesiones*.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from factumov.models.password_reset import PasswordReset


def create(db: Session, user_id: UUID, token_hash: str, expires_at: datetime) -> PasswordReset:
    reset = PasswordReset(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(reset)
    db.flush()
    return reset


def get_pending_by_token_hash(db: Session, token_hash: str) -> PasswordReset | None:
    """El token vivo y sin usar, con su usuario ya cargado.

    Las tres causas de `None` —hash desconocido, vencido, ya consumido— se colapsan acá a
    propósito: el endpoint contesta lo mismo para las tres y así no tiene forma de
    distinguirlas por descuido.
    """
    return (
        db.execute(
            select(PasswordReset)
            .where(
                PasswordReset.token_hash == token_hash,
                PasswordReset.expires_at > func.now(),
                PasswordReset.used_at.is_(None),
            )
            .options(joinedload(PasswordReset.user))
        )
        .scalars()
        .first()
    )


def consume(db: Session, reset: PasswordReset) -> None:
    """Marca el token como usado, sin borrar la fila."""
    reset.used_at = func.now()
    db.flush()


def invalidate_all_for_user(db: Session, user_id: UUID) -> None:
    """Quema los demás tokens de reset vivos de ese usuario.

    Es la diferencia de fondo con la confirmación de email, donde dos links vivos son
    inofensivos —los dos hacen lo mismo, y lo que hacen ya está hecho—. Un token de reset sin
    usar es la capacidad de cambiar la contraseña otra vez: dejarlo vivo después de un reset
    le deja al que pidió el primero una segunda oportunidad de entrar, que es exactamente el
    escenario del que se está sacando al usuario cuando el reset lo pidió porque sospechaba
    algo.

    Un `UPDATE` masivo y no un `for` sobre las filas: son pocas, pero traerlas para escribir
    en cada una es un ida y vuelta por token sin ganar nada. El filtro por `used_at` es para
    no pisar la marca de uno que ya se consumió, que es un dato de auditoría.
    """
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user_id, PasswordReset.used_at.is_(None))
        .values(used_at=func.now())
    )
    db.flush()
