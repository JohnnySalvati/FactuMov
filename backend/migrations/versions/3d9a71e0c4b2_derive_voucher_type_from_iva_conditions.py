"""derive voucher type from iva conditions

Revision ID: 3d9a71e0c4b2
Revises: 8f1c4b2e5a09
Create Date: 2026-08-26 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d9a71e0c4b2'
down_revision: Union[str, Sequence[str], None] = '8f1c4b2e5a09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# La letra deducida de las dos condiciones frente al IVA, en SQL. Es la misma tabla que
# `services/voucher.py`, escrita acá porque una migración no puede depender del código de la
# app: el modelo de mañana no describe el esquema de hoy.
#
# Sin notas de crédito la respuesta es siempre una sola, así que alcanzan tres ramas: solo el
# inscripto puede emitir A o B, y la A solo la recibe otro inscripto; monotributista y exento
# emiten C contra cualquiera.
_LETTER_SQL = """
    CASE
        WHEN fi.condicion_iva = 'INSCRIPTO' AND c.condicion_iva = 'INSCRIPTO' THEN 'A'
        WHEN fi.condicion_iva = 'INSCRIPTO' THEN 'B'
        ELSE 'C'
    END::vouchertype
"""


def upgrade() -> None:
    """La letra del comprobante deja de guardarse: se deduce.

    `voucher_type` era una columna de `invoice_templates` que el usuario elegía de un
    desplegable. No es una elección: es una consecuencia de la condición frente al IVA del
    emisor y de la del receptor, y una vez sacadas las notas de crédito —que FactuMov no
    ofrece, porque nadie emite una NC todos los meses— la combinación determina exactamente
    una letra. Ver `services/voucher.py`.

    Guardada, la columna es una tercera fuente de verdad capaz de contradecir a sus dos
    padres: el día que un cliente pasa de monotributista a inscripto, el modelo guardado
    sigue diciendo B cuando ARCA ya espera A. Deducida, no puede quedar vieja.

    **Se comprueba antes de borrar.** Si alguna fila guardada no coincide con lo que la
    deducción da para sus padres, la migración corta: puede ser una condición frente al IVA
    mal cargada, o una letra elegida a mano a propósito, y las dos merecen una mirada humana
    antes de que el dato desaparezca. Es el mismo criterio de `cf79c4f7610c` y de
    `2c2b5ddd2d8d` — la migración no adivina.

    El tipo `vouchertype` de Postgres **no** se borra: sigue siendo el vocabulario de ARCA y
    vuelve a hacer falta en la tabla `invoices` de la unidad de emisión con CAE.
    """
    bind = op.get_bind()

    mismatched = bind.execute(
        sa.text(
            f"""
            SELECT count(*)
            FROM invoice_templates t
            JOIN fiscal_identities fi ON fi.id = t.fiscal_identity_id
            JOIN customers c ON c.id = t.customer_id
            WHERE t.voucher_type <> {_LETTER_SQL}
            """
        )
    ).scalar_one()
    if mismatched:
        raise RuntimeError(
            f"{mismatched} invoice template(s) have a stored voucher_type that does not "
            "match the letter derived from their issuer's and customer's IVA conditions. "
            "Review those rows — a wrong condicion_iva, or a letter picked by hand — and "
            "then re-run this migration."
        )

    op.drop_column('invoice_templates', 'voucher_type')


def downgrade() -> None:
    """Devuelve la columna, reconstruida.

    Acá el downgrade sí puede ser exacto, al revés que en `cf79c4f7610c`: el valor es una
    función de datos que siguen estando, así que no hay nada que inventar. Se agrega nullable,
    se rellena y recién entonces se pone NOT NULL — una fila existente no puede satisfacer el
    NOT NULL en el instante en que la columna aparece.
    """
    op.add_column(
        'invoice_templates',
        sa.Column(
            'voucher_type',
            sa.Enum('A', 'B', 'C', 'NCA', 'NCB', 'NCC', name='vouchertype'),
            nullable=True,
        ),
    )
    op.execute(
        f"""
        UPDATE invoice_templates t
        SET voucher_type = {_LETTER_SQL}
        FROM fiscal_identities fi, customers c
        WHERE fi.id = t.fiscal_identity_id AND c.id = t.customer_id
        """
    )
    op.alter_column('invoice_templates', 'voucher_type', nullable=False)
