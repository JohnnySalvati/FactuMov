from fastapi import FastAPI

from factumov.routers import (
    customer,
    health,
)

app = FastAPI(title="FactuMov")

app.include_router(health.router)
app.include_router(customer.router)
