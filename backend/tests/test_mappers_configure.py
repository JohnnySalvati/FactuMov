from sqlalchemy.orm import configure_mappers

from factumov.models import (
    Customer,
    FiscalIdentity,
    InvoiceTemplate,
    InvoiceTemplateLine,
    User,
    UserSession,
)
from factumov.models.base import Base


def test_mappers_configure() -> None:
    """Every relationship, FK target and back_populates pair resolves."""
    configure_mappers()


def test_all_models_are_registered() -> None:
    """Each model class has its table registered on the shared metadata."""
    for model in (
        Customer,
        FiscalIdentity,
        InvoiceTemplate,
        InvoiceTemplateLine,
        UserSession,
        User,
    ):
        assert model.__tablename__ in Base.metadata.tables
