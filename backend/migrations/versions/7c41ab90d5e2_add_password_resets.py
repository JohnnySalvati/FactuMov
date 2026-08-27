"""add password_resets

Revision ID: 7c41ab90d5e2
Revises: 3d9a71e0c4b2
Create Date: 2026-08-27 09:12:05.441907

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c41ab90d5e2"
down_revision: Union[str, Sequence[str], None] = "3d9a71e0c4b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Third table with the same shape as user_sessions and email_confirmations: an opaque
    token stored as its SHA-256, an absolute expiry, and a consumption mark rather than a
    deleted row. A table instead of two columns on users, for the same reason as
    email_confirmations: asking twice has to leave both links alive, because the user who
    cannot find the first mail asks for another one.

    No backfill. A reset token is something a user asks for; there is no state before this
    migration that should have one.
    """
    op.create_table(
        "password_resets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_password_resets_user_id"), "password_resets", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema.

    Exact, unlike cf79c4f7610c: nothing outside this table depends on it, and the rows it
    drops are single-use tokens that are worthless once the feature is gone.
    """
    op.drop_index(op.f("ix_password_resets_user_id"), table_name="password_resets")
    op.drop_table("password_resets")
