# Proyecto: FactuMov — App de Facturación

## Objetivo
Nueva app de facturación, independiente de Balance360 pero reutilizando su lógica de
backend ya probada. Debe funcionar en Android, iOS y Desktop.

## Funcionalidades core
1. Crear un modelo a partir de la importación de una factura en PDF.
2. Permitir la edición de ese modelo.
3. Almacenar el modelo.
4. Emitir nuevas facturas haciendo pequeñas modificaciones sobre un modelo guardado.
5. (Eventual) Enviar la factura por email y/o WhatsApp.

## Cómo trabajamos en este proyecto
Miguel está usando este proyecto para aprender desarrollo (venía de saber algo de Python,
pero sin haber hecho un proyecto completo). La dinámica es la misma que rige en Balance360:

**Regla fundamental — Claude nunca escribe código Python. Sin excepciones.**

El rol de Claude en Python es:
- Explicar el concepto o patrón a aplicar, con alternativas y trade-offs.
- Indicar qué archivo y qué función crear o modificar.
- Describir qué debe hacer el código, no cómo escribirlo.
- Señalar errores y explicar por qué son errores.
- Sugerir librerías o patrones que mejoren la calidad.
- Correr tests y linters para mostrar el error concreto en vez de opinar.

**Claude sí escribe HTML / CSS / JS.** Es su única responsabilidad de escritura de código.
En este proyecto eso incluye todo el frontend React.

**Excepción — primer ejemplo de un patrón nuevo.** Cuando Miguel nunca escribió algo de
cierto tipo (el primer test de pytest, el primer router, el primer schema de Pydantic, la
primera migración a mano…), Claude puede escribir **un** ejemplo completo que sirva de
modelo, explicando cada decisión. Del segundo en adelante vuelve a escribirlo Miguel.
Condiciones: Miguel lo pide explícitamente — Claude nunca lo asume — y el ejemplo se explica
línea por línea, porque el objetivo es el patrón, no el archivo.

**Migraciones (Alembic): las escribe Claude.** Decisión del 2026-08-08 — Miguel prefiere
concentrarse en FastAPI y SQLAlchemy; Alembic es una herramienta aparte y se delega. Claude
genera, revisa y aplica las migraciones, y explica qué cambió y por qué.
Los **modelos** los sigue escribiendo Miguel. El flujo es: Miguel edita el modelo → Claude
genera la migración, la revisa y la aplica.

**Regex / parsing de PDF: lo escribe Claude.** Decisión del 2026-08-09 — misma lógica que
Alembic: las expresiones regulares son una habilidad aparte que Miguel quiere aprender más
adelante, no ahora. Claude escribe y mantiene `services/invoice_parser.py` (layouts,
extractores, regex) y explica qué hace cada patrón.
Lo que **no** delega: routers, schemas, CRUD, servicios de negocio y modelos siguen siendo
de Miguel. El parser es una excepción acotada, no una puerta abierta al backend.

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
- Toda la conversación de mentoring ocurre en **inglés** (misma política que Balance360).
- Después de cada mensaje del usuario, si hay errores de gramática, vocabulario o fraseo,
  agregar una nota breve **"Prompt feedback"** con la versión corregida y una explicación
  corta. Mantenerlo conciso; no desviar el trabajo técnico.
- Los strings de UI de la app siguen en español.

## Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 (sync) + Alembic + PostgreSQL. Gestor: `uv`.
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
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── src/factumov/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models/      # SQLAlchemy
│   │   ├── schemas/     # Pydantic — entrada/salida de la API
│   │   ├── crud/
│   │   ├── routers/     # solo JSON
│   │   └── services/
│   │       └── invoice_parser.py
│   └── tests/
└── frontend/
```

## Relevamiento de servicios de Balance360 (hecho — 2026-08-08)
Ruta real: `E:\Capacitacion\InSoft\Balance360\Balance360\src\balance360\services\`

| Servicio | Qué hace | Reutilización |
|---|---|---|
| `pdf_invoice.py` | **Parser** de facturas PDF de terceros: pdfplumber + regex, con un registry de layouts por proveedor (Dux, Venex, ZTECNO, Air/NVX…). Lógica pura, sin DB ni red. | ✅ **Copiar tal cual** a `services/invoice_parser.py`. Es el core de la funcionalidad #1. |
| `wsfe.py` | Cliente WSFEv1: último número de comprobante + solicitud de CAE (`FECAESolicitar`), con IVA, tributos y comprobantes asociados (NC). | 🟡 Extraer los DTOs (`InvoiceRequest`, enums `VoucherType`/`Concepto`) para que no dependan de Balance360. |
| `arca.py` | Autenticación WSAA contra ARCA: firma un TRA con cert + clave privada, obtiene token/sign, cachea el ticket. Incluye workaround TLS (AFIP negocia DH de 1024 bits). | 🟡 Desacoplar `balance360.database.settings` (inyectar config) y la ruta hardcodeada `ticket_arca.json`. |
| `invoice_pdf.py` | Genera el **QR fiscal** que ARCA exige en el PDF impreso, a partir de un `Invoice` del ORM. | 🟠 Refactor: que reciba un DTO plano en vez del modelo ORM. |
| `invoice.py` | Orquestador: confirmar / pagar / eliminar factura, crear NC, `authorize_invoice`. | 🔴 No reutilizable directo — muy acoplado a stock, seriales y CRUD de Balance360. Sirve como referencia del flujo. |

**`pdf_invoice.py` e `invoice_pdf.py` NO son duplicados.** El primero *lee* facturas ajenas
(parsing), el segundo *genera* el QR de una factura propia. Los nombres chocan por accidente.

## Parser (`services/invoice_parser.py`) — estado al 2026-08-09
Reescrito a partir del de Balance360 y verificado contra las 9 muestras de `samples/`.
Extrae todo: emisor, receptor, período, CAE e items.

- **Un solo layout: ARCA "Comprobantes en línea".** Todas las facturas de Miguel salen de
  ahí. Se borraron los otros nueve layouts de Balance360: un regex que no se puede verificar
  contra un PDF real es un pasivo, no una función.
- **El PDF trae la factura tres veces** (ORIGINAL / DUPLICADO / TRIPLICADO). Se corta en el
  primer `DUPLICADO`; si no, toda extracción encuentra tres de cada cosa.
- **ARCA no imprime alícuota por línea**: se deduce de la letra (C → 0, A y B → 21).
- **En B el precio impreso ya incluye IVA** (lo confirma "IVA Contenido" del Régimen de
  Transparencia Fiscal). Se guarda el precio tal como viene y la letra decide cómo
  interpretarlo — misma convención que `Invoice.iva_breakdown` de Balance360.
- **El documento del receptor puede ser CUIT, CUIL o DNI**, por eso `customer_doc_number` y
  no `customer_cuit`. Las facturas a consumidor final traen DNI.
- **Los domicilios se parten en dos renglones** y hay que reensamblarlos.
- Los campos del emisor se llaman `issuer_*`, no `supplier_*`: en FactuMov el emisor es el
  propio usuario.

## Decisión: NO armar todavía el paquete compartido de ARCA/WSFE
El primer hito (importar PDF → modelo editable → guardarlo) no necesita ARCA ni WSFE.
Solo necesita el parser, que es lógica pura y se copia sin costo. Diseñar hoy la
abstracción para compartir `arca.py`/`wsfe.py` sería decidir a ciegas: cuando se llegue a
emitir con CAE habrá mucha más información sobre qué forma debe tener. Revisar esta
decisión al empezar la funcionalidad #4.

## Decisiones de producto (2026-08-08)
- El PDF que se importa es **una factura emitida por el propio usuario**, no de un proveedor.
  Consecuencia importante: el parser de Balance360 hay que **extenderlo**. Hoy extrae al
  emisor (`supplier_cuit`, `supplier_name`, …) y descarta deliberadamente al receptor — y el
  receptor es justamente el dato que FactuMov necesita, porque el emisor siempre es el usuario.
- FactuMov es **multi-entidad**, como Balance360: varias razones sociales / CUIT emisores.

## Modelo de datos — principio rector
Un `InvoiceTemplate` es una `Invoice` **menos todo lo que cambia en cada emisión**. Los
campos de `Invoice` de Balance360 se parten en tres grupos:

| Grupo | Campos | ¿Va en el template? |
|---|---|---|
| Identidad / relaciones | `entity_id`, `fiscal_identity_id`, receptor, `voucher_type`, `pos`, `concepto` | ✅ Sí — es lo que define al modelo |
| Contenido | líneas (descripción, cantidad, precio, alícuota) | ✅ Sí — se ajusta al emitir |
| Hechos de la emisión | `date`, `number`, `cae`, `cae_expiry`, `confirmed`, `paid`, `authorized`, `from_date`/`to_date`/`due_date` | ❌ No — los asigna ARCA o el momento de emisión |

Emitir = tomar un `InvoiceTemplate`, permitir retoques, y crear una `Invoice` nueva.

### Desviaciones deliberadas respecto de Balance360
1. **`quantity` es `Numeric`, no `Integer`.** Balance360 la tiene como `Integer`, pero el
   parser devuelve `Decimal` y captura cantidades como `1,00` o `2,50`. Servicios y
   productos por peso necesitan fracciones.
2. **`TimestampMixin` sin `created_by` / `modified_by`.** Los de Balance360 son FK a
   `users.id`; copiarlos tal cual obligaría a crear la tabla `users` antes de tiempo.
   Se agregan cuando exista autenticación.
3. **`Customer` en vez de `Contact`.** FactuMov solo emite; no necesita el `contact_type`
   (customer/supplier/both) que Balance360 usa porque también registra compras.
4. **Líneas con `position` explícito.** Balance360 ordena por `created_at`, que se rompe si
   el usuario reordena las líneas en el editor.
5. **No existe `Entity`.** En Balance360, `Entity` responde "¿en los libros de quién va este
   movimiento?" — es un concepto contable. FactuMov no lleva libros: solo emite. El emisor
   es `FiscalIdentity`, y "multi-entidad" significa simplemente varias filas en esa tabla.
   Esto ahorra una tabla, la asociación many-to-many y un `entity_id` en cada query.
6. **Los enums de dominio fiscal quedan en español** (`Concepto`, `CondicionIva`), aunque la
   convención general sea inglés. Son los nombres que usa ARCA en el request de WSFE
   (`Concepto`, `CondicionIVAReceptorId`); traducirlos agregaría un paso de traducción
   mental cada vez que se lee el código de emisión.

### Tablas del modelo
| Tabla | Rol |
|---|---|
| `FiscalIdentity` | Emisor: CUIT, razón social, condición IVA, IIBB, domicilio |
| `Customer` | Receptor |
| `InvoiceTemplate` | Emisor + cliente + tipo de comprobante + punto de venta + concepto |
| `InvoiceTemplateLine` | Descripción, cantidad, precio unitario, alícuota, posición |

## Notas
- Este archivo es un documento vivo — editalo a medida que el proyecto avance.
- Convenciones de código, estructura de carpetas y decisiones técnicas que se vayan
  tomando en las sesiones de Code deberían agregarse acá para que persistan.
