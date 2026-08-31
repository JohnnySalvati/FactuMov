# Proyecto: FactuMov — App de Facturación

App de facturación independiente de Balance360 pero reutilizando su lógica de backend ya
probada, para Android, iOS y Desktop. **El celular es el caso principal.** Las cinco
funcionalidades core están hechas y el circuito cierra de punta a punta: importar un PDF,
editar el modelo, guardarlo, emitir con CAE y mandarlo por email.

El detalle del objetivo, las funcionalidades y lo que falta está en
[`docs/producto.md`](docs/producto.md).

## Cómo está organizada la documentación
**Este archivo es el que se carga en toda sesión**: contiene las reglas de trabajo, el stack y
las convenciones — o sea lo que aplica sin importar qué se esté tocando. **El porqué de cada
decisión vive en `docs/`**, un archivo por área, y se lee cuando se va a tocar esa área.

Antes eran 2354 líneas en un solo archivo. La división no cambió una palabra del contenido: lo
que cambió es que ahora se puede encontrar.

| Antes de tocar… | Leer |
|---|---|
| Objetivo, alcance, qué falta | [`docs/producto.md`](docs/producto.md) |
| Levantar el entorno, probar desde el celular | [`docs/desarrollo.md`](docs/desarrollo.md) |
| Tablas, schemas, migraciones, la letra del comprobante | [`docs/modelo-de-datos.md`](docs/modelo-de-datos.md) |
| `invoice_parser.py`, el draft, `POST /invoice-templates/import` | [`docs/parser-e-importacion.md`](docs/parser-e-importacion.md) |
| Login, sesiones, registro, mails, rate limiting | [`docs/autenticacion.md`](docs/autenticacion.md) |
| WSAA, padrón, delegación, `arca_tickets` | [`docs/arca.md`](docs/arca.md) |
| Pedir el CAE, los importes, el PDF, mandarlo | [`docs/emision-y-envio.md`](docs/emision-y-envio.md) |
| La SPA: pantallas, gestos, CSS | [`docs/frontend.md`](docs/frontend.md) |
| Conectar con Balance360 y registrar lo emitido | [`docs/balance360.md`](docs/balance360.md) |
| Scoping por usuario y convenciones de test | [`docs/ownership-y-tests.md`](docs/ownership-y-tests.md) |
| Planes, límites del Free, el trial y el cobro | [`docs/monetizacion.md`](docs/monetizacion.md) |
| Ícono, paleta, la landing de InSoft | [`docs/marca.md`](docs/marca.md) |
| Las decisiones del deploy | [`docs/produccion.md`](docs/produccion.md) |
| **Cómo se deploya, paso a paso** | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |

[`docs/README.md`](docs/README.md) es el mismo mapa con una línea de qué hay en cada archivo.

**Las referencias cruzadas del estilo "ver *Sesiones*" apuntan a una sección**, que puede estar
en otro archivo de `docs/`; el índice de arriba dice en cuál.

## Cómo trabajamos en este proyecto
El proyecto arrancó como ejercicio de aprendizaje (Miguel venía de saber algo de Python sin
haber hecho un proyecto completo) con la dinámica de Balance360. Desde el 2026-08-26 ya no:

**Regla fundamental (desde 2026-08-26) — Claude escribe todo el código.** Python incluido:
routers, schemas, CRUD, modelos, servicios, tests, migraciones y frontend.

Reemplaza al régimen anterior, en el que Miguel escribía el Python y Claude solo explicaba.
Ese modo se cerró el 2026-08-26 por decisión de Miguel: el proyecto pasa de ejercicio de
aprendizaje a producto, y el cuello de botella dejó de ser aprender FastAPI.

Lo que **no** cambia es la explicación. Claude tiene que ir contando qué hace y por qué a
medida que escribe: la decisión de diseño, la alternativa que descartó y el motivo. La
diferencia con el régimen anterior es quién teclea, no cuánto se entiende de lo que queda
escrito. Las decisiones no obvias siguen bajando a este archivo.

Cuando algo no está claro, preguntar antes de asumir.

## Cortes de sesión y commits
Claude tiene que **avisar por iniciativa propia** cuándo conviene cortar el chat y empezar
uno nuevo. El criterio no es solo el largo de la conversación: el buen momento es cuando
coincide con un punto de commit, o sea cuando hay una unidad de trabajo terminada y
verificada (tests y linters en verde). Cortar en el medio de algo a medio hacer obliga a
reconstruir contexto en la sesión siguiente y sale más caro que seguir.

**Siempre que se sugiera un commit, dar el mensaje de commit escrito**, listo para copiar.
Mensajes en inglés, imperativo, una línea de resumen y —si hace falta— un cuerpo que
explique el *por qué*, no el *qué* (el diff ya dice qué cambió).

## Working language
- La conversación ocurre en **español**. Hasta el 2026-08-26 era en inglés, con una nota
  "Prompt feedback" corrigiendo cada mensaje; las dos cosas se dieron de baja junto con el
  modo de aprendizaje. **No corregir el inglés de Miguel.**
- Los **identificadores de código siguen en inglés** — eso no cambió (ver *Convenciones*).
- Los strings de UI de la app siguen en español.
- Los comentarios y docstrings nuevos van en español, que es el idioma en el que se discute
  el proyecto. Los que ya están en inglés se dejan donde están: reescribirlos en masa sería
  un diff enorme sin ningún valor.

## Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 (sync) + Alembic + PostgreSQL. Gestor: `uv`.
- **Auth:** `pwdlib[argon2]` para el hash de contraseñas. Sin JWT ni OAuth2: sesión
  opaca en cookie contra la tabla `user_sessions` (ver *Autenticación*).
- **Frontend:** React SPA/PWA. Lo escribe Claude íntegramente.
- **Python:** ≥3.11, layout `src/factumov/`.
- Si más adelante se necesita presencia en las stores: envolver la misma SPA con
  Capacitor (iOS/Android) y Tauri o Electron (Desktop), sin duplicar UI ni backend.

### Por qué React y no HTMX / Flutter / React Native
- **No HTMX** (aunque Balance360 lo use): HTMX depende del servidor en cada interacción,
  lo que deja floja la PWA offline e incómodo el envoltorio con Capacitor. Además Miguel
  nunca escribió esos templates él mismo, así que no hay skill previa que preservar.
- **No Flutter / React Native:** todo el trabajo pesado (parseo del PDF, ARCA, CAE) ocurre
  en el servidor. El cliente solo sube un archivo y muestra un formulario editable. No hay
  necesidad de UI nativa real, así que no se justifica el lock-in a Dart ni el toolchain
  nativo.

## Convenciones (heredadas de Balance360)
- Todos los identificadores de código en **inglés**. Español solo en strings de UI.
- ruff: `line-length = 100`, lint `["E", "F", "I"]`.
- mypy en modo `strict`.
- La entidad central se llama **`InvoiceTemplate`**, no `Model`. "Modelo" es la palabra del
  usuario y vive en la UI; `models/` en el código son las tablas de SQLAlchemy y usar
  `Model` para la entidad produciría choques de nombres constantes.
- El backend habla **solo JSON**. No existe el paquete `web/` de Balance360 (esa era la
  capa HTMX); con una SPA solo hacen falta los `routers/`.
- Postgres de FactuMov escucha en el puerto **5433**, para no chocar con el 5432 que ya usa
  Balance360.

## Estructura del repo
```
FactuMov/
├── CLAUDE.md                       # reglas de trabajo + índice de la documentación
├── docs/                           # el porqué de cada decisión, un archivo por área
│   ├── README.md                   # el mapa
│   ├── DEPLOYMENT.md               # el procedimiento de deploy, paso a paso
│   └── *.md                        # producto, desarrollo, modelo-de-datos, parser-e-importacion,
│                                   # autenticacion, arca, emision-y-envio, frontend,
│                                   # ownership-y-tests, marca, produccion
├── docker-compose.yml              # solo Postgres — ver *Cómo se corre*
├── docker-compose.prod.yml         # db + app + web, para la VM
├── .env.example                    # el .env de PRODUCCIÓN (el de dev es backend/.env.example)
├── certs/                          # los certificados de ARCA — en .gitignore, no viajan
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── docker-entrypoint.sh        # alembic upgrade head y después uvicorn
│   ├── .env.example
│   ├── src/factumov/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── logging_config.py     # que los INFO de la app se impriman — ver *produccion*
│   │   ├── models/      # SQLAlchemy
│   │   ├── schemas/     # Pydantic — entrada/salida de la API
│   │   ├── crud/
│   │   ├── routers/     # solo JSON
│   │   ├── templates/   # un solo archivo: el comprobante impreso (HTML → PDF)
│   │   └── services/
│   │       ├── invoice_parser.py   # PDF → ParsedInvoice (lee facturas ajenas)
│   │       ├── invoice_draft.py    # ParsedInvoice → InvoiceTemplateDraft
│   │       ├── invoice_totals.py   # neto, IVA y total según la letra
│   │       ├── emission.py         # modelo → CAE de ARCA → Invoice guardada
│   │       ├── balance360.py       # copia la factura emitida a Balance360
│   │       ├── subscription.py     # la política comercial: quién es Pro y qué puede un Free
│   │       ├── secrets.py          # cifra los secretos que hay que poder volver a leer
│   │       └── invoice_pdf.py      # Invoice → QR + HTML + PDF (imprime las propias)
│   └── tests/
│       └── samples/                # 10 facturas PDF reales (1 A, 4 B, 5 C)
│           └── unsupported/       # otros layouts, fuera del glob de los tests
└── frontend/                       # Vite + React 19 + TypeScript
    ├── Dockerfile                  # build de la SPA + el nginx que la sirve
    ├── nginx.conf                  # sirve el dist y proxea /api al app
    ├── vite.config.ts              # proxy /api → :8000
    ├── public/                     # ícono, sus PNG, manifest y el logo de InSoft
    ├── scripts/render_icons.py     # los PNG del ícono, derivados de su SVG
    └── src/
        ├── api/                    # client.ts (fetch) + types.ts (espejo de los schemas)
        ├── auth/                   # contexto de sesión
        ├── components/             # layout, guard de rutas, avisos, TileGrid, editor
        ├── hooks/                  # useResource, useLongPress
        └── pages/                  # una grilla y un editor por recurso
```

## Notas
- La documentación es un documento vivo — editala a medida que el proyecto avance.
- **Una decisión no obvia que se tome en una sesión de Code va al archivo de `docs/` de su
  área**, no acá. Este archivo solo crece si cambia una regla de trabajo, el stack o una
  convención — o si hay que sumar un área nueva al índice.
- Si un área nueva no entra en ninguno de los archivos que ya están, se abre uno y se lo suma
  al índice de acá y al de [`docs/README.md`](docs/README.md). Los dos, o el mapa miente.
