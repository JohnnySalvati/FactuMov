"""add subscriptions

Revision ID: e8a3c5f21d47
Revises: c1d7e9a4b820
Create Date: 2026-08-31

Una fila por usuario con el estado de su plan. La tabla guarda **hechos** —en qué estado está
y hasta cuándo llega lo pagado— y no el plan efectivo, que se deduce leyendo esos hechos contra
la política de `services/subscription.py`. Ver *Monetización*.

El backfill le da a cada cuenta que ya existía los mismos treinta días de prueba que va a
recibir cualquier registro nuevo. Esta migración **sí inventa un dato**, al revés que
`2c2b5ddd2d8d` y `cf79c4f7610c`, que cortan antes de adivinar: la diferencia es que allá el
dato faltante tenía una respuesta correcta que la migración no podía conocer (de quién era una
fila huérfana), y acá no hay ninguna respuesta preexistente que se pueda contradecir. El plan
no existía hasta esta migración, así que no hay nada que deducir mal — hay una decisión de
producto que tomar, y es la misma que se toma con todo el mundo.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e8a3c5f21d47"
down_revision: Union[str, Sequence[str], None] = "c1d7e9a4b820"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Las columnas guardan el **nombre** del miembro, no su valor: es lo que hace `Enum(...)` de
# SQLAlchemy sin `values_callable`, igual que el resto de los enums del proyecto.
_STATUS_LABELS = ("TRIALING", "ACTIVE", "PAST_DUE", "CANCELED")
_INTERVAL_LABELS = ("MONTHLY", "YEARLY")
_PROVIDER_LABELS = ("MERCADO_PAGO", "MANUAL")

# Los mismos treinta días que `services.subscription.TRIAL_DAYS`. Está escrito de nuevo acá, y
# no importado, por la misma razón por la que `3d9a71e0c4b2` repite en SQL la tabla de letras:
# una migración no puede depender del código de la app. El día que el trial pase a 45 días, lo
# que esta migración tiene que seguir haciendo es lo que hizo cuando corrió.
_TRIAL_DAYS = 30


def upgrade() -> None:
    """Upgrade schema."""
    # `create_type=False` y `create()` explícito antes del `create_table`, como en
    # `d4b8e2a71c56`: con la creación implícita, un fallo a mitad de camino deja los tipos
    # dados de alta y el reintento revienta con "type already exists".
    status = postgresql.ENUM(*_STATUS_LABELS, name="subscriptionstatus", create_type=False)
    interval = postgresql.ENUM(*_INTERVAL_LABELS, name="billinginterval", create_type=False)
    provider = postgresql.ENUM(*_PROVIDER_LABELS, name="billingprovider", create_type=False)
    bind = op.get_bind()
    status.create(bind, checkfirst=True)
    interval.create(bind, checkfirst=True)
    provider.create(bind, checkfirst=True)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("billing_interval", interval, nullable=True),
        sa.Column("provider", provider, nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=64), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        # Unique y no índice a secas: "la suscripción del usuario" tiene que ser una sola fila.
        sa.UniqueConstraint("user_id"),
        # Una suscripción del proveedor no puede quedar atada a dos cuentas. Postgres deja
        # repetir el NULL, que es lo que tienen todas las filas mientras están en trial.
        sa.UniqueConstraint("provider_subscription_id"),
    )

    # El trial de las cuentas que ya existían. `gen_random_uuid()` viene con pgcrypto, que en
    # Postgres 13+ está en el core; el resto del proyecto genera los UUID en Python, pero acá
    # no hay Python en el medio — es un INSERT ... SELECT y traer todos los usuarios a la app
    # para volver a mandarlos sería el mismo trabajo con dos viajes más.
    op.execute(
        sa.text(
            """
            INSERT INTO subscriptions (id, user_id, status, current_period_end)
            SELECT gen_random_uuid(), users.id, 'TRIALING',
                   now() + make_interval(days => :trial_days)
            FROM users
            """
        ).bindparams(trial_days=_TRIAL_DAYS)
    )


def downgrade() -> None:
    """Downgrade schema.

    Restituye la forma y no los datos, como el de `b2d5f80c3e17`: los pagos acreditados que
    esta tabla registrara se pierden, y no se pueden re-deducir de ninguna otra. Bajar de esta
    revisión con suscripciones vivas es perder de quién se cobró y hasta cuándo.
    """
    op.drop_table("subscriptions")
    # Los tipos no se van con la tabla: `CREATE TYPE` es una operación de esquema aparte y sin
    # estos drops el downgrade deja la base a medio revertir.
    for type_name in ("subscriptionstatus", "billinginterval", "billingprovider"):
        sa.Enum(name=type_name).drop(op.get_bind(), checkfirst=True)
