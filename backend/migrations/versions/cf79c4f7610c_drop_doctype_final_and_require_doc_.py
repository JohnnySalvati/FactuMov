"""drop DocType FINAL and require doc_number

Revision ID: cf79c4f7610c
Revises: 070c8508060a
Create Date: 2026-08-18 15:12:49.033837

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf79c4f7610c'
down_revision: Union[str, Sequence[str], None] = '070c8508060a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    FactuMov issues repeat invoices to habitual customers, and an unidentified buyer
    has no template to reuse, so DocType.FINAL — ARCA's "sin identificar", code 99 —
    leaves the domain. Everything that existed only to accommodate it goes with it:
    the partial unique index, the check constraint, and the nullable doc_number.

    Note this does NOT stop invoicing a consumidor final. That is CondicionIva.FINAL,
    a different enum on a different column, and it is untouched. What is dropped is
    only the ability to store a customer who supplied no document at all.
    """
    # Refuse to run rather than destroy data. Any surviving FINAL customer, or any
    # row stranded with a NULL document, has to be resolved by hand first: the cast
    # below would fail anyway, but it would fail after the constraints are already
    # gone, leaving the schema half migrated.
    blocking = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM customers "
                "WHERE doc_type = 'FINAL' OR doc_number IS NULL"
            )
        )
        .scalar_one()
    )
    if blocking:
        raise RuntimeError(
            f"{blocking} customer(s) are FINAL or have no doc_number. "
            "Give each one a doc_type and doc_number, then re-run this migration."
        )

    # Both of these mention 'FINAL' as a doctype literal, so they have to go before
    # the type is rebuilt — otherwise the USING cast trips over its own predicate.
    op.drop_constraint("ck_customers_doc_number_required", "customers", type_="check")
    op.drop_index("uq_customers_doc_type_doc_number", table_name="customers")

    op.alter_column(
        "customers", "doc_number", existing_type=sa.String(length=11), nullable=False
    )

    # Postgres can add a label to an enum but never remove one, so the type is
    # rebuilt: rename the old one aside, create the real one, cast the column
    # through text, drop the leftover. `customers.doc_type` is the only column
    # using doctype, which is what makes a single cast enough.
    op.execute("ALTER TYPE doctype RENAME TO doctype_obsolete")
    sa.Enum("CUIT", "CUIL", "DNI", name="doctype").create(op.get_bind())
    op.execute(
        "ALTER TABLE customers ALTER COLUMN doc_type TYPE doctype "
        "USING doc_type::text::doctype"
    )
    op.execute("DROP TYPE doctype_obsolete")

    # A plain constraint now that no row is exempt, which is also what the model
    # declares. The partial index existed only to let FINAL rows repeat.
    op.create_unique_constraint(
        "uq_customers_doc_type_doc_number", "customers", ["doc_type", "doc_number"]
    )


def downgrade() -> None:
    """Downgrade schema.

    Reversible, but not free: it restores the shape, not the data. Customers that
    were FINAL before the upgrade were given a real document to get through it, and
    nothing here can tell those apart from customers who always had one.
    """
    op.drop_constraint("uq_customers_doc_type_doc_number", "customers", type_="unique")

    # Same rebuild in reverse. ALTER TYPE ... ADD VALUE would be shorter, but it
    # cannot be used later in the same transaction that adds it, and Alembic runs
    # the whole migration in one.
    op.execute("ALTER TYPE doctype RENAME TO doctype_obsolete")
    sa.Enum("CUIT", "CUIL", "DNI", "FINAL", name="doctype").create(op.get_bind())
    op.execute(
        "ALTER TABLE customers ALTER COLUMN doc_type TYPE doctype "
        "USING doc_type::text::doctype"
    )
    op.execute("DROP TYPE doctype_obsolete")

    op.alter_column(
        "customers", "doc_number", existing_type=sa.String(length=11), nullable=True
    )

    op.create_index(
        "uq_customers_doc_type_doc_number",
        "customers",
        ["doc_type", "doc_number"],
        unique=True,
        postgresql_where=sa.text("doc_type <> 'FINAL'"),
    )
    op.create_check_constraint(
        "ck_customers_doc_number_required",
        "customers",
        "doc_type = 'FINAL' OR doc_number IS NOT NULL",
    )
