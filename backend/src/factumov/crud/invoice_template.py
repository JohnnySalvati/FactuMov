"""Acceso a datos de `invoice_templates`, scopeado por join.

La tabla no tiene `user_id` propio: cuelga de `fiscal_identity_id`, que ya está indexado, y
el scoping sale de un join contra `fiscal_identities`. Denormalizar la columna acortaría
las queries a cambio de una tercera fuente de verdad capaz de contradecir a sus padres —un
modelo cuyo `user_id` dice A y cuya identidad fiscal es de B— y no ahorraría ninguna
validación: chequear que los dos padres son del usuario hace falta igual en la escritura,
porque sin eso A crea un modelo apuntando al cliente de B.

Con esa validación en su lugar, alcanza con joinear una sola de las dos relaciones: ambas
apuntan siempre al mismo dueño, así que las dos dan la misma respuesta.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from factumov.crud import customer as customer_crud
from factumov.crud import fiscal_identity as fiscal_identity_crud
from factumov.crud.base import db_flush
from factumov.exceptions import (
    DuplicateInvoiceTemplateNameError,
    UnknownCustomerError,
    UnknownFiscalIdentityError,
)
from factumov.models.fiscal_identity import FiscalIdentity
from factumov.models.invoice_template import InvoiceTemplate
from factumov.models.invoice_template_line import InvoiceTemplateLine
from factumov.schemas.invoice_template import InvoiceTemplateCreate, InvoiceTemplateUpdate
from factumov.schemas.invoice_template_line import InvoiceTemplateLineCreate

exception_map = {
    "uq_invoice_templates_fiscal_identity_id_name": DuplicateInvoiceTemplateNameError,
    "invoice_templates_customer_id_fkey": UnknownCustomerError,
    "invoice_templates_fiscal_identity_id_fkey": UnknownFiscalIdentityError,
}


def build_invoice_template_lines(
    lines: list[InvoiceTemplateLineCreate],
) -> list[InvoiceTemplateLine]:
    return [
        InvoiceTemplateLine(**line.model_dump(), position=position)
        for position, line in enumerate(lines)
    ]


def _check_parents_owned(
    db: Session,
    user_id: uuid.UUID,
    fiscal_identity_id: uuid.UUID | None,
    customer_id: uuid.UUID | None,
) -> None:
    """Verifica que los padres referenciados sean del usuario.

    `None` significa "este padre no se está tocando" (un PATCH que no lo trae), no "no hay
    padre": en create los dos son obligatorios y llegan siempre.

    Un id de otro usuario levanta la misma excepción que un id inexistente, así que el
    router responde el mismo 422 en los dos casos. Distinguirlos —un 403, o un mensaje
    propio— confirmaría que esa fila existe, que es justo lo que el 404 de las lecturas
    evita. El `exception_map` de abajo sigue mapeando las violaciones de FK: acá se
    adelanta el chequeo, pero la base sigue siendo la que garantiza el invariante si dos
    requests corren a la vez.
    """
    if fiscal_identity_id is not None:
        if fiscal_identity_crud.get_by_id(db, fiscal_identity_id, user_id) is None:
            raise UnknownFiscalIdentityError(str(fiscal_identity_id))
    if customer_id is not None:
        if customer_crud.get_by_id(db, customer_id, user_id) is None:
            raise UnknownCustomerError(str(customer_id))


def get_all(db: Session, user_id: uuid.UUID) -> list[InvoiceTemplate]:
    invoice_templates = (
        db.execute(
            select(InvoiceTemplate)
            .join(InvoiceTemplate.fiscal_identity)
            .where(FiscalIdentity.user_id == user_id)
            # Los dos padres vienen con el modelo porque `InvoiceTemplate.voucher_type` los
            # lee para deducir la letra. Sin esto, listar N modelos son 2N queries más.
            .options(
                selectinload(InvoiceTemplate.lines),
                joinedload(InvoiceTemplate.fiscal_identity),
                joinedload(InvoiceTemplate.customer),
            )
        )
        .scalars()
        .all()
    )
    return list(invoice_templates)


def get_by_id(
    db: Session, invoice_template_id: uuid.UUID, user_id: uuid.UUID
) -> InvoiceTemplate | None:
    return (
        db.execute(
            select(InvoiceTemplate)
            .join(InvoiceTemplate.fiscal_identity)
            .where(
                InvoiceTemplate.id == invoice_template_id,
                FiscalIdentity.user_id == user_id,
            )
            .options(
                joinedload(InvoiceTemplate.fiscal_identity),
                joinedload(InvoiceTemplate.customer),
            )
        )
        .scalars()
        .first()
    )


def create(db: Session, data: InvoiceTemplateCreate, user_id: uuid.UUID) -> InvoiceTemplate:
    _check_parents_owned(db, user_id, data.fiscal_identity_id, data.customer_id)
    invoice_template = InvoiceTemplate(**data.model_dump(exclude={"lines"}))
    db.add(invoice_template)
    invoice_template.lines = build_invoice_template_lines(data.lines)
    db_flush(db, exception_map)
    return invoice_template


def update(
    db: Session,
    invoice_template: InvoiceTemplate,
    data: InvoiceTemplateUpdate,
    user_id: uuid.UUID,
) -> InvoiceTemplate:
    # Solo se validan los padres que el PATCH trae: `exclude_unset` distingue "no lo
    # mandó" de "lo mandó en null", y los campos que no vienen quedan como estaban, ya
    # validados en su momento.
    patch = data.model_dump(exclude_unset=True, exclude={"lines"})
    _check_parents_owned(db, user_id, patch.get("fiscal_identity_id"), patch.get("customer_id"))
    for field, value in patch.items():
        setattr(invoice_template, field, value)
    if data.lines is not None:
        invoice_template.lines = build_invoice_template_lines(data.lines)
    db_flush(db, exception_map)
    return invoice_template


def delete(db: Session, invoice_template: InvoiceTemplate) -> None:
    db.delete(invoice_template)
    db_flush(db, exception_map)
