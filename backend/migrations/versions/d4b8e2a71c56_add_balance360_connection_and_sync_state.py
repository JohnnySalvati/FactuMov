"""add balance360 connection and invoice sync state

Revision ID: d4b8e2a71c56
Revises: c8a1e4f60b92
Create Date: 2026-08-29

Las dos mitades de la integración con Balance360 del lado de FactuMov:

- `balance360_connections`, una por usuario: a qué instalación se le habla y con qué token
  (cifrado, no hasheado — hay que poder mandarlo).
- Cuatro columnas en `invoices` con el estado de la copia del otro lado.

Las cuatro son nullable y el default es NULL, que no es "pendiente": son las facturas que se
emitieron antes de que existiera la integración y que no tienen nada que registrar. Hacerlas
`PENDING` con un `server_default` habría puesto todo el historial en la cola de reintentos.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4b8e2a71c56"
down_revision: Union[str, Sequence[str], None] = "c8a1e4f60b92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# La columna guarda el **nombre** del miembro, no su valor: es lo que hace `Enum(...)` de
# SQLAlchemy sin `values_callable`, igual que el resto de los enums del proyecto.
_STATUS_LABELS = ("PENDING", "REGISTERED", "FAILED")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "balance360_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("base_url", sa.String(length=200), nullable=False),
        sa.Column("encrypted_token", sa.String(length=500), nullable=False),
        sa.Column("token_hint", sa.String(length=8), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "auto_register", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # Unique y no index a secas: "la conexión del usuario" tiene que ser una sola fila.
        sa.UniqueConstraint("user_id"),
    )

    # `create_type=False` en la columna y el `create()` explícito antes, como en
    # `3610e7b47b8a`: con la creación implícita, un `add_column` que falla deja el tipo dado
    # de alta y el reintento revienta con "type already exists".
    status = postgresql.ENUM(*_STATUS_LABELS, name="balance360status", create_type=False)
    status.create(op.get_bind(), checkfirst=True)

    op.add_column("invoices", sa.Column("balance360_status", status, nullable=True))
    op.add_column("invoices", sa.Column("balance360_invoice_id", sa.Uuid(), nullable=True))
    op.add_column("invoices", sa.Column("balance360_error", sa.String(length=300), nullable=True))
    op.add_column(
        "invoices", sa.Column("balance360_synced_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("invoices", "balance360_synced_at")
    op.drop_column("invoices", "balance360_error")
    op.drop_column("invoices", "balance360_invoice_id")
    op.drop_column("invoices", "balance360_status")
    # El tipo no se va solo con la columna: `CREATE TYPE` es una operación de esquema aparte
    # y sin este drop el downgrade deja la base a medio revertir.
    sa.Enum(name="balance360status").drop(op.get_bind(), checkfirst=True)
    op.drop_table("balance360_connections")
