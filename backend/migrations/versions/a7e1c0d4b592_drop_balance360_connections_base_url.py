"""drop balance360_connections.base_url

Revision ID: a7e1c0d4b592
Revises: f3b7d1a95c40
Create Date: 2026-08-29 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7e1c0d4b592"
down_revision: Union[str, Sequence[str], None] = "f3b7d1a95c40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """La dirección de Balance360 pasa a ser config del servidor.

    Era un campo del formulario y una columna por usuario, y las dos cosas estaban mal. Quien
    sabe en qué host corre Balance360 es quien deployó las dos apps, no la persona que aprieta
    "conectar": pedírsela convertía un dato de infraestructura en una pregunta de usuario, y
    tipearla mal daba un error de red donde el usuario esperaba uno de credenciales. Guardada
    por usuario, además, era el mismo valor copiado tantas veces como cuentas conectadas.

    Ahora sale de `BALANCE360_BASE_URL`. Un servidor de FactuMov le habla a un Balance360; el
    día que eso no alcance —dos instalaciones distintas contra la misma app— la columna vuelve,
    y no antes.

    Se borra en vez de dejarla ignorada: una columna que nadie lee pero que sigue teniendo un
    valor es la que dentro de seis meses alguien usa creyendo que está viva.
    """
    op.drop_column("balance360_connections", "base_url")


def downgrade() -> None:
    """Vuelve la columna con la dirección del `.env` adentro.

    El `server_default` no es cosmético: la columna es `NOT NULL` y las filas que existan
    necesitan un valor. Queda el placeholder y no la variable de entorno real porque una
    migración no lee el `.env` del proceso que la corre —el downgrade puede correrlo cualquiera
    desde cualquier lado—; si hay que volver de verdad, se hace un UPDATE con la dirección que
    corresponda.
    """
    op.add_column(
        "balance360_connections",
        sa.Column(
            "base_url",
            sa.String(length=200),
            nullable=False,
            server_default="https://balance360.example",
        ),
    )
    op.alter_column("balance360_connections", "base_url", server_default=None)
