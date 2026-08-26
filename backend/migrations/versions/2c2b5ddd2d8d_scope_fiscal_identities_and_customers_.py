"""scope fiscal identities and customers to a user

Revision ID: 2c2b5ddd2d8d
Revises: 45cbc9ddbf95
Create Date: 2026-08-26 10:41:02.118374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c2b5ddd2d8d'
down_revision: Union[str, Sequence[str], None] = '45cbc9ddbf95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Ownership scoping: fiscal_identities and customers get an owner, and every unique
    constraint on them narrows from global to per-owner.

    Narrowing the constraints is not cosmetic. Global uniqueness would forbid two users
    from having the same customer, which is an ordinary situation, and it would also let
    a 409 confirm that some other user's row exists — reintroducing through the duplicate
    path exactly the existence oracle that the 404-never-403 rule closes on the read path.

    invoice_templates gets no user_id. It hangs off fiscal_identity_id, which is already
    indexed, so scoping is a join; a denormalised copy would be a third source of truth
    that can disagree with its parents. The CRUD validates that both parents belong to the
    caller on write, which makes a template's ownership derived and consistent by
    construction.

    The column is added nullable, backfilled, and only then made NOT NULL — the usual
    three-step, because an existing row cannot satisfy NOT NULL at the moment it appears.
    """
    bind = op.get_bind()

    # Refuse to invent an owner. On a single-user development database the intent is
    # unambiguous and the backfill is automatic; with zero users there is nobody to
    # attribute the rows to, and with several there is no way to tell which. Failing
    # here costs a manual UPDATE; guessing wrong hands one user another user's data.
    orphans = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM fiscal_identities) "
            "     + (SELECT count(*) FROM customers)"
        )
    ).scalar_one()
    if orphans:
        users = bind.execute(sa.text("SELECT count(*) FROM users")).scalar_one()
        if users != 1:
            raise RuntimeError(
                f"{orphans} fiscal identity/customer row(s) have no owner and there "
                f"are {users} users, so the owner cannot be inferred. Add a user_id "
                "column by hand, assign each row, then re-run this migration."
            )

    op.add_column("fiscal_identities", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("customers", sa.Column("user_id", sa.Uuid(), nullable=True))

    if orphans:
        op.execute("UPDATE fiscal_identities SET user_id = (SELECT id FROM users)")
        op.execute("UPDATE customers SET user_id = (SELECT id FROM users)")

    op.alter_column("fiscal_identities", "user_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("customers", "user_id", existing_type=sa.Uuid(), nullable=False)

    op.create_index(
        op.f("ix_fiscal_identities_user_id"), "fiscal_identities", ["user_id"], unique=False
    )
    op.create_index(op.f("ix_customers_user_id"), "customers", ["user_id"], unique=False)

    # No ondelete: the default NO ACTION makes deleting a user who still owns data fail.
    # That is the right behaviour while there is no account-deletion endpoint — the unit
    # that adds one is the unit that gets to choose between cascade and anonymise.
    op.create_foreign_key(
        "fiscal_identities_user_id_fkey", "fiscal_identities", "users", ["user_id"], ["id"]
    )
    op.create_foreign_key("customers_user_id_fkey", "customers", "users", ["user_id"], ["id"])

    op.drop_constraint("fiscal_identities_name_key", "fiscal_identities", type_="unique")
    op.drop_constraint("fiscal_identities_tax_id_key", "fiscal_identities", type_="unique")
    op.create_unique_constraint(
        "uq_fiscal_identities_user_id_name", "fiscal_identities", ["user_id", "name"]
    )
    op.create_unique_constraint(
        "uq_fiscal_identities_user_id_tax_id", "fiscal_identities", ["user_id", "tax_id"]
    )

    op.drop_constraint("uq_customers_doc_type_doc_number", "customers", type_="unique")
    op.create_unique_constraint(
        "uq_customers_user_id_doc_type_doc_number",
        "customers",
        ["user_id", "doc_type", "doc_number"],
    )


def downgrade() -> None:
    """Downgrade schema.

    Widening the constraints back to global can fail on data the upgraded schema allowed:
    two users owning the same CUIT, or the same customer document. Those rows are legal
    after the upgrade and illegal before it, so the migration refuses rather than picking
    a survivor. Resolve the collisions by hand first.

    Even when it does run it restores the shape, not the information: dropping user_id
    discards who owned what, and nothing here can put it back.
    """
    bind = op.get_bind()

    collisions = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM ("
            "   SELECT 1 FROM fiscal_identities GROUP BY name HAVING count(*) > 1) n) "
            "     + (SELECT count(*) FROM ("
            "   SELECT 1 FROM fiscal_identities GROUP BY tax_id HAVING count(*) > 1) t) "
            "     + (SELECT count(*) FROM ("
            "   SELECT 1 FROM customers GROUP BY doc_type, doc_number HAVING count(*) > 1) c)"
        )
    ).scalar_one()
    if collisions:
        raise RuntimeError(
            f"{collisions} value(s) are shared across users and would violate the global "
            "unique constraints this downgrade restores. Merge or remove the duplicate "
            "fiscal identities/customers by hand, then re-run."
        )

    op.drop_constraint(
        "uq_customers_user_id_doc_type_doc_number", "customers", type_="unique"
    )
    op.create_unique_constraint(
        "uq_customers_doc_type_doc_number", "customers", ["doc_type", "doc_number"]
    )

    op.drop_constraint(
        "uq_fiscal_identities_user_id_tax_id", "fiscal_identities", type_="unique"
    )
    op.drop_constraint("uq_fiscal_identities_user_id_name", "fiscal_identities", type_="unique")
    op.create_unique_constraint(
        "fiscal_identities_tax_id_key", "fiscal_identities", ["tax_id"]
    )
    op.create_unique_constraint("fiscal_identities_name_key", "fiscal_identities", ["name"])

    op.drop_constraint("customers_user_id_fkey", "customers", type_="foreignkey")
    op.drop_constraint(
        "fiscal_identities_user_id_fkey", "fiscal_identities", type_="foreignkey"
    )
    op.drop_index(op.f("ix_customers_user_id"), table_name="customers")
    op.drop_index(op.f("ix_fiscal_identities_user_id"), table_name="fiscal_identities")
    op.drop_column("customers", "user_id")
    op.drop_column("fiscal_identities", "user_id")
