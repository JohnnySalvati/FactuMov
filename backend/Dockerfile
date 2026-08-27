# syntax=docker/dockerfile:1
#
# Imagen del backend. El contexto de build es `backend/`, no la raíz del repo: así el
# frontend no invalida esta cache y viceversa. La SPA tiene su propia imagen —ver
# `frontend/Dockerfile`— y es un nginx el que las junta.

# Imagen oficial de uv con Python 3.11 ya adentro.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# UV_COMPILE_BYTECODE: precompila los .pyc, así el arranque no los escribe.
# UV_LINK_MODE=copy: copia los paquetes en vez de symlinkear la cache, que es lo que hace
#   que la imagen sea autocontenida.
# PYTHONUNBUFFERED: los logs salen al instante. Importa más que de costumbre acá: el
#   renglón con el CAE recién otorgado es la red de seguridad de la emisión.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# --- Librerías de sistema para WeasyPrint ---
# Pango es el motor de texto con el que WeasyPrint dibuja el PDF del comprobante, y
# `fonts-dejavu-core` está porque `templates/invoice.html` pide "DejaVu Sans" por nombre:
# sin la fuente el PDF sale igual, con la sustituta que elija fontconfig y las columnas
# corridas. Va antes de las dependencias para que la capa quede cacheada.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# --- Capa 1: dependencias ---
# Solo los archivos de bloqueo. Mientras no cambien, Docker reutiliza esta capa y el
# build de un cambio de código no reinstala nada.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# --- Capa 2: el proyecto ---
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# El venv que arma uv queda en /app/.venv; con esto se invocan `alembic` y `uvicorn`
# directamente, sin `uv run`.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Forma JSON: el proceso 1 es `sh`, que después hace `exec uvicorn` y le cede su lugar.
# Sin eso uvicorn no recibiría el SIGTERM del deploy y cada redeploy sería un kill -9.
CMD ["sh", "docker-entrypoint.sh"]
