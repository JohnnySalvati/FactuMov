"""add subscription_payments

Revision ID: b6f4a2c98d31
Revises: e8a3c5f21d47
Create Date: 2026-09-01

Los cobros que informa el proveedor. La tabla es a la vez el historial —de qué se le cobró a
cada cuenta— y el registro de idempotencia del webhook de Mercado Pago, que reintenta y manda
el mismo evento más de una vez. Ver *Monetización*.

**No hay backfill y no puede haberlo.** Ninguna cuenta pagó todavía: hasta esta unidad no
existía el checkout, así que no hay cobros anteriores que reconstruir. Es lo contrario de
`e8a3c5f21d47`, que sí inventó un dato —el trial de las cuentas que ya existían— porque ahí
había una decisión de producto que tomar; acá inventar una fila sería inventar plata que nadie
pagó.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b6f4a2c98d31"
down_revision: Union[str, Sequence[str], None] = "e8a3c5f21d47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Como el resto de los enums del proyecto, la columna guarda el **nombre** del miembro.
_PAYMENT_STATUS_LABELS = ("APPROVED", "REJECTED")


def upgrade() -> None:
    """Upgrade schema."""
    # `billingprovider` ya existe: lo creó `e8a3c5f21d47`. Se lo referencia con
    # `create_type=False` y sin `create()` para no intentar darlo de alta de nuevo — el
    # `checkfirst` alcanzaría, pero decirlo explícito deja claro cuál de los dos tipos es
    # nuevo en esta revisión y cuál se está reusando.
    provider = postgresql.ENUM(name="billingprovider", create_type=False)
    status = postgresql.ENUM(*_PAYMENT_STATUS_LABELS, name="paymentstatus", create_type=False)
    status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "subscription_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("provider", provider, nullable=False),
        sa.Column("provider_payment_id", sa.String(length=64), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("charged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"]),
        sa.PrimaryKeyConstraint("id"),
        # **La restricción que hace de antiduplicado.** El chequeo del servicio pierde contra
        # dos entregas simultáneas del mismo webhook; esto no. Sin ella, tres reintentos de
        # Mercado Pago empujarían el período tres meses.
        sa.UniqueConstraint("provider_payment_id"),
    )
    # La lectura natural es "los cobros de esta suscripción". Índice y no unique: son varios
    # por fila, uno por mes.
    op.create_index(
        op.f("ix_subscription_payments_subscription_id"),
        "subscription_payments",
        ["subscription_id"],
    )


def downgrade() -> None:
    """Downgrade schema.

    Se pierde el historial de cobros, que no se puede re-deducir de ninguna otra tabla: lo que
    queda en `subscriptions` es hasta cuándo llega el período, no de qué se cobró para llegar
    ahí. Y se pierde el antiduplicado: con esta tabla caída, un webhook que se reintente vuelve
    a aplicar un cobro que ya se había aplicado.
    """
    op.drop_index(
        op.f("ix_subscription_payments_subscription_id"), table_name="subscription_payments"
    )
    op.drop_table("subscription_payments")
    # `billingprovider` **no** se borra: lo sigue usando `subscriptions.provider`, que es de la
    # revisión anterior. Solo se va el que esta revisión creó.
    sa.Enum(name="paymentstatus").drop(op.get_bind(), checkfirst=True)
