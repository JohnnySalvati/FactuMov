"""add arca_tickets.issued_at

Revision ID: e5c2a9f3d418
Revises: d4b8e2a71c56
Create Date: 2026-08-29 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5c2a9f3d418"
down_revision: Union[str, Sequence[str], None] = "d4b8e2a71c56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cuándo emitió WSAA este ticket de acceso.

    La tabla ya decía hasta cuándo vale el ticket, pero no de cuándo es. Son dos cosas
    distintas y hacía falta la segunda: un TA lleva adentro la lista de relaciones tal como
    estaba **en el momento de emitirse**, así que uno emitido antes de que un contribuyente
    nos delegara sigue contestando "no está delegado" durante las doce horas que le quedan de
    vigencia. Sin esta columna no hay forma de preguntar "¿este ticket es viejo?", que es lo
    único que separa un "no" verdadero de uno que ya no lo es.

    El backfill sale de `updated_at` y no de `now()`: el único UPDATE que esa fila recibe es
    justamente la renovación del ticket, así que para las filas que hoy existen `updated_at`
    ya es, exactamente, el momento en que WSAA lo emitió. `now()` las marcaría como recién
    emitidas y se perdería la primera renovación de cada entorno.
    """
    op.add_column(
        "arca_tickets",
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute("UPDATE arca_tickets SET issued_at = updated_at")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("arca_tickets", "issued_at")
