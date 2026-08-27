#!/bin/sh
set -e

# Las migraciones se aplican acá y no a mano: el deploy es un `up -d --build` y nada más.
# Con `set -e`, una migración que falle deja la app sin arrancar en vez de levantarla
# contra un esquema viejo — que es lo que hay que querer, y lo que manda a mirar los logs.
alembic upgrade head

# `exec` reemplaza al shell: uvicorn pasa a ser el proceso principal y recibe el SIGTERM
# directamente, así el apagado de cada deploy es ordenado.
#
# Un solo worker, a propósito. El rate limiter guarda su estado en memoria del proceso, así
# que con N workers el límite efectivo es N veces el configurado (ver CLAUDE.md → *Rate
# limiting*). Con uno, los números del código son los números reales. La carga esperada es
# un puñado de facturas por mes.
#
# --proxy-headers + --forwarded-allow-ips="*": sin esto `request.client` es el nginx de al
# lado y **todos los usuarios comparten un solo cubo** en el rate limiter. El `*` no es un
# descuido: este puerto no se publica en ninguna parte (ver `docker-compose.prod.yml`), así
# que el único que puede hablarle es el `web` del mismo compose, y ese sí reescribe el
# X-Forwarded-For con el cliente real.
exec uvicorn factumov.main:app --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips="*"
