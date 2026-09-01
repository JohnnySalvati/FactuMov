import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from factumov.logging_config import configure_logging
from factumov.routers import (
    auth,
    balance360,
    customer,
    fiscal_identity,
    health,
    invoice,
    invoice_template,
    subscription,
)
from factumov.services import delegation_watch, email

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

    **Lo primero que hace es configurar el logging**, antes de loguear nada. Hasta que no
    corre `configure_logging` el único handler que existe es `logging.lastResort`, que imprime
    de WARNING para arriba: el ERROR de abajo se vería igual, pero el INFO del caso normal no,
    y tampoco los del barrido de delegaciones. Ver `logging_config.py`.

    Va acá y no en el import del módulo porque tocar la config global de `logging` al importar
    le impondría los handlers de la app a cualquiera que importe `main` —los tests, sin ir más
    lejos, que arman su propio `TestClient` sin levantar el lifespan—. El lifespan es
    exactamente el momento en que esto empieza a ser un proceso servidor y no un módulo.
    """
    configure_logging()

    problem = email.config_problem()
    if problem is None:
        logger.info("Config de mail leída correctamente.")
    else:
        logger.error(
            "El envío de mails NO va a funcionar: %s. Sin esto no se puede registrar una "
            "cuenta ni restablecer una contraseña; revisá las variables SMTP_* del .env.",
            problem,
        )

    task = asyncio.create_task(_recheck_delegations_forever())
    try:
        yield
    finally:
        task.cancel()
        # Esperar la cancelación y no soltarla: sin esto el barrido puede quedar a mitad de una
        # llamada a ARCA cuando el proceso se está bajando, y el `finally` de la sesión no
        # corre. `CancelledError` es el resultado esperado, no un fallo.
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _recheck_delegations_forever() -> None:
    """Vuelve a preguntarle a ARCA, cada tanto, por las delegaciones que esperan aceptación.

    Vive en el `lifespan` y no en un cron o en un worker aparte. La alternativa era un comando
    suelto colgado del Task Scheduler o de un cron, que es más prolijo en producción y en
    desarrollo simplemente no corre — o sea que el circuito que esto cierra no se podría probar
    donde se lo prueba todo. Con N workers barre uno solo: el `pg_try_advisory_xact_lock` de
    `recheck_pending` se encarga, que es el mismo mecanismo que ya usan el ticket de ARCA y la
    numeración de comprobantes.

    **Duerme antes de la primera vuelta.** Arrancar barriendo alargaría el arranque con una
    llamada a ARCA que nadie pidió, y sobre todo convertiría un proceso que crashea y se
    reinicia en un martillo contra ARCA.

    **Se traga cualquier excepción.** Es un bucle infinito de fondo: si una vuelta se rompe, lo
    que corresponde es que la siguiente lo intente de nuevo, no que el barrido muera en silencio
    y nadie se entere hasta que un usuario pregunte por qué nunca le llegó el aviso.

    `to_thread` porque `recheck_pending` es sincrónico de punta a punta —SQLAlchemy sync y zeep
    sobre requests—, y correrlo derecho acá bloquearía el event loop durante toda la
    conversación con ARCA.
    """
    while True:
        await asyncio.sleep(delegation_watch.RECHECK_INTERVAL_SECONDS)
        try:
            verified = await asyncio.to_thread(delegation_watch.recheck_pending)
        except Exception:
            logger.exception("Falló el rechequeo de delegaciones pendientes.")
        else:
            if verified:
                logger.info("Quedaron verificadas %d delegaciones pendientes.", verified)


app = FastAPI(title="FactuMov", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(balance360.router)
app.include_router(customer.router)
app.include_router(health.router)
app.include_router(fiscal_identity.router)
# El segundo router de ese módulo, y el único de la app sin sesión además de `auth`: es donde
# aterriza el link que el mail le manda al operador. Ver `confirm_delegation_accepted`.
app.include_router(fiscal_identity.delegation_router)
app.include_router(invoice.router)
app.include_router(invoice_template.router)
app.include_router(subscription.router)
# El segundo router de suscripción, y el tercero de la app sin sesión: lo llama Mercado Pago
# desde sus servidores, que no tienen ninguna cookie de acá. Su autenticación es la firma
# `x-signature` — ver `mercado_pago_webhook`.
app.include_router(subscription.webhook_router)
