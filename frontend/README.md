# FactuMov — frontend

SPA en Vite + React + TypeScript. Las decisiones de diseño están en la sección *Frontend* de
`../CLAUDE.md`, no acá: este archivo es solo cómo se corre.

## Correrlo

Necesita el backend levantado, porque el dev server le hace de proxy:

```bash
# terminal 1 — backend
cd ../backend
uv run uvicorn factumov.main:app --reload --port 8000

# terminal 2 — frontend
npm install      # la primera vez
npm run dev      # http://localhost:5173
```

El puerto 5173 es fijo (`strictPort`): `APP_BASE_URL` del backend apunta ahí, y de esa
variable cuelga el link de confirmación que sale por mail.

## Comandos

| Comando | Qué hace |
|---|---|
| `npm run dev` | Dev server con Fast Refresh |
| `npm run build` | `tsc -b` y bundle de producción en `dist/` |
| `npm run lint` | oxlint |
| `npm run preview` | Sirve el `dist/` ya buildeado |

## Cómo le pega al backend

Todo va a rutas relativas bajo `/api`, que el dev server reenvía a `127.0.0.1:8000`
sacándole el prefijo. **No hay ninguna variable de entorno con la URL del backend**, y no
hace falta CORS: el navegador ve un solo origen. En producción la SPA y la API van detrás del
mismo nginx, que es lo que el proxy imita.

La sesión es una cookie `httpOnly` que el navegador maneja solo — no hay token que guardar ni
nada en `localStorage`.
