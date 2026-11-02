"""add fiscal_identities.balance360_entity_id

Revision ID: a3c9e7d15b42
Revises: e9b4d1c76a20
Create Date: 2026-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3c9e7d15b42"
down_revision: Union[str, Sequence[str], None] = "e9b4d1c76a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    A qué entidad de Balance360 van los comprobantes del CUIT, cuando allá el CUIT está en más
    de una. Nullable y sin default: `NULL` es "que la deduzca Balance360", que es lo que hacía
    toda fila hasta hoy y lo que sigue siendo correcto para casi todas.

    Sin FK: es un id de la base de Balance360.
    """
    op.add_column(
        "fiscal_identities", sa.Column("balance360_entity_id", sa.Uuid(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("fiscal_identities", "balance360_entity_id")
