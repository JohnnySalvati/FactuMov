"""require doc_number unless doc_type is FINAL

Revision ID: 070c8508060a
Revises: ca13b855923c
Create Date: 2026-08-16 22:18:19.769642

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '070c8508060a'
down_revision: Union[str, Sequence[str], None] = 'ca13b855923c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # CustomerCreate already refuses a non-FINAL customer without a document, but
    # CustomerUpdate is a partial payload: it never sees the stored row, so it
    # cannot tell "leave the existing number alone" from "there is no number".
    # PATCH {"doc_type": "CUIT"} on a consumidor final therefore stranded a
    # customer with a NULL doc_number — invisible to get_by_doc for ever, so every
    # PDF import of that customer created a duplicate instead of finding them.
    #
    # The partial unique index is no help here: Postgres treats NULLs as distinct,
    # so any number of CUIT rows with a NULL document coexist happily.
    #
    # Named, so db_flush can map the violation onto a domain exception the same way
    # it maps uq_customers_doc_type_doc_number.
    op.create_check_constraint(
        'ck_customers_doc_number_required',
        'customers',
        "doc_type = 'FINAL' OR doc_number IS NOT NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_customers_doc_number_required', 'customers', type_='check')
