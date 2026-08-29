"""add fiscal_identities.delegation_claim_token_hash

Revision ID: f3b7d1a95c40
Revises: e5c2a9f3d418
Create Date: 2026-08-29 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b7d1a95c40'
down_revision: Union[str, Sequence[str], None] = 'e5c2a9f3d418'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    The SHA-256 of the token in the link the operator's email carries, so that whoever accepted
    the designation in ARCA can say so instead of waiting for the 15-minute sweep to find out.

    Column and not a table, unlike email_confirmations: that one is a table because a resend
    issues a new token without invalidating the old one, so several have to be alive at once.
    This mail goes out once per fiscal identity, so there is never more than one link around.

    Nullable and no backfill: a token only exists while a claim is waiting. Identities that
    already claimed before this migration keep working through the sweep and through the screen
    -- they just have no link, which is what they had until now anyway.

    unique for the same reason as in the three token tables: it is also the index the lookup
    uses. Postgres allows repeated NULLs, which is what almost every row has.
    """
    op.add_column(
        'fiscal_identities',
        sa.Column('delegation_claim_token_hash', sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        'uq_fiscal_identities_delegation_claim_token_hash',
        'fiscal_identities',
        ['delegation_claim_token_hash'],
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the links. The claims themselves survive, so the sweep and the screen keep closing
    the wait exactly as they did before the link existed.
    """
    op.drop_constraint(
        'uq_fiscal_identities_delegation_claim_token_hash', 'fiscal_identities', type_='unique'
    )
    op.drop_column('fiscal_identities', 'delegation_claim_token_hash')
