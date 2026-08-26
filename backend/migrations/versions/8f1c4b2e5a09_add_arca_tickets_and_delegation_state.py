"""add arca_tickets and fiscal identity delegation state

Revision ID: 8f1c4b2e5a09
Revises: 10a07c64dfce
Create Date: 2026-08-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f1c4b2e5a09'
down_revision: Union[str, Sequence[str], None] = '10a07c64dfce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    `arca_tickets` replaces the ticket_arca.json file Balance360 keeps in its working
    directory. The file cannot coordinate what FactuMov needs coordinated: one shared
    certificate, N workers, and a WSAA that refuses to issue a new access ticket while
    the previous one is still valid. Two workers asking at once do not get two tickets,
    they get one ticket and an error. A row plus an advisory lock serialises that; a
    file in a container's cwd does not, and does not survive the container either.

    The table carries no user_id on purpose: the ticket belongs to the certificate, not
    to the taxpayer. Whom it acts for is decided per call, in WSFE's Auth.Cuit — and
    that gap between the certificate's CUIT and the represented CUIT is exactly what the
    delegation grants. It is the only table in the schema that is not owned by a user.

    `env` is part of the unique key because homologación and producción have different
    certificates and therefore different tickets; without it, switching environments
    would reuse a ticket the other side does not recognise.

    token and sign are Text rather than String(n): they are base64 blobs of undocumented
    length (~3 KB today) and ARCA promises no ceiling. A short varchar would break in
    production, all at once, on a value nobody controls.

    fiscal_identities.delegation_verified_at is nullable with no backfill: no row has
    ever been verified, because nothing before this migration could ask. It is a
    timestamp and not a boolean for the same reason users.email_confirmed_at is — the
    "when" is what the UI and any support question actually want, and a delegation can
    be revoked on ARCA's side without telling us, so the column records that this was
    true on that date rather than that it is true now.
    """
    op.create_table('arca_tickets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('env', sa.String(length=4), nullable=False),
    sa.Column('service', sa.String(length=50), nullable=False),
    sa.Column('token', sa.Text(), nullable=False),
    sa.Column('sign', sa.Text(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('env', 'service', name='uq_arca_tickets_env_service')
    )
    op.add_column('fiscal_identities', sa.Column('delegation_verified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema.

    Reversible in full, unlike cf79c4f7610c and 2c2b5ddd2d8d: nothing here is a data
    decision. Dropping the tickets only forces the next WSAA login — which will fail
    until the previous ticket expires, up to twelve hours, so do not run this on a live
    deployment to fix something else.
    """
    op.drop_column('fiscal_identities', 'delegation_verified_at')
    op.drop_table('arca_tickets')
