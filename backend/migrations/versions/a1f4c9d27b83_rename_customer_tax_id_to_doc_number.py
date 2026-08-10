"""rename customer tax_id to doc_number and add partial unique index

Revision ID: a1f4c9d27b83
Revises: 40c6538fece7
Create Date: 2026-08-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f4c9d27b83'
down_revision: Union[str, Sequence[str], None] = '40c6538fece7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Rename, not drop+add: ALTER ... RENAME COLUMN preserves the existing data.
    op.alter_column('customers', 'tax_id', new_column_name='doc_number')

    # Partial: FINAL is ARCA's "sin identificar", so those rows are allowed to
    # repeat. A UniqueConstraint cannot carry a WHERE clause; only an index can.
    op.create_index(
        'uq_customers_doc_type_doc_number',
        'customers',
        ['doc_type', 'doc_number'],
        unique=True,
        postgresql_where=sa.text("doc_type <> 'FINAL'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_customers_doc_type_doc_number', table_name='customers')
    op.alter_column('customers', 'doc_number', new_column_name='tax_id')
