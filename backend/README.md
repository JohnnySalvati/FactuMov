# FactuMov — Backend

API en FastAPI para la app de facturación. Habla solo JSON; el frontend React vive en
`../frontend/`.

## Requisitos
- Python 3.11 (fijado en `.python-version`)
- [uv](https://docs.astral.sh/uv/)
- Docker, para Postgres

## Puesta en marcha

```bash
uv python pin 3.11
uv sync --extra dev
cp .env.example .env
```

Levantar Postgres (desde la raíz del repo). Escucha en el puerto **5433** para no chocar
con el 5432 que ya usa Balance360:

```bash
docker compose up -d
```

Levantar la API en modo desarrollo:

```bash
uv run fastapi dev src/factumov/main.py
```

- API: http://127.0.0.1:8000
- Docs interactivas: http://127.0.0.1:8000/docs

## Herramientas

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```
