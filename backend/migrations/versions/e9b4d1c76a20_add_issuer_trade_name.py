"""add fiscal_identities.trade_name and invoices.issuer_trade_name

Revision ID: e9b4d1c76a20
Revises: d7f3b0c81a95
Create Date: 2026-09-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e9b4d1c76a20"
down_revision: Union[str, Sequence[str], None] = "d7f3b0c81a95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    El nombre de fantasía del emisor: cómo se llama el negocio, que no siempre es cómo se
    llama el contribuyente. Sale en el renglón grande de arriba del comprobante, arriba de la
    razón social.

    Dos columnas y no una: `fiscal_identities.trade_name` es la ficha —lo que vale hoy— y
    `invoices.issuer_trade_name` es la copia congelada de lo que salió impreso, igual que el
    resto de los `issuer_*`. Sin la copia, cambiarle el nombre al negocio reescribiría el
    encabezado de todas las facturas ya emitidas.

    Las dos nullable y sin `server_default`: "no tiene nombre de fantasía" es el caso más
    común y es la verdad de todas las filas que existían antes. En las facturas viejas el
    `NULL` hace que el comprobante imprima la razón social en ese renglón, que es lo mismo
    que imprimía antes de esta migración.
    """
    op.add_column(
        "fiscal_identities", sa.Column("trade_name", sa.String(length=150), nullable=True)
    )
    op.add_column(
        "invoices", sa.Column("issuer_trade_name", sa.String(length=150), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("invoices", "issuer_trade_name")
    op.drop_column("fiscal_identities", "trade_name")
