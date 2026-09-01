"""add invoice_templates.email_subject and email_body

Revision ID: d7f3b0c81a95
Revises: b6f4a2c98d31
Create Date: 2026-09-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d7f3b0c81a95"
down_revision: Union[str, Sequence[str], None] = "b6f4a2c98d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    El asunto y el cuerpo del mail con el que se manda la factura emitida de este modelo.

    **Nullable y sin `server_default`**, al revés que `customers.cc_emails`. Ahí el array vacío
    era la verdad de las filas viejas; acá `NULL` no significa "sin texto" sino "el texto que
    la app viene mandando desde siempre", que es exactamente lo que tienen los modelos que
    existían antes de estas columnas. Un `server_default` con el texto de hoy congelaría en
    cada fila una copia que dejaría de actualizarse el día que se corrija la redacción.

    Dos columnas y no una: el asunto y el cuerpo se personalizan por separado y caen en el
    default por separado.
    """
    op.add_column(
        "invoice_templates", sa.Column("email_subject", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "invoice_templates", sa.Column("email_body", sa.String(length=2000), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema.

    Restituye la forma y no los datos, como `b2d5f80c3e17`: los textos escritos se pierden y
    los modelos vuelven al mail por default, que es el que mandaban antes de esta migración.
    """
    op.drop_column("invoice_templates", "email_body")
    op.drop_column("invoice_templates", "email_subject")
