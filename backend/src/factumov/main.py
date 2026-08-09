from fastapi import FastAPI

from factumov.routers import health

app = FastAPI(title="FactuMov")

app.include_router(health.router)
