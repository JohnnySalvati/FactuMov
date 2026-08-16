from fastapi import FastAPI

from factumov.routers import (
    customer,
    fiscal_identity,
    health,
    invoice_template,
)

app = FastAPI(title="FactuMov")

app.include_router(customer.router)
app.include_router(health.router)
app.include_router(fiscal_identity.router)
app.include_router(invoice_template.router)
