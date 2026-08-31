"""add customers.cc_emails

Revision ID: c1d7e9a4b820
Revises: a7e1c0d4b592
Create Date: 2026-08-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d7e9a4b820"
down_revision: Union[str, Sequence[str], None] = "a7e1c0d4b592"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Direcciones que reciben una copia (CC) cuando se le manda una factura al cliente. `email`
    sigue siendo el destinatario principal; esto es solo el CC.

    Un array de Postgres y no una tabla: es una lista corta que se edita entera desde la ficha
    del cliente y nadie la consulta al revés. NOT NULL con `server_default` en `{}` — las
    filas que existían antes de la columna genuinamente no tenían CC, así que el array vacío
    es la verdad y no un hueco.
    """
    op.add_column(
        "customers",
        sa.Column(
            "cc_emails",
            sa.ARRAY(sa.String(length=254)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("customers", "cc_emails")
