"""add fiscal_identities.delegation_claimed_at

Revision ID: c8a1e4f60b92
Revises: b2d5f80c3e17
Create Date: 2026-08-27 19:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8a1e4f60b92'
down_revision: Union[str, Sequence[str], None] = 'b2d5f80c3e17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    When the user told us they had already granted the delegation in ARCA, with ARCA not yet
    confirming it. NULL means they never did.

    Granting the delegation has two halves and the second one is ours: the taxpayer designates
    FactuMov as their representative, and FactuMov then has to accept that designation by hand,
    with Clave Fiscal, in adminrel/pending.aspx. Until that happens WSFE answers code 600 --
    exactly what it answers when nobody delegated anything. The column exists because it is the
    only thing that tells those two states apart, and it cannot come from ARCA: ARCA does not
    publish pending designations over any web service. It comes from the user, who is the only
    one who knows whether they did their half.

    Nullable with no backfill: rows that predate this genuinely never told us anything, so NULL
    is the truth rather than a gap. Same shape and same reasoning as delegation_verified_at
    right next to it.
    """
    op.add_column(
        'fiscal_identities',
        sa.Column('delegation_claimed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops the claims. Nothing derives from them -- the screen falls back to telling everyone to
    go and delegate, which is where it was before.
    """
    op.drop_column('fiscal_identities', 'delegation_claimed_at')
