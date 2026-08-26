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
npm run dev      # https://localhost:5173
```

El puerto 5173 es fijo (`strictPort`): `APP_BASE_URL` del backend apunta ahí, y de esa
variable cuelga el link de confirmación que sale por mail.

## Probar desde el celular

Vite escucha en todas las interfaces e imprime las URL de LAN al arrancar. Con el teléfono en
la misma red Wi-Fi, abrí la de la interfaz Wi-Fi (algo como `https://192.168.1.37:5173`) y
aceptá la advertencia del certificado — es autofirmado, lo genera el dev server.

**Tiene que ser `https`.** La cookie de sesión es `Secure` y el navegador solo la guarda en un
contexto seguro; `localhost` cuenta como seguro aunque sea http, una IP de LAN no. Por http la
cookie se setea, nunca vuelve, y todo contesta 401.

Para probar además el **registro** desde el teléfono hay que apuntar `APP_BASE_URL` del
backend a esa misma URL de LAN, o el link del mail abre en `localhost` y desde el celular no
resuelve.

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
