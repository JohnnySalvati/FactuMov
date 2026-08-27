"""rename invoices.customer_email to sent_to

Revision ID: b2d5f80c3e17
Revises: 49023933c5a4
Create Date: 2026-08-27 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b2d5f80c3e17'
down_revision: Union[str, Sequence[str], None] = '49023933c5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    The column stops being a copy of the customer's email taken at emission time and becomes
    the address the last email actually went to — the delivery counterpart of sent_at.

    The copy was a bug, not a design: an invoice emitted while the customer had no email on
    file kept that gap forever. Filling the address in on the customer's card changed nothing,
    and an emitted invoice cannot be edited either, so the invoice was stuck as unsendable.
    The email is not part of what ARCA authorised and never reaches the printed voucher — it
    is only where to deliver the PDF, which is a question about now. So it is read live off
    the customer row, and what stays here is the fact worth freezing: where it was sent.

    Rows that were never sent get NULL. Whatever address they carried was the copy, not a
    delivery, and leaving it would make the column mean two different things depending on the
    row.
    """
    op.alter_column('invoices', 'customer_email', new_column_name='sent_to')
    op.execute("UPDATE invoices SET sent_to = NULL WHERE sent_at IS NULL")


def downgrade() -> None:
    """Downgrade schema.

    Restores the shape, not the data — same caveat as cf79c4f7610c. The addresses cleared
    above are gone, so invoices that were never sent come back with customer_email NULL even
    if their customer had an address on file at emission time. Re-deriving it is not possible:
    the customer's email may have changed since.
    """
    op.alter_column('invoices', 'sent_to', new_column_name='customer_email')
