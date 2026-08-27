import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from factumov.crud import invoice as invoice_crud
from factumov.dependencies import CurrentUserDep, SessionDep, get_current_user
from factumov.models.invoice import Invoice
from factumov.schemas.invoice import InvoiceRead

router = APIRouter(
    prefix="/invoices",
    tags=["invoices"],
    dependencies=[Depends(get_current_user)],
)


def get_invoice_or_404(invoice_id: uuid.UUID, db: SessionDep, user: CurrentUserDep) -> Invoice:
    """404 sobre la factura de otro usuario — ver `routers/customer.py`."""
    invoice = invoice_crud.get_by_id(db, invoice_id, user.id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return invoice


InvoiceDep = Annotated[Invoice, Depends(get_invoice_or_404)]


@router.get("", response_model=list[InvoiceRead])
def list_invoices(db: SessionDep, user: CurrentUserDep) -> list[Invoice]:
    return invoice_crud.get_all(db, user.id)


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice: InvoiceDep) -> Invoice:
    return invoice


# No hay PATCH ni DELETE, y la ausencia es la decisión: una factura emitida no se corrige ni
# se borra. Lo que la deja sin efecto es una nota de crédito, que FactuMov no emite y que
# tampoco sería una edición de esta fila. Ver `crud/invoice.py`.
