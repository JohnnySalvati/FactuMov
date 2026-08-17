from uuid import UUID

from factumov.enums import Concepto, IvaAliquot
from factumov.schemas.invoice_template_draft import (
    CustomerDraft,
    InvoiceTemplateDraft,
    InvoiceTemplateLineDraft,
)
from factumov.services.invoice_parser import ParsedInvoice


def build_draft(
    parsed_invoice: ParsedInvoice,
    customer_id: UUID | None = None,
    fiscal_identity_id: UUID | None = None,
) -> InvoiceTemplateDraft:

    customer = CustomerDraft(
        name=parsed_invoice.customer_name,
        condicion_iva=parsed_invoice.customer_condicion_iva,
        doc_type=parsed_invoice.customer_doc_type,
        doc_number=parsed_invoice.customer_doc_number,
        address=parsed_invoice.customer_address,
    )
    lines = [
        InvoiceTemplateLineDraft(
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            iva_aliquot=IvaAliquot.get_by_rate(line.iva_rate),
        )
        for line in parsed_invoice.lines
    ]
    invoice_template_draft = InvoiceTemplateDraft(
        fiscal_identity_id=fiscal_identity_id,
        issuer_tax_id=parsed_invoice.issuer_cuit,
        customer_id=customer_id,
        customer=customer,
        voucher_type=parsed_invoice.voucher_type,
        pos=parsed_invoice.pos,
        concepto=Concepto.products if parsed_invoice.from_date is None else Concepto.services,
        lines=lines,
    )
    return invoice_template_draft
