import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from factumov.routers import (
    auth,
    customer,
    fiscal_identity,
    health,
    invoice,
    invoice_template,
)
from factumov.services import email

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Avisa al arrancar si el mail no va a poder salir.

    Loguea y **no** aborta el arranque, y eso es una decisión y no una tibieza. El mail hace
    falta en el registro, en el reenvío y en el reset de contraseña; todo lo demás —emitir,
    editar modelos, consultar el padrón— anda perfectamente sin él. Tirar abajo la app
    entera por una variable que solo esos tres endpoints miran es el mismo error que
    `EmailSettings` evita al no instanciarse en el import del módulo.

    Lo que sí cambia es *cuándo* se entera alguien. Antes el primer síntoma era un usuario
    real que no recibía su mail; ahora es un renglón en la consola en el momento en que se
    levanta el server, que es cuando el `.env` está a mano. Los endpoints que dependen del
    mail contestan igual 503 en vez de un 202 mentiroso — ver `routers/auth.py`.

    El logger no tiene handler propio: uvicorn configura los suyos y no toca el root, así que
    esto sale por `logging.lastResort`, que imprime a stderr de WARNING para arriba. Alcanza
    justo para lo que hace falta acá, que es que se vea en la terminal.
    """
    problem = email.config_problem()
    if problem is None:
        logger.info("Config de mail leída correctamente.")
    else:
        logger.error(
            "El envío de mails NO va a funcionar: %s. Sin esto no se puede registrar una "
            "cuenta ni restablecer una contraseña; revisá las variables SMTP_* del .env.",
            problem,
        )
    yield


app = FastAPI(title="FactuMov", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(customer.router)
app.include_router(health.router)
app.include_router(fiscal_identity.router)
app.include_router(invoice.router)
app.include_router(invoice_template.router)
