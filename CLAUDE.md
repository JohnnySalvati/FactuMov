# Proyecto: FactuMov — App de Facturación

## Objetivo
Nueva app de facturación, independiente de Balance360 pero reutilizando su lógica de
backend ya probada. Debe funcionar en Android, iOS y Desktop.

**El celular es el caso principal** (confirmado el 2026-08-26); la computadora tiene que
andar, pero es el secundario. No es un matiz de diseño: define que el CSS se escribe
mobile-first —el estilo base es el de pantalla angosta y las media queries agregan con
`min-width`— y que cada pantalla nueva se piensa primero en 360 px de ancho. Escrito al
revés, cada pantalla nace ancha y hay que acordarse de angostarla, o sea que el caso
principal queda dependiendo de que nadie se olvide.

## Funcionalidades core
1. Crear un modelo a partir de la importación de una factura en PDF.
2. Permitir la edición de ese modelo.
3. Almacenar el modelo.
4. Emitir nuevas facturas haciendo pequeñas modificaciones sobre un modelo guardado.
5. (Eventual) Enviar la factura por email y/o WhatsApp.

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
├── CLAUDE.md                       # no hay README: este archivo es la documentación
├── docker-compose.yml              # solo Postgres — ver *Cómo se corre*
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
│   │   ├── templates/   # un solo archivo: el comprobante impreso (HTML → PDF)
│   │   └── services/
│   │       ├── invoice_parser.py   # PDF → ParsedInvoice (lee facturas ajenas)
│   │       ├── invoice_draft.py    # ParsedInvoice → InvoiceTemplateDraft
│   │       ├── invoice_totals.py   # neto, IVA y total según la letra
│   │       ├── emission.py         # modelo → CAE de ARCA → Invoice guardada
│   │       └── invoice_pdf.py      # Invoice → QR + HTML + PDF (imprime las propias)
│   └── tests/
│       └── samples/                # 10 facturas PDF reales (1 A, 4 B, 5 C)
│           └── unsupported/       # otros layouts, fuera del glob de los tests
└── frontend/                       # Vite + React 19 + TypeScript
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

## Relevamiento de servicios de Balance360 (hecho — 2026-08-08)
Ruta real: `E:\Capacitacion\InSoft\Balance360\Balance360\src\balance360\services\`

| Servicio | Qué hace | Reutilización |
|---|---|---|
| `pdf_invoice.py` | **Parser** de facturas PDF de terceros: pdfplumber + regex, con un registry de layouts por proveedor (Dux, Venex, ZTECNO, Air/NVX…). Lógica pura, sin DB ni red. | ✅ **Copiar tal cual** a `services/invoice_parser.py`. Es el core de la funcionalidad #1. |
| `wsfe.py` | Cliente WSFEv1: último número de comprobante + solicitud de CAE (`FECAESolicitar`), con IVA, tributos y comprobantes asociados (NC). | ✅ **Portado entero** (2026-08-27). Sin tributos ni comprobantes asociados: FactuMov no emite NC. |
| `arca.py` | Autenticación WSAA contra ARCA: firma un TRA con cert + clave privada, obtiene token/sign, cachea el ticket. Incluye workaround TLS (AFIP negocia DH de 1024 bits). | 🟡 Desacoplar `balance360.database.settings` (inyectar config) y la ruta hardcodeada `ticket_arca.json`. |
| `invoice_pdf.py` | Genera el **QR fiscal** que ARCA exige en el PDF impreso, a partir de un `Invoice` del ORM. | ✅ **Portado** (2026-08-27), junto con `templates/invoices/pdf.html`. Sigue recibiendo el `Invoice`, que acá ya trae copiadas las dos partes. |
| `invoice.py` | Orquestador: confirmar / pagar / eliminar factura, crear NC, `authorize_invoice`. | 🔴 No reutilizable directo — muy acoplado a stock, seriales y CRUD de Balance360. Sirve como referencia del flujo. |

**`pdf_invoice.py` e `invoice_pdf.py` NO son duplicados.** El primero *lee* facturas ajenas
(parsing), el segundo *genera* el QR de una factura propia. Los nombres chocan por accidente.

**Actualización 2026-08-26:** apareció un servicio que no estaba en el relevamiento original,
`padron.py` — consulta al padrón de ARCA (`ws_sr_constancia_inscripcion`) para completar un
contacto a partir del CUIT. Ya está portado (ver *ARCA*).

**Actualización 2026-08-27:** con `FECAESolicitar` portado (ver *Emisión con CAE*), de los
seis servicios del relevamiento quedan afuera solo `invoice_pdf.py` —que va con la unidad del
mail— e `invoice.py`, que nunca fue reutilizable.

## Parser (`services/invoice_parser.py`) — estado al 2026-08-18
Reescrito a partir del de Balance360 y verificado contra las 10 muestras de
`backend/tests/samples/`. Extrae todo: emisor, receptor, período, CAE e items.

- **Un solo layout: ARCA "Comprobantes en línea".** Todas las facturas de Miguel salen de
  ahí. Se borraron los otros nueve layouts de Balance360: un regex que no se puede verificar
  contra un PDF real es un pasivo, no una función.
- **El PDF trae la factura tres veces** (ORIGINAL / DUPLICADO / TRIPLICADO). Se corta en el
  primer `DUPLICADO`; si no, toda extracción encuentra tres de cada cosa.
- **La alícuota se lee en A y se deduce en B y C.** Solo la A discrimina IVA por línea, y
  ahí hay que leer la columna: una misma factura A puede mezclar 21% y 10,5%, así que
  deducirla de la letra da un número plausible y equivocado. En B y C esa columna no existe
  y la letra es toda la información que hay (C → 0, B → 21).
- **Las columnas de items no son las mismas en todas las letras**, ni en cantidad ni en
  orden:

  | Letra | Después de Precio Unit. |
  |---|---|
  | B y C | `% Bonif` `Imp. Bonif.` `Subtotal` — 3 |
  | A | `% Bonif` `Subtotal` `Alícuota IVA` `Subtotal c/IVA` — 4 |

  La A no imprime `Imp. Bonif.` y sí agrega la alícuota. El extractor decide por la
  cantidad de columnas y no por el encabezado, que en la A viene partido en dos renglones
  (`Alicuota` arriba, `IVA` abajo). Se aceptan solo esos dos anchos a propósito: ante un
  layout desconocido conviene no matchear —falta la línea y `needs_manual_items` lo
  delata— antes que matchear corrido y meter en la alícuota el número de otra columna.
- **La unidad de medida no es siempre `unidades`.** ARCA ofrece horas, kilogramos, metros,
  docenas. Estaba hardcodeada, y una línea facturada en otra unidad no matcheaba: la línea
  desaparecía del draft sin ninguna señal.
- **El rótulo del domicilio del receptor cambia con la letra**: B y C imprimen `Domicilio:`
  y A imprime `Domicilio Comercial:`. Exigir la forma corta dejaba a todo receptor de una A
  sin condición frente al IVA ni domicilio.
- **En B el precio impreso ya incluye IVA** (lo confirma "IVA Contenido" del Régimen de
  Transparencia Fiscal); en A viene neto (35000 × 1,21 = 42350 en la muestra A lo
  confirma). Se guarda el precio tal como viene y la letra decide cómo interpretarlo —
  misma convención que `Invoice.iva_breakdown` de Balance360.
- **El documento del receptor puede ser CUIT, CUIL o DNI**, por eso `customer_doc_number` y
  no `customer_cuit`. Las facturas a consumidor final traen DNI.
- **Los domicilios se parten en dos renglones** y hay que reensamblarlos.
- Los campos del emisor se llaman `issuer_*`, no `supplier_*`: en FactuMov el emisor es el
  propio usuario.

### Pendiente: un segundo layout (2026-08-26)
`tests/samples/unsupported/factura_A_00005-00000001.pdf` es una factura A real de Miguel que
el parser hoy **no** sabe leer: saca `pos`, `number`, `date`, CAE, IIBB y fecha de inicio, y
nada más. Sin CUIT del emisor, sin receptor y sin líneas. No hay nada roto — es otro
generador, no ARCA "Comprobantes en línea":

| | Comprobantes en línea | El PDF nuevo |
|---|---|---|
| Copias | ORIGINAL + DUPLICADO + TRIPLICADO | una sola, `Pág. 1/1` |
| CUIT | `20182810674` | `20-18281067-4`, con guiones |
| Columnas de items | `Código` `Producto/Servicio` `Cantidad` `U. Medida` `Precio Unit.` `% Bonif` … | `Producto/Servicio` `Cantidad` `Precio Unit.` … — sin código, **sin U. Medida**, sin bonif |
| Tipo de comprobante | rótulo de ARCA | `COD. 01`, pegado a la razón social |
| Datos del emisor | un campo por renglón | varios por renglón (`Condición frente al IVA: … CUIT: …`) |
| Peso | ~86 KB | 19 KB |

Los guiones tumban `_ISSUER_CUIT` y `_CUSTOMER`, que piden 11 dígitos seguidos; la falta de
`U. Medida` tumba `_ITEM_ROW`, que exige el token de unidad entre cantidad y precio; y los
campos apilados en un mismo renglón tumban los regex del emisor, que buscan el rótulo
siguiente y `.` no cruza saltos de línea.

Soportarlo es **volver a un registry de layouts**, que es justamente lo que se borró de
Balance360 — pero con la diferencia que hacía a esa decisión: acá hay un PDF real contra el
cual verificar. Miguel confirmó que es una factura suya y que hay que soportarla, más
adelante. Mientras tanto vive en `samples/unsupported/`, fuera del glob de
`test_every_sample_parses_end_to_end`.

## Decisión: NO armar el paquete compartido de ARCA/WSFE — confirmada el 2026-08-26
El primer hito (importar PDF → modelo editable → guardarlo) no necesita ARCA ni WSFE.
Solo necesita el parser, que es lógica pura y se copia sin costo. Diseñar hoy la
abstracción para compartir `arca.py`/`wsfe.py` sería decidir a ciegas: cuando se llegue a
emitir con CAE habrá mucha más información sobre qué forma debe tener.

Revisada al portar ARCA, que era el momento previsto. **Se confirma: copia adaptada, no
paquete compartido.** Ahora hay información concreta y dice que no: de los tres servicios
portados, ninguno quedó igual. `arca.py` cambió el caché de ticket de archivo a tabla,
`wsfe.py` no tiene el mismo `Auth.Cuit` —en Balance360 el certificado es del propio
contribuyente, en FactuMov representa a terceros— y los tres pasaron de `settings` global a
config inyectada. Un paquete compartido tendría que parametrizar exactamente esas tres cosas,
que es donde está toda la diferencia entre las dos apps. Lo que sí se comparte sin costo son
las constantes que ARCA fija: URLs de WSDL, códigos de error, `idImpuesto`.

## Decisiones de producto (2026-08-08)
- El PDF que se importa es **una factura emitida por el propio usuario**, no de un proveedor.
  Consecuencia importante: el parser de Balance360 hay que **extenderlo**. Hoy extrae al
  emisor (`supplier_cuit`, `supplier_name`, …) y descarta deliberadamente al receptor — y el
  receptor es justamente el dato que FactuMov necesita, porque el emisor siempre es el usuario.
- FactuMov es **multi-entidad**, como Balance360: varias razones sociales / CUIT emisores.

### FactuMov no admite clientes sin documento (2026-08-18)
El alcance es la emisión repetida a **clientes habituales**, y un comprador anónimo no tiene
modelo guardado que reutilizar — la misma lógica por la que un `InvoiceTemplate` no guarda
`date` ni `number`. Se borró `DocType.FINAL` (código 99 de ARCA, "sin identificar") y
`doc_number` pasó a ser obligatorio.

- **No impide facturar a un consumidor final.** Eso es `CondicionIva.FINAL`, otro enum en
  otra columna, y queda intacto: la muestra B `30714597066_006_00010_00000055.pdf` tiene un
  receptor con CUIT y `condicion_iva = FINAL`. Lo único que se pierde es guardar un cliente
  que no entregó **ningún** documento.
- **Elimina una clase de bug entera, no solo código.** `doc_number` podía ser NULL
  únicamente por culpa de FINAL, y un cliente con documento NULL era invisible para
  `get_by_doc` para siempre: cada importación del mismo PDF le creaba un duplicado. Es el
  bug que motivó `ck_customers_doc_number_required` (migración `070c8508060a`). Con la
  columna NOT NULL, `get_by_doc` es total y la causa desaparece en vez de parchearse.
- **Alinea el enum con el parser.** `DocType` queda en `{CUIT, CUIL, DNI}`, que es
  exactamente lo que `_CUSTOMER` sabe leer del PDF: la alternación del regex es
  `CUIT|CUIL|DNI`. Antes el router tenía una rama `is not DocType.FINAL` inalcanzable,
  porque aplicaba vocabulario del emisor a un valor que sólo el parser podía traer.
- **Lo que se fue con ella:** el índice parcial (pasa a `UniqueConstraint`, ya no hay filas
  exentas), el check constraint, el validador de `CustomerCreate`, el caso especial de
  `update_or_create` y la rama del router.
- **Revertirla es posible pero no gratis:** la migración `cf79c4f7610c` tiene `downgrade`,
  pero restituye la forma, no los datos. Los clientes que eran FINAL recibieron un documento
  real para poder migrar, y nada los distingue después de los que siempre lo tuvieron. La
  migración **se niega a correr** si encuentra alguna fila FINAL o con `doc_number` NULL, en
  vez de destruirla.

## Modelo de datos — principio rector
Un `InvoiceTemplate` es una `Invoice` **menos todo lo que cambia en cada emisión**. Los
campos de `Invoice` de Balance360 se parten en tres grupos:

| Grupo | Campos | ¿Va en el template? |
|---|---|---|
| Identidad / relaciones | `entity_id`, `fiscal_identity_id`, receptor, `pos`, `concepto` | ✅ Sí — es lo que define al modelo |
| Derivados | `voucher_type` | ❌ No — sale de los dos anteriores; ver *La letra del comprobante* |
| Contenido | líneas (descripción, cantidad, precio, alícuota) | ✅ Sí — se ajusta al emitir |
| Hechos de la emisión | `date`, `number`, `cae`, `cae_expiry`, `confirmed`, `paid`, `authorized`, `from_date`/`to_date`/`due_date` | ❌ No — los asigna ARCA o el momento de emisión |

Emitir = tomar un `InvoiceTemplate`, permitir retoques, y crear una `Invoice` nueva.

### Desviaciones deliberadas respecto de Balance360
1. **`quantity` es `Numeric`, no `Integer`.** Balance360 la tiene como `Integer`, pero el
   parser devuelve `Decimal` y captura cantidades como `1,00` o `2,50`. Servicios y
   productos por peso necesitan fracciones.
2. **`TimestampMixin` sin `created_by` / `modified_by`** — decidido el 2026-08-26, no
   diferido. Se venían postergando hasta la unidad de *ownership scoping*, y esa unidad
   resolvió no traerlos: `user_id` ya responde de quién es la fila, y con un único dueño
   por fila —nadie más la puede leer ni tocar— `created_by` y `modified_by` valdrían
   siempre lo mismo que `user_id`. Balance360 los necesita porque varios usuarios operan
   sobre los mismos libros; acá no hay nada compartido. Se revisa si aparece acceso
   compartido (el contador con acceso a las identidades de su cliente): ese es el cambio
   que vuelve real la pregunta "quién tocó esto", y es también el que va a decidir si la
   propiedad sigue siendo una columna o pasa a ser una tabla de asociación.
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
| `FiscalIdentity` | Emisor: CUIT, razón social, condición IVA, IIBB, domicilio, estado de la delegación (verificada, y el aviso del usuario de que ya delegó) |
| `Customer` | Receptor |
| `InvoiceTemplate` | Emisor + cliente + punto de venta + concepto (la letra se deduce) |
| `InvoiceTemplateLine` | Descripción, cantidad, precio unitario, alícuota, posición |
| `Invoice` | Factura **emitida**: número, CAE, importes y copia de las dos partes |
| `InvoiceLine` | La línea tal como se emitió |
| `User` | Cuenta: email, hash de contraseña, confirmación, alta/baja |
| `UserSession` | Sesión abierta: hash del token, vencimiento absoluto, revocación |
| `EmailConfirmation` | Token de confirmación de email, de un solo uso |
| `PasswordReset` | Token para elegir contraseña nueva, de un solo uso |
| `ArcaTicket` | Ticket de acceso de WSAA, por entorno y servicio. La única tabla sin dueño |

### Decisiones sobre `InvoiceTemplate` (2026-08-15)
- **Nombre único por identidad fiscal** — `UniqueConstraint(fiscal_identity_id, name)`, no un
  índice parcial como el de `Customer`: acá no hay ninguna fila exenta de la regla. Dos
  razones sociales sí pueden tener cada una su "Alquiler mensual".
- **Sin unique sobre `(template_id, position)`.** Es correcta en teoría y cara en la práctica:
  reordenar las líneas dentro de un mismo flush deja transitoriamente dos líneas en la misma
  posición. El invariante se mantiene en el CRUD, que asigna `position` con `enumerate()`.
- **`position` no es campo de entrada.** El cliente manda un array ordenado; el orden del
  array *es* la posición. Aceptarla del cliente obligaría a validar huecos, duplicados y
  negativos sin ganar nada: el editor es una lista drag-and-drop que siempre conoce el orden
  completo.
- **`template_id` no va en los schemas de línea.** En create todavía no existe el padre, y en
  update el padre viene del path: tenerlo en el body solo abre la puerta a que discrepen.
- **Las líneas se reemplazan enteras en el update**, apoyándose en el `delete-orphan` de la
  relación. Diferenciar altas/bajas/modificaciones por id es más código y no aporta nada a un
  formulario que siempre manda el estado completo.
- **`lines` con `min_length=1` en create y update, y `None` como "no tocar".** Un template sin
  líneas no se puede emitir, así que `[]` es 422 y el CRUD solo distingue entre `None` y una
  lista no vacía.

### La letra del comprobante se deduce (2026-08-26)
**A, B o C no es una elección del usuario: es una consecuencia de quién le factura a quién.**
Lo fija ARCA a partir de la condición frente al IVA del emisor y de la del receptor. Port de
`allowed_for` de Balance360 —que intersecta dos conjuntos, "lo que esta condición puede emitir"
y "lo que esta condición puede recibir"— en `services/voucher.py`.

**FactuMov no ofrece notas de crédito**, y eso es lo que cambia el resultado. La app automatiza
el comprobante que se repite todos los meses; nadie le emite una NC a sus clientes todos los
meses. La NC es la excepción, y la excepción se hace a mano en el sitio de ARCA. Sacadas las
tres NC de los conjuntos de Balance360, la intersección pasa de ser un menú a ser **siempre un
solo elemento**:

| Emisor \ Receptor | Inscripto | Monotributo | Exento | Consumidor final |
|---|---|---|---|---|
| **Inscripto**   | A | **A** | B | B |
| **Monotributo** | C | C | C | C |
| **Exento**      | C | C | C | C |

**La celda Inscripto → Monotributo decía B hasta el 2026-08-27, y estaba mal.** Es A, por la
Ley 27.618: desde 2021 el responsable inscripto que le factura a un monotributista emite A. No
es una interpretación — ARCA **rechaza** la B en ese par con el código 10243 y autoriza la A,
verificado emitiendo las dos en homologación. Ver *Emisión con CAE → Dos códigos heredados de
Balance360 estaban mal*.

No hay fila de emisor consumidor final porque no puede emitir: `FiscalIdentityCreate` lo rechaza
con 422 desde antes, y `voucher_type_for` levanta `UndecidableVoucherTypeError` si alguien
aflojara ese validador — un error ruidoso en vez de una letra plausible y equivocada.

- **`voucher_type` dejó de ser una columna** de `invoice_templates` (migración `3d9a71e0c4b2`).
  Guardar un valor que es función de otros dos valores guardados es una tercera fuente de verdad
  capaz de contradecir a sus padres — el mismo argumento por el que `invoice_templates` no lleva
  `user_id`. Y acá no es teórico: el día que un cliente se inscribe en IVA, todos los modelos que
  le facturan pasan de B a A. Con la columna, siguen diciendo B hasta que alguien se dé cuenta, y
  lo que sigue es un CAE rechazado o —peor— una factura aceptada y legalmente equivocada.
- **Es una propiedad de `InvoiceTemplate`, no un campo calculado en el schema.** El que la va a
  necesitar de nuevo es el código de emisión, que trabaja con el modelo y no con el `Read`.
  Consecuencia: toca las dos relaciones, así que el CRUD las trae con `joinedload` — sin eso,
  listar N modelos son 2N queries más.
- **Sale en `InvoiceTemplateRead` y no entra por ningún schema de escritura.** Mismo criterio que
  `delegation_verified_at`: la pantalla la necesita, el cliente no la decide. Mandarla en el body
  no rompe nada porque Pydantic la descarta, y hay un test que lo fija.
- **El desplegable del editor desapareció.** Tenía seis opciones de las cuales cinco eran siempre
  incorrectas para un par dado; ahora hay un renglón que dice qué comprobante sale, con la
  aclaración de que la define ARCA. Es un campo menos que llenar en la pantalla que se usa cien
  veces por semana, y una forma menos de emitir mal.
- **El `VoucherType` del enum conserva las NC**, y el tipo `vouchertype` de Postgres no se borró.
  Es el vocabulario de ARCA: el parser tiene que poder representar un PDF que sea una nota de
  crédito (`_ARCA_VOUCHER_TYPE` mapea los códigos 3, 8 y 13), y la tabla `invoices` de la unidad
  de emisión las va a necesitar. Lo que no existe es una NC *como modelo*.
- **El draft de importación ya no trae `voucher_type`.** El PDF sí dice qué letra era, y el
  parser la sigue leyendo —la necesita para deducir la alícuota en B y C—, pero el draft existe
  para sembrar el editor y el editor ya no tiene ese campo. Proponer una letra que después se
  recalcula sola es ofrecer una discusión que no puede ganar nadie.
- **La tabla está escrita tres veces, y las tres tienen su motivo.** `services/voucher.py` es la
  autoridad. `api/types.ts` la repite porque el editor muestra la letra y calcula el total
  *mientras* el usuario cambia de cliente, o sea antes de que exista nada que guardar — la misma
  copia a mano que el resto de ese archivo. Y la migración la repite en SQL porque una migración
  no puede depender del código de la app: el modelo de mañana no describe el esquema de hoy.
- **La migración se niega a borrar un dato que no cuadra.** Antes de tirar la columna compara
  cada fila guardada contra lo que la deducción da para sus padres, y corta con `RuntimeError` si
  alguna discrepa: puede ser una condición frente al IVA mal cargada o una letra elegida a mano a
  propósito, y las dos merecen una mirada humana. El `downgrade` sí puede ser exacto, al revés
  que el de `cf79c4f7610c`: reconstruye el valor de datos que siguen estando.

## Endpoint de importación (2026-08-17)
`POST /invoice-templates/import` recibe un PDF y devuelve un `InvoiceTemplateDraft`. Cierra
la funcionalidad #1 del lado del backend: parser + draft + HTTP.

- **Responde 200, no 201.** No persiste nada. El draft es una propuesta que el usuario
  revisa en el editor y recién después confirma con `POST /invoice-templates`. Acá POST
  significa "procesá esto", no "creá esto".
- **Lee la base pero no escribe.** Resuelve el emisor por CUIT (`get_by_tax_id`) y el
  receptor por documento (`get_by_doc`), y devuelve esos ids dentro del draft. No llama a
  `update_or_create`: dar de alta un cliente que el usuario todavía no confirmó convierte
  una vista previa en un efecto secundario, y reimportar el mismo PDF le forkearía la
  historia. El test lo fija contando filas de `customers` después del request.
- **Los datos parseados del receptor viajan igual cuando la fila ya existe**, al lado del
  `customer_id`. El editor los muestra contra lo guardado para que el usuario vea si cambió
  el domicilio o la razón social.
- **El draft sale sin nombre.** El nombre del template lo elige el usuario en el editor; el
  PDF no lo trae. Por eso `build_draft` no recibe ningún `name`.
- **La ruta literal va declarada antes que `/{invoice_template_id}`.** FastAPI resuelve en
  orden de declaración y `GET /{invoice_template_id}` matchea el path
  `/invoice-templates/import`: con la literal abajo, el POST responde 405.
- **Endpoint sync (`def`), no `async def`.** `SessionDep` es una `Session` sincrónica y
  pdfplumber es CPU-intensivo; en un `def` FastAPI lo corre en el threadpool y el event loop
  queda libre. Consecuencia: los bytes se leen con `file.file.read(...)`, no con `await`.
- **Un PDF ilegible no es un error.** El parser devuelve todo en `None` en vez de tirar
  excepción, así que el endpoint responde 200 con un draft vacío y la UI ofrece carga
  manual. `needs_manual_items` no se propaga al draft porque es exactamente `lines == []`.
- **413 y 415 se resuelven antes de parsear**, el tamaño primero porque es el chequeo que
  acota el trabajo, el tipo después aprovechando los bytes ya leídos. El límite se aplica
  leyendo un byte de más (`MAX_UPLOAD_BYTES + 1`): si vuelven más bytes que el límite,
  sobra. Una sola llamada, una sola comparación, y sin el `int | None` de `UploadFile.size`
  que en mypy strict obliga a un guard aparte. El truco se apoya en que un `read(n)` corto
  solo puede significar EOF: cierto para el spool de Starlette (`BytesIO` antes del
  rollover, `BufferedRandom` después), falso en un stream sin buffer.
- **El tipo se decide por los magic bytes, no por `content_type`.** El header lo pone el
  archivo; el `Content-Type` lo declara el cliente y miente en las dos direcciones — httpx
  manda `application/octet-stream` cuando no se especifica, así que chequearlo rechazaría
  PDFs legítimos. Se compara contra `%PDF-` con guion: la versión va siempre pegada al
  marcador, y sin el guion cualquier cosa que empiece con `%PDF` pasaría el filtro.
- **415 y "PDF ilegible" no son lo mismo.** Un JPEG o un .docx no son de este tipo de medio
  y se rechazan con 415. Un PDF escaneado o corrupto sí lo es, y cae en el 200 con draft
  vacío del punto anterior. Rechazar y ofrecer carga manual son respuestas a situaciones
  distintas y no deberían colapsar en una sola.
- **`MAX_UPLOAD_BYTES` es una constante del módulo, leída adentro de la función.** No va en
  el `Settings` de `database.py`, que es sobre la base. Que sea un global resuelto en tiempo
  de llamada es además lo que deja parchearlo desde un test: como valor por defecto de un
  parámetro, o importado por nombre en otro módulo, el test parchearía una copia que nadie
  mira.

**Pendiente:** el guard acota lo que el proceso copia y parsea, no lo que el server ingiere.
Para cuando la función corre, Starlette ya volcó el body entero a un `SpooledTemporaryFile`
—memoria hasta 1 MB, disco después—. El techo real va en el borde: `client_max_body_size`
de nginx, o un middleware ASGI que cuente los chunks de `http.request` y corte en el medio.
El `max_part_size` de Starlette no alcanza: solo mide las partes que no son archivo.

## Autenticación (2026-08-18)

### Registro y delegación en ARCA — decisión de producto
- El usuario se registra con email + contraseña y confirma la dirección.
- Después la app le manda por email las instrucciones para otorgar la **delegación en
  ARCA**: el contribuyente autoriza al CUIT del certificado de FactuMov a usar WSFE en su
  nombre.
- **FactuMov verifica la delegación por su cuenta** en vez de pedirle al usuario que la
  confirme: una autenticación WSAA más una llamada WSFE inocua. Si sale bien, la identidad
  fiscal pasa a "delegación activa", y recién ahí puede emitir.
- **El estado de la delegación vive en `FiscalIdentity`, no en `User`.** Un usuario puede
  tener varios CUIT, y cada uno se delega por separado.
- **La delegación prueba que el usuario controla ese CUIT**, porque no se puede otorgar sin
  la Clave Fiscal de ese CUIT. Eso es verificación de titularidad, **no** autenticación de
  FactuMov: ARCA nunca ve a nuestros usuarios y no ofrece identity provider para apps de
  terceros. La autenticación propia carga con todo el peso — y la delegación le sube la
  apuesta, porque una vez otorgada un compromiso de FactuMov puede emitir facturas
  legalmente válidas contra un CUIT real.

### Registro self-serve
Alternativa descartada: invite-only. Self-serve implica que la unidad de registro construye
un `POST /auth/register` público, con confirmación por email y el rate limiting que lo
protege: los dos quedan en el camino crítico, no son opcionales.

Consecuencia inmediata sobre el modelo: **`email_confirmed_at` existe desde ya**, aunque el
envío del mail sea de una unidad posterior. Un usuario sin confirmar es una fila que no debe
poder loguearse, y `is_active` solo no alcanza: mezcla "nunca confirmó" con "lo dio de baja
un admin", que son estados distintos y con remedios distintos. Es timestamp y no booleano
porque el "cuándo" es justo lo que quieren tanto el reenvío de confirmación como cualquier
consulta de soporte. Agregarlo más tarde habría costado una segunda migración sobre una
tabla ya poblada, más una decisión de backfill sobre si los usuarios existentes cuentan
como confirmados.

El login se cierra sobre las dos condiciones desde el principio (`is_active` **y**
`email_confirmed_at is not None`). Agregar la columna y postergar el chequeo deja un agujero
silencioso que la unidad siguiente se tiene que acordar de tapar.

### El login no revela si un email está registrado
Misma respuesta —mismo body, mismo status— para email desconocido, contraseña incorrecta y
usuario sin confirmar. Los tres son 401 idénticos.

- **"Confirmá tu email" es un oráculo de enumeración**: confirma que la dirección existe.
  Por eso el usuario sin confirmar no recibe un mensaje propio.
- **El timing también contesta la pregunta.** Si el usuario no existe no hay hash contra el
  cual verificar, y volver antes de tiempo delata la diferencia. Se verifica contra un hash
  dummy y se descarta el resultado. El dummy se calcula **una sola vez al importar el
  módulo**, no por request: por request duplica el costo y crea su propia señal de timing.
  Tiene que ser un hash real con los parámetros reales, o los tiempos no coinciden.
- La misma regla rige para el reenvío de confirmación de la unidad siguiente: contesta
  siempre "si esa dirección está registrada, te mandamos un mail".

### Sesiones
- **Token opaco contra la tabla `user_sessions`, no JWT.** Un JWT es válido hasta que vence
  porque se verifica con la firma y nada más; revocarlo exige igual una tabla de revocados,
  o sea la consulta a la base que el JWT prometía evitar. Con logout y "cerrar todas las
  sesiones" en el alcance, la tabla no es un costo extra: es el mecanismo.
- **El token se guarda hasheado con SHA-256, no con argon2.** Sale de
  `secrets.token_urlsafe(32)` — 256 bits de entropía, no hay diccionario que atacar. Un KDF
  lento no compra nada y cuesta ~100 ms **en cada request autenticado**. Argon2 es lento a
  propósito porque las contraseñas son de baja entropía y las elige un humano: amenaza
  distinta, herramienta distinta. El hexdigest fija la columna en `String(64)`, y su
  `unique=True` es además el índice por el que cada request busca el token.
- **`hashed_password` es `String(255)`.** El PHC de argon2id que escribe pwdlib mide ~97
  caracteres y su largo se mueve con los parámetros. Los 72 que uno recuerda son el límite
  del **password de entrada** de bcrypt, no el largo de ningún hash: con `String(72)` el
  INSERT falla con `value too long for type character varying(72)`.
- **Vencimiento absoluto, no deslizante.** `expires_at` se fija en el login y no se extiende
  por usar la sesión.
- **La comparación de vencimiento se hace en SQL** (`expires_at > func.now()`), no trayendo
  la fila y comparando en Python. Una sola fuente de verdad para "ahora", y evita el
  `TypeError` de comparar un datetime naive con uno aware que `DateTime(timezone=True)` deja
  servido. De paso, testear el vencimiento pasa a ser insertar una fila con `expires_at` en
  el pasado, que es más simple que parchear un reloj.
- **`revoked_at` se conserva** en vez de borrar la fila en el logout. Hace el logout
  idempotente y deja rastro de auditoría, que es barato y se justifica con lo que está en
  juego después de la delegación. Las dos variantes necesitan igual una limpieza periódica
  de filas vencidas.
- **Cookie `httpOnly` + `Secure` + `SameSite=Lax`.**
- **`SESSION_LIFETIME` y el nombre de la cookie son constantes de módulo leídas adentro de
  la función**, no `Settings` — mismo criterio que `MAX_UPLOAD_BYTES` del endpoint de
  importación, y por la misma razón: `Settings` es sobre la base de datos, y un global
  resuelto en tiempo de llamada es lo que deja parchearlo desde un test.
- **`User.sessions` va con `cascade="all, delete-orphan"` + `passive_deletes=True`**, no con
  el `passive_deletes="all"` de `Customer.invoice_templates`. No son variantes de lo mismo:
  `"all"` significa "no toques los hijos, ni les pongas la FK en NULL", y existe para que
  Postgres tire la violación de FK que el CRUD convierte en `CustomerInUseError` — borrar un
  cliente con modelos *tiene* que fallar. Las sesiones quieren lo contrario. Y sin
  `passive_deletes=True`, el cascade del ORM carga cada sesión en memoria y las borra de a
  una en vez de dejar que el `ON DELETE CASCADE` lo haga en una sentencia. Verificado: el
  borrado de un usuario con tres sesiones emite un solo `DELETE FROM users`.

### Dónde vive cada cosa
| Archivo | Rol |
|---|---|
| `schemas/auth.py` | Contrato de entrada/salida |
| `services/security.py` | Hash argon2 (pwdlib), tokens (`secrets`), hash SHA-256 del token |
| `crud/user.py`, `crud/user_session.py` | Acceso a datos |
| `dependencies.py` | `SessionDep`, `get_current_session`, `get_current_user` |
| `crud/email_confirmation.py`, `crud/password_reset.py` | Tokens de confirmación y de reset |
| `services/email.py`, `services/notifications.py` | Transporte SMTP y textos de los mails |
| `services/rate_limit.py` | Contador de ventana fija en memoria |
| `routers/auth.py` | `login`, `logout`, `/me`, `register`, `confirm`, `resend-confirmation`, `forgot-password`, `reset-password` |

- **El login recibe JSON, no `OAuth2PasswordRequestForm`.** El form de FastAPI es lo que usa
  casi todo tutorial, pero es `x-www-form-urlencoded` y su campo se llama `username`. El
  backend habla solo JSON, así que es un modelo Pydantic con `email` y `password`.
- **La normalización del email va en el schema**, con el mismo `field_validator` que hace
  `.strip().lower()` que ya tiene `CustomerCreate`. Sin eso `Miguel@x.com` y `miguel@x.com`
  son dos cuentas y el `unique=True` no lo impide.
- **`get_current_user` va en `dependencies.py` y no en `routers/auth.py`**, para que
  `routers/customer.py` no termine importando de un router hermano sin ninguna razón
  estructural. Es también el lugar donde `SessionDep` deja de estar copiado en cada router.

### Capa HTTP (2026-08-26)
- **Son dos dependencias, no una.** `get_current_session` resuelve la cookie a la fila viva
  de `user_sessions`; `get_current_user` depende de ella y devuelve `user_session.user`. El
  logout necesita la *fila* para revocarla, y sin el escalón intermedio tendría que releer
  la cookie y rehashearla a mano.
- **El logout depende de la sesión y no del usuario.** Un usuario dado de baja mientras
  tenía la sesión abierta igual tiene que poder cerrarla; exigir `get_current_user` ahí lo
  dejaría con una sesión viva que no puede revocar. Responde **204** y borra la cookie con
  `delete_cookie`, que es un `Set-Cookie` vacío con `Max-Age=0`.
- **`is_active` y `email_confirmed_at` se revalidan en cada request**, no solo en el login.
  La sesión dura una semana: una baja tiene que pegar en el request siguiente, no cuando
  venza el token. El `joinedload(UserSession.user)` del CRUD ya trajo la fila, así que no
  cuesta una query extra.
- **Las cinco causas de 401 comparten un solo `detail`** (sin cookie, token desconocido,
  vencido, revocado, usuario inhabilitado). Distinguirlas le diría a un atacante qué parte
  de su intento estuvo cerca de funcionar.
- **La autenticación se aplica a nivel de router**, con
  `APIRouter(..., dependencies=[Depends(get_current_user)])` en `customer`,
  `fiscal_identity` e `invoice_template`. Decorar endpoint por endpoint es la misma regla
  escrita quince veces y falla por omisión: el que se olvide queda público sin que nada lo
  marque. `health` queda afuera a propósito — lo consulta el orquestador, que no tiene
  sesión.
- **Excepción al "constante leída adentro de la función":** `SESSION_LIFETIME` sí se lee en
  tiempo de llamada, pero `SESSION_COOKIE_NAME` viaja como `Cookie(alias=...)` en la firma
  de la dependencia, así que se resuelve al importar. Es el precio de que el parámetro
  aparezca en el OpenAPI en vez de leer `request.cookies` a mano; a cambio, un test que
  quiera cambiar el nombre de la cookie tiene que importarlo, no parchearlo.
- **`SESSION_LIFETIME` = 7 días.** Vencimiento absoluto, no deslizante.

### Tests de autenticación
- **El fixture `client` queda autenticado por defecto; el anónimo es `anonymous_client`.**
  Al revés habría que editar los 61 tests de router que ya existen, y cada test nuevo
  tendría que acordarse de elegir — y olvidarse da un 401 pelado en vez de una falla clara.
- **Autentica con una cookie real sobre una fila real de `user_sessions`**, no
  sobreescribiendo `get_current_user`. Así los 61 tests ejercitan la dependencia de verdad
  sin costo, y sobre todo el *ownership scoping* de la unidad siguiente va a tener un
  `users.id` real del cual colgar `fiscal_identities.user_id`. Con la dependencia falseada,
  esa unidad sería reescribir los 61 tests.
- **El fixture no se loguea por HTTP.** Los parámetros recomendados de argon2 (m=64 MiB,
  t=3, p=4) cuestan ~50–100 ms por verificación; por 61 tests, más el hash de cada usuario,
  duplica una suite de 8 segundos. La fila de sesión se inserta directo y la cookie se pone
  a mano; el endpoint de login lo ejercitan sus propios tests, que es donde ese costo
  corresponde. Por lo mismo, `make_user` reparte una constante hasheada una sola vez, y solo
  los tests que verifican contraseñas pagan un hash real.
- **`TestClient(app, base_url="https://testserver")`.** La cookie es `Secure` y el cookie
  jar de Python se niega a mandarla sobre http: sin esto la cookie se setea, nunca vuelve, y
  todos los tests dan 401 por un motivo que no se parece en nada a la causa. Los navegadores
  no tienen el problema en dev — tratan `http://localhost` como contexto seguro.
- **La cookie se inyecta por el constructor** (`TestClient(..., cookies={...})`) y no con
  `jar.set()`. Consecuencia a tener presente: esa cookie queda sin dominio y el `Set-Cookie`
  del logout llega con el dominio del request, así que en el jar conviven dos entradas y
  `cookies.get()` sigue devolviendo la vieja. Por eso el test del logout mira el header
  `Set-Cookie`, que es lo que el navegador lee de verdad, y la prueba de que la sesión
  murió es el `GET /auth/me` que sigue.
- **El fixture `user` es el dueño de la sesión de `client`** — activo y confirmado. Está
  expuesto aparte para que un test pueda afirmar sobre la fila (por ejemplo, que el logout
  le puso `revoked_at`).

### Registro y confirmación por email (2026-08-26)
`POST /auth/register`, `POST /auth/confirm` y `POST /auth/resend-confirmation`, con la tabla
`email_confirmations` (migración `10a07c64dfce`) y el envío por SMTP.

- **El registro contesta siempre 202 con el mismo body**, exista o no la dirección. Un 409
  por duplicado sería el oráculo de enumeración que el login evita con tanto cuidado. El
  texto es afirmativo y no condicional ("Te mandamos un mail a esa dirección") porque las
  tres ramas mandan algo: dirección nueva y dirección sin confirmar reciben el link, y
  dirección ya confirmada recibe un aviso de que la cuenta existe. Ese aviso es lo único
  que puede contar qué pasó, y llega a la casilla del dueño, que es quien tiene derecho a
  saberlo.
- **La contraseña se hashea antes del lookup**, aunque en dos de las tres ramas el hash se
  tire. Argon2 es lo más caro del endpoint: hashear solo al crear haría que una dirección
  ya registrada conteste notoriamente más rápido, y el cuerpo idéntico no serviría de nada.
  Es el hash dummy del login, con el desperdicio del lado contrario.
- **Registrarse sobre una dirección sin confirmar emite un token nuevo pero no toca la
  contraseña.** Pisarla es una toma de cuenta completa: al atacante le alcanza con
  registrarse encima de una cuenta pendiente y esperar a que el dueño real —que justamente
  estaba esperando un mail— haga clic en el link que le llegue. Quien se equivocó de
  contraseña al registrarse necesita el reset, que es otra unidad.
- **`email_confirmations` es tabla y no dos columnas en `users`**, porque el reenvío emite
  un token nuevo sin invalidar el anterior. Con columnas, cada reenvío pisaría el token del
  mail que el usuario quizás ya tiene abierto y el link viejo moriría sin explicación. Y no
  invalidar el anterior tampoco cuesta nada: cada token es de un solo uso, vence solo, y
  los dos apuntan al mismo usuario.
- **La confirmación no abre sesión.** Sería mejor UX, pero el token vivió 24 horas en una
  casilla de mail: convertirlo en cookie dejaría logueado a cualquiera con acceso a ese
  mensaje. Pedir la contraseña una vez después de confirmar cuesta una pantalla.
- **Token desconocido, vencido, ya usado y de un usuario dado de baja dan el mismo 400.** No
  hay nada que enumerar —son 256 bits— pero el remedio de los cuatro es idéntico y el texto
  lo dice: "pedí uno nuevo". El CRUD ya los colapsa en un `None`, así que el endpoint no
  tiene rama que pueda distinguirlos por descuido.
- **El mail con las instrucciones de delegación sale al confirmar, no al registrarse**, y
  solo la primera vez. Antes de confirmar no hay ninguna prueba de que la casilla sea de
  quien dice, y ese mail termina con alguien entrando a ARCA con su Clave Fiscal.
- **`CONFIRMATION_LIFETIME` = 24 h**, y el `PASSWORD_MIN_LENGTH` = 10 vive en el schema. Sin
  reglas de composición: empujan a `Password1!` y NIST las desaconseja desde 2017. El techo
  de 128 no es política sino defensa — sin él, una contraseña de megabytes le hace quemar
  CPU a argon2 gratis. `LoginRequest` **no** lleva el mínimo: un 422 por "muy corta" le
  diría al atacante que su intento no llegó ni a compararse.

#### El `commit` explícito antes de mandar el mail
Sin un `commit` explícito en el endpoint, la transacción queda abierta durante toda la
conexión SMTP, hasta `SMTP_TIMEOUT_SECONDS`: diez segundos de transacción abierta por
registro. Por eso el router commitea, contra la convención del proyecto de que eso es trabajo
de `get_db`. El segundo commit de `get_db` no tiene nada que escribir, y en los tests el
`join_transaction_mode="create_savepoint"` del fixture `db` hace que este commit cierre un
savepoint y el rollback siga revirtiendo todo. El test que lo protege mira el **orden** y no
el resultado, que es lo único que distingue este caso: ningún otro test nota que la línea
falte.

Hasta el 2026-08-27 había un segundo motivo, hoy histórico: **en FastAPI 0.141 los background
tasks corren antes del cierre de las dependencias con `yield`** —medido, no supuesto— así que
el mail salía con un token que todavía no estaba en la base, y una transacción abortada le
dejaba al usuario un link que no iba a funcionar nunca. Dejó de aplicar cuando el mail de
confirmación pasó a mandarse adentro del request (ver *El fallo de SMTP se ve*), pero el orden
que exigía es el mismo: primero se guarda el token, después sale el link que lo nombra. Sigue
valiendo tal cual para los mails que **sí** quedaron en background.

#### Mail: dónde vive cada cosa
| Archivo | Rol |
|---|---|
| `services/email.py` | Transporte: `EmailSettings`, SMTP, STARTTLS, timeout, `send_email` / `send_email_best_effort` |
| `services/notifications.py` | Contenido: asunto y cuerpo de los seis mails, y cuál de los dos transportes usa cada uno |

Separados porque cambian por motivos distintos: cambiar de proveedor no toca una palabra de
los textos, y corregir la redacción de un mail no debería obligar a leer código de sockets.

- **`EmailSettings` es un `BaseSettings` propio, no un campo más de `Settings`.** El de
  `database.py` es sobre la base; meterle el servidor de mail lo vuelve un cajón de sastre.
- **Los dos llevan `extra="ignore"`, y eso no es cosmético.** pydantic-settings prohíbe los
  extras por default y el `.env` es uno solo para toda la app: sin esto, agregar `SMTP_HOST`
  al `.env` hacía fallar la construcción de `Settings`, que ocurre **al importar
  `database.py`**. O sea que la app entera y la suite completa se caían por una variable que
  ese objeto nunca iba a mirar.
- **`EmailSettings` se construye adentro de `send_email`**, con `lru_cache`. Instanciarla en
  el módulo haría que un `.env` sin `SMTP_HOST` rompiera el import de todo el paquete por no
  poder mandar un mail que nadie pidió.
- **`notifications.py` importa el módulo `email`, no la función `send_email`.** Así el
  nombre se resuelve en cada llamada y un test puede parchear el transporte en un solo
  lugar — el mismo criterio que `MAX_UPLOAD_BYTES`. Con `from ... import send_email` el
  parche no llegaría nunca.
- **El CUIT que nombra el mail de delegación sale de `arca.get_delegate_tax_id()`**, no de
  `EmailSettings`. Hasta el 2026-08-26 era un campo de esta clase con un placeholder por
  default, porque se creía que el certificado no existía. Existe: es `20182810674`, el mismo
  con el que Balance360 ya emite. Ver *ARCA → El CUIT de FactuMov*.

#### `generate_opaque_token` / `hash_opaque_token`
Antes se llamaban `*_session_token`. La mecánica es la misma para la sesión y para la
confirmación —256 bits de `secrets`, guardados como SHA-256— y el nombre no tenía nada de la
sesión adentro. Un segundo par idéntico con otro nombre habría sido peor que el rename.

#### Tests
- **Dos fixtures autouse en `conftest.py`.** `sent_emails` parchea el transporte y devuelve
  lo que se mandó; es autouse porque un test que se olvidara de pedirlo abriría un socket
  SMTP de verdad y fallaría con un timeout de diez segundos sin relación aparente con lo que
  estaba probando. Parchea `email.send_email` y no las funciones de `notifications`, así los
  asuntos, los cuerpos y la URL se siguen armando de verdad.
- **`email_settings` desengancha el `.env`** (`monkeypatch.setitem(..., "env_file", None)`)
  además de fijar las variables. Las variables de entorno pisan al `.env`, así que fijarlas
  alcanzaría para las que el fixture usa; el problema son las que un test necesita
  *ausentes*. Sin esto, un `SMTP_USER` real en el `.env` de alguien rompe el test de "no hace
  login sin credenciales" en su máquina y en ninguna otra.
- **El token se saca del link del mail, no de la tabla.** Leer el `token_hash` probaría que
  el CRUD guardó algo; sacarlo del cuerpo del mail y postearlo prueba que el link que llega a
  la casilla abre la cuenta, que es lo que puede romperse en el medio.

### Rate limiting (2026-08-26)
Cierra el registro: CLAUDE.md ya decía que el rate limiting está en el camino crítico del
self-serve, no que es opcional. `services/rate_limit.py`, aplicado a `login`, `register` y
`resend-confirmation`.

- **Es un piso, no el techo.** El estado vive en memoria del proceso: con N workers el
  límite efectivo es N veces el configurado. El techo real va en el borde (`limit_req` de
  nginx), igual que con `MAX_UPLOAD_BYTES`. Lo que esta capa agrega es lo que el borde **no
  puede** hacer: limitar por dirección de email, que está en el body y nginx no lee.
- **Sin dependencia nueva.** `slowapi` da backends de Redis y headers estándar, pero acá
  alcanzan un contador y un candado. El día que haya que compartir el estado entre workers
  lo que se necesita es Redis, no un wrapper.
- **Ventana fija, no deslizante.** La fija admite una ráfaga de hasta 2× justo en el borde
  entre ventanas; la deslizante lo evita guardando el timestamp de cada intento en vez de un
  contador. Para lo que se defiende —mail bombing y credential stuffing— esa ráfaga da lo
  mismo, y un contador por clave es lo que mantiene la memoria acotada.
- **Seis limitadores, dos ejes.** Por IP: login 10 cada 15 min; registro, reenvío y
  "olvidé mi contraseña" 5 por hora; `reset-password` 10 por hora. Por dirección: 3 por hora,
  **compartidos entre los tres endpoints que mandan mail a la dirección del body**, porque
  presupuestos separados dejarían triplicar el bombardeo alternando entre ellos. El login es
  el más holgado a propósito: el que se equivoca de contraseña de verdad reintenta varias
  veces seguidas.
- **`reset-password` no comparte el presupuesto de casilla**, porque no manda ningún mail al
  pedido: su límite existe por otra cosa. Es el único endpoint sin sesión que hashea con
  argon2, o sea que quema ~100 ms de CPU por request. El 422 por contraseña corta ni siquiera
  llega al endpoint —lo corta Pydantic antes— así que diez por hora no le estorba a nadie que
  esté tipeando de verdad.
- **El contador avanza antes de mirar la base.** Si solo avanzara para direcciones que
  existen, el 429 llegaría antes para las registradas y sería el oráculo de enumeración que
  el 202 se cuida de no ser.
- **La clave sale de `request.client`, no del header `X-Forwarded-For`.** Detrás de un proxy
  es uvicorn (`--proxy-headers`, `--forwarded-allow-ips`) el que reescribe `request.client`
  a partir de ese header, y solo si el que se conectó es un proxy de confianza. Leerlo acá
  saltearía esa decisión, y un header que cualquiera inventa vuelve al limitador un adorno:
  uno distinto por request y no hay límite; el de otro y lo dejás afuera a él.
- **`clock` es un parámetro del `RateLimiter`.** Parchear `time.monotonic` en el test lo
  cambiaría para todo el proceso, pytest incluido. Es `monotonic` y no `time` para que
  corregirle la hora al server no abra la ventana antes de tiempo.
- **Hay candado.** Los endpoints son `def`, así que FastAPI los corre en el threadpool: sin
  el `Lock`, dos requests leen el mismo contador y uno pisa el `+= 1` del otro, o sea que el
  límite se afloja justo bajo la carga que tendría que frenar. Hay un test con ocho hilos.
- **`reset_rate_limiters` es autouse en `conftest.py`.** Los limitadores son globales de
  módulo y el TestClient se presenta siempre con la misma IP: sin el reset, el sexto test
  que registra algo empieza a comer 429, y el que falla no es el que rompió nada sino el que
  quedó sexto, que cambia con el orden de colección.
- **Los limitadores se registran solos** (`rate_limit.reset_all()`), desde la unidad de ARCA.
  Antes era una tupla `ALL_LIMITERS` escrita a mano en `routers/auth.py`, y un limitador
  nuevo en otro router —los dos de ARCA— tenía que acordarse de sumarse a esa lista.
  Olvidarse reintroduce exactamente el bleed entre tests que el fixture existe para evitar,
  y el síntoma no señala la causa.
- **`client_key` y `enforce_rate_limit` viven en `dependencies.py`**, no en `routers/auth.py`.
  Se mudaron cuando los endpoints de ARCA empezaron a limitar: la alternativa era que
  `routers/customer.py` importara de un router hermano, que es el mismo motivo por el que
  `get_current_user` nunca estuvo en `routers/auth.py`.
- **Los tests leen los límites de los propios limitadores** en vez de repetir los números.
  Si el registro pasa de 5 a 10 por hora, tienen que seguir probando el límite y no fallar
  por saberse uno viejo de memoria. Aparte hay un test que fija el piso —ningún límite baja
  de 3 por hora— para que apretarlos hasta que estorben lo diga la suite antes que un
  usuario.

### El fallo de SMTP se ve (2026-08-27)
Hasta acá, `send_email` se tragaba el `OSError` y dejaba una línea de log, y **todos** los
mails salían en un `BackgroundTasks`. Las dos decisiones eran defendibles por separado y
juntas produjeron el peor resultado posible: con el `.env` apuntando al puerto 465 —que el
transporte no sabe hablar— el registro contestó **202 durante días** y el mail no salió
nunca. La respuesta afirmaba algo que el sistema no había hecho.

Son dos cambios, y son distintos a propósito: uno avisa temprano, el otro avisa tarde pero
seguro.

**1. La config que no puede funcionar se rechaza al leerla.** Un `model_validator` en
`EmailSettings` corta dos combinaciones:

| Config | Por qué no anda | Cómo fallaba antes |
|---|---|---|
| `SMTP_PORT=465` | TLS implícito necesita `smtplib.SMTP_SSL`; este transporte abre siempre texto plano | Timeout de 10 s adentro del envío |
| `SMTP_USER` sin `SMTP_PASSWORD` (o al revés) | `send_email` saltea el login sin decir nada | El relay rechaza el envío al final |

Las dos comparten lo que las hacía caras: fallaban lejos de su causa y ninguna nombraba al
`.env`, que es lo único que había que tocar. La pregunta "¿esto puede andar?" se contesta sin
red, así que se contesta antes de intentar nada.

- **El aviso sale al arrancar, en el `lifespan` de `main.py`, y no aborta el arranque.** El
  mail hace falta en tres endpoints; emitir, editar modelos y consultar el padrón andan sin
  él. Tirar abajo la app entera por una variable que solo miran esos tres es el mismo error
  que `EmailSettings` evita al no instanciarse en el import del módulo. Lo que cambia es
  *cuándo* se entera alguien: antes era un usuario real sin su mail, ahora es un renglón en
  la consola con el `.env` a mano.
- El logger no tiene handler propio y no hace falta: uvicorn configura los suyos y no toca el
  root, así que esto sale por `logging.lastResort`, que imprime a stderr de WARNING para
  arriba.

**2. El mail que es el producto del request se manda adentro del request.** `send_email`
levanta `EmailDeliveryError` en vez de tragarse el error, y `_deliver` del router lo convierte
en **503**. Los cuatro endpoints que existen para mandar un mail —`register`,
`resend-confirmation`, `forgot-password` y las dos ramas de este último— contestan que no
salió en vez de un 202 alegre.

- **El costo es latencia y se paga barato.** Hasta `SMTP_TIMEOUT_SECONDS` en el peor caso,
  ~1-2 s con Gmail en el normal, y solo en operaciones que un usuario hace una vez —no en la
  pantalla que abre cien veces por semana—. A cambio, la respuesta dice la verdad.
- **`send_email_best_effort` es para los mails que solo acompañan**: las instrucciones de
  delegación después de confirmar, el aviso de que la contraseña cambió. Esos salen después
  de algo que **ya quedó guardado**, así que un 503 mandaría al usuario a reintentar con un
  token consumido — o sea a un 400 sobre una cuenta que en realidad sí quedó confirmada.
  Siguen en `BackgroundTasks` y solo loguean. La distinción es de **rol**, no de importancia.
- **Que las tres ramas del registro manden un mail dejó de ser una simetría linda y pasó a
  ser estructural.** Si alguna no mandara nada, nunca podría fallar, y un 503 pasaría a
  significar "tu dirección cae en las otras dos ramas". La propiedad anti-enumeración no la
  sostiene solo el cuerpo idéntico: la sostiene que las ramas hagan lo mismo. Es el mismo
  argumento que obliga a `forgot-password` a mandarle algo a una dirección desconocida.
- **`resend-confirmation` es la excepción, y se acepta.** Ahí una rama no manda nada —para
  una dirección confirmada o inexistente no hay ningún mail que mandar— así que su 503
  distingue una rama de la otra. Lo que revela es "esa dirección está registrada **y sin
  confirmar**", un estado transitorio de horas, y la alternativa sería mandarle mail a
  direcciones que no pidieron nada, o sea el mail bomb del que hay que defenderse.
- **Un 503 en el registro llega con la fila del usuario ya commiteada, y está bien.** La
  cuenta queda sin confirmar, o sea inservible, y el reintento cae en la rama de "dirección
  sin confirmar" y emite un token nuevo.
- **El detalle no viaja en la respuesta.** El texto del 503 dice que es un problema nuestro y
  no de la cuenta, y que se reintente. Nombrar el servidor o la variable que falta contaría
  cómo está armado nuestro lado y no le sirve a nadie del otro.

### Reset de contraseña (2026-08-27)
`POST /auth/forgot-password` y `POST /auth/reset-password`, con la tabla `password_resets`
(migración `7c41ab90d5e2`) y las pantallas `/olvide-password` y `/restablecer-password`.

Era la primera de las unidades pendientes y la pedía el propio registro: **quien se equivocó
de contraseña al registrarse no tenía ninguna salida.** El segundo registro no pisa la
contraseña —a propósito, porque pisarla es una toma de cuenta— así que la cuenta quedaba con
una contraseña que nadie sabe y una dirección que nadie puede volver a usar.

- **`password_resets` es la tercera tabla con la misma forma** que `user_sessions` y
  `email_confirmations`: token opaco de `secrets` guardado como SHA-256 en `String(64)` con
  `unique=True`, vencimiento absoluto en la columna, marca de consumo en vez de borrar la
  fila. Que se repita es la decisión: una tabla genérica de "tokens" con una columna `kind`
  las obligaría a compartir vencimiento, índices y reglas de limpieza, que es justo lo que no
  comparten. La columna se llama `used_at` y no `confirmed_at` porque acá no se confirma
  nada, se consume un permiso.
- **Vive una hora, no 24.** No es una simetría rota con la confirmación: es que lo que está
  en juego es distinto. Un token de confirmación vencido cuesta un reenvío; uno de reset vivo
  es la cuenta entera para cualquiera que llegue a esa casilla. El usuario acaba de pedirlo y
  lo va a usar en el minuto siguiente.
- **Funciona sobre una cuenta sin confirmar**, que es el caso que motivó la unidad. Exigir
  estar confirmado dejaría abierto exactamente el callejón sin salida que vino a cerrar.
- **Usar el link confirma la dirección.** Haberlo abierto prueba lo mismo que prueba el link
  de confirmación: que quien lo abrió tiene la casilla. Sin esto la salida sería falsa —el
  usuario cambia la contraseña y sigue sin poder entrar, con el mismo 401 de siempre y sin
  nada que se lo explique—. Y como la confirmación es lo que dispara el mail de instrucciones
  de delegación, ese mail sale acá también la primera vez, para que el invariante
  "confirmado ⇒ recibió las instrucciones" no dependa de por qué puerta se confirmó.
- **Cierra todas las sesiones** (`user_session.revoke_all_for_user`). Quien resetea porque
  sospecha que alguien le entró tiene que quedarse solo adentro; sin esto la sesión ajena
  sigue viva hasta una semana y el cambio de contraseña no la toca.
- **Usar un link mata los demás** (`password_reset.invalidate_all_for_user`), y ahí está la
  diferencia de fondo con la confirmación de email. Dos links de confirmación vivos son
  inofensivos: los dos hacen lo mismo y lo que hacen ya está hecho. Dos links de reset vivos
  son dos oportunidades de cambiar la contraseña, y la segunda le queda a quien pidió la
  primera. Lo que **sí** se conserva de la confirmación es que pedirlo de nuevo no rompe el
  mail anterior: el que no encuentra el primero pide otro, y castigarlo por buscar mal sería
  dejarlo con dos links muertos.
- **No abre sesión**, por lo mismo que la confirmación no la abre: el token vivió en una
  casilla de mail y convertirlo en cookie dejaría adentro a cualquiera con acceso a ese
  mensaje.
- **Una dirección sin cuenta usable también recibe un mail**, y no es una cortesía: es lo que
  hace que las dos ramas puedan fallar igual. Si esa rama no mandara nada nunca podría dar
  503, y el 503 pasaría a significar "esa dirección existe" — ver *El fallo de SMTP se ve*.
  El texto **no dice "no existe"**: una cuenta dada de baja cae en la misma rama, y afirmarlo
  sería mentirle a su dueño.
- **El aviso de "tu contraseña cambió" es best effort y sale igual.** Es la única señal que
  le llega al dueño de la casilla si el reset lo pidió otro, y llega a un lugar al que ese
  otro ya no puede volver: el link se consumió y las sesiones se cerraron todas.
- **El hash de argon2 se calcula después de validar el token**, al revés que en el registro.
  Allá el costo se paga siempre para que el tiempo de respuesta no delate si la dirección
  existía; acá no hay nada que ocultar —el 200 y el 400 ya dicen si el token servía— y
  hashear antes le regalaría 100 ms de CPU a cualquiera que postee un token inventado.
- **Token desconocido, vencido, ya usado y de un usuario dado de baja dan el mismo 400**,
  mismo criterio que la confirmación: el remedio de los cuatro es pedir uno nuevo, y el CRUD
  ya los colapsa en un `None` para que el endpoint no pueda distinguirlos por descuido.
- **`ResetPasswordRequest` lleva el mínimo de largo y `LoginRequest` no.** Acá se *elige* una
  contraseña, así que la política del alta aplica igual. En el login no se elige nada, y un
  422 por "muy corta" le diría al atacante que su intento ni llegó a compararse.
- **La pantalla no postea sola al montar**, a diferencia de `ConfirmEmailPage`: falta un dato
  que solo puede dar el usuario. Efecto secundario feliz: el token de un solo uso no se quema
  por abrir el link, así que no hace falta el `useRef` de guarda contra el doble montaje de
  StrictMode.
- **El link "Olvidé mi contraseña" va abajo del formulario de login**, no al lado del campo.
  Quien lo necesita ya falló una vez y mira ahí abajo después del cartel rojo; arriba
  competiría con el botón de entrar, que es lo que se aprieta el 99% de las veces.

### Unidades pendientes, en orden
Cerradas el 2026-08-26: la capa HTTP de autenticación (login, logout, `/me`,
`dependencies.py` y los tres routers protegidos), el *ownership scoping*, el registro con
confirmación por email con su rate limiting, la **integración con ARCA** (verificación de
delegación + consulta al padrón) y el **frontend**, incluida la grilla de modelos con su
editor e importación de PDF — ver *ARCA* y *Frontend*.

Cerradas el 2026-08-27: el **reset de contraseña**, la **visibilidad del fallo de SMTP**, la
**emisión con CAE** y el **envío de la factura por email** — ver las secciones respectivas.
**Con eso las cinco funcionalidades core están hechas** y el circuito cierra de punta a punta:
importar un PDF, editar el modelo, guardarlo, emitir con CAE y mandarlo.

Lo que sigue ya no es funcionalidad: es **salir a la cancha**. Las tres se pidieron el
2026-08-27 y van en ese orden por dependencia, no por importancia — ver *Marca, landing y
producción*. La primera está cerrada; quedan las otras dos.

Cerrada el 2026-08-27: la **marca** — el ícono propio, el acento verde, los íconos de la PWA
con su manifest y el logo de InSoft en las pantallas sin sesión.

1. **Producción** — la app corriendo en la VM detrás de `srv-nginx`, con su dominio propio.
   Es lo que la landing va a linkear, así que va antes que ella.
2. **FactuMov en la landing de InSoft** — tarjeta en *Nuestros SaaS* y entrada en el
   lanzador de apps, apuntando a la URL del punto anterior. Los assets de la tarjeta ya
   existen: `frontend/public/factumov-icon.svg` y los PNG de al lado.
3. **Segundo layout del parser** — ver *Parser → Pendiente: un segundo layout*. No bloquea
   nada: hoy el usuario puede cargar el modelo a mano.
4. **WhatsApp**, la otra mitad de la funcionalidad #5. Sin empezar y sin decisión tomada
   sobre qué proveedor.

Y dos cosas que la emisión dejó anotadas y no son unidades todavía:

- **Los valores de `CondicionIva` de Balance360 están mal** — ver *Emisión con CAE → Dos
  códigos heredados*. Acá se corrigieron; allá pueden estar declarando la condición
  equivocada del receptor en cada factura. Sin revisar.
- **Ninguna pantalla usa `/invoices` para reemitir el mes siguiente.** Hoy se vuelve al
  modelo, que es correcto, pero "emitir igual que el mes pasado" es el gesto que más se va a
  repetir.

## ARCA (2026-08-26)
Port adaptado de `arca.py`, `padron.py` y la mitad de consulta de `wsfe.py` de Balance360.
Cierra la verificación de la delegación y agrega la carga de un cliente desde el padrón.
Migración `8f1c4b2e5a09`. Dependencias nuevas: `zeep`, `requests`, `cryptography`.

| Archivo | Rol |
|---|---|
| `services/arca.py` | WSAA: `ArcaSettings`, TRA, firma PKCS#7, CUIT del certificado, `get_access_ticket` |
| `services/wsfe.py` | `check_delegation` sobre `FEParamGetPtosVenta` |
| `services/padron.py` | `get_taxpayer` sobre `getPersona_v2` |
| `crud/arca_ticket.py` | Lectura y upsert del TA, con el advisory lock |
| `models/arca_ticket.py` | Tabla `arca_tickets` |

### El certificado es uno solo, de FactuMov
El usuario **no** sube su certificado: entra a ARCA y **delega** WSFE al CUIT de FactuMov.
De ahí salen casi todas las decisiones de abajo.

- **El `Auth.Cuit` de WSFE es el CUIT representado, no el del certificado.** En Balance360
  coinciden —el certificado es del propio contribuyente—, así que ese código se lee igual y
  significa otra cosa. Esa brecha *es* la delegación: con un mismo ticket, ARCA acepta unos
  CUIT y rechaza otros.
- **El padrón es la excepción y por eso no necesita delegación.** Ahí el `cuitRepresentada`
  somos nosotros, así que la consulta funciona desde el día uno. Lo que hace falta es que
  ARCA nos tenga habilitado el servicio `ws_sr_constancia_inscripcion` **al certificado**
  (Administrador de Relaciones en prod, WSASS en homologación); sin eso el que falla es
  WSAA, con "Computador no autorizado a acceder al servicio", y no se llega a la consulta.
- **`ArcaSettings` es un `BaseSettings` propio con `extra="ignore"`, construido adentro de
  las funciones con `lru_cache`** — mismo patrón, y mismas dos razones, que `EmailSettings`.
- **`ARCA_ENV` default `"homo"`.** Si la variable falta, la app pega contra el ARCA de
  pruebas. Equivocarse hacia homologación es gratis; al revés no.

### El CUIT de FactuMov es `20182810674`
Es el mismo con el que **Balance360 ya emite** —para sí mismo y para quienes le delegaron—,
y ya tiene los servicios y los certificados dados de alta en ARCA. O sea que el certificado
no es un pendiente: existe, funciona y está probado en producción contra CUIT de terceros.

Esto corrige la nota que decía "el certificado todavía no existe, default placeholder". Era
de cuando se escribió el mail de delegación, antes de mirar Balance360.

- **`get_delegate_tax_id()` es la única función que contesta "a quién hay que autorizar".**
  La usan el mail de instrucciones y el `delegate_tax_id` de la respuesta de verificación.
  Antes eran dos lugares con dos fuentes distintas, que es exactamente cómo se llega a que el
  mail diga un CUIT y el sistema espere otro.
- **El certificado manda; `ARCA_DELEGATE_TAX_ID` es el fallback.** El certificado es lo que
  ARCA ve del otro lado, así que no puede mentir; la variable es algo que alguien tecleó.
  Cuando los dos están y discrepan, gana el certificado. La variable contesta cuando no hay
  certificado en esa máquina — un worker que solo manda mails.
- **`arca_delegate_tax_id` se mudó de `EmailSettings` a `ArcaSettings`.** Es un dato de ARCA
  que el mail *usa*; estaba en el otro lado solo porque el mail fue su primer consumidor y
  `ArcaSettings` no existía.
- **El default es el CUIT real y no un placeholder**, al revés que antes: el certificado es
  uno solo para toda la app, así que el CUIT es un hecho del proyecto y no de la instalación.
  La variable queda para el día que FactuMov saque certificado propio y haya que migrar sin
  tocar código.

### El ticket de acceso vive en una tabla
No en el `ticket_arca.json` del cwd que usa Balance360. **WSAA se niega a emitir un TA nuevo
mientras el anterior siga vigente**, así que dos workers pidiendo a la vez no obtienen dos
tickets: obtienen uno y un error, y la app queda afuera de ARCA hasta doce horas. Un archivo
en el cwd de un contenedor no coordina eso, y encima no sobrevive al deploy.

- **`arca_tickets` es la única tabla sin `user_id`.** El ticket es del certificado, no del
  contribuyente; a quién representa se decide por llamada.
- **`(env, service)` único.** Homo y prod tienen certificados distintos y tickets distintos;
  y el TA se emite **por servicio**, así que WSFE y el padrón tienen el suyo.
- **`token` y `sign` son `Text`.** Son blobs base64 de largo no documentado (~3 KB hoy) y
  ARCA no promete un techo: un `varchar(n)` corto se rompe en producción y de golpe.
- **`pg_advisory_xact_lock`, no `SELECT ... FOR UPDATE`.** La primera vez no hay fila que
  trabar, así que el FOR UPDATE no bloquea a nadie y los N workers piden un TA cada uno. El
  advisory lock traba la *clave*, exista o no la fila, y se suelta solo en el commit.
- **La clave del lock sale de un `blake2b` y no de `hash()`**, que Python aleatoriza por
  proceso: dos workers tomarían candados distintos para la misma clave.
- **Doble lectura: una sin candado y otra adentro.** La primera es el camino de casi todos
  los requests; la segunda es lo que evita que el candado sirva para serializar pedidos en
  vez de para no hacerlos.
- **Se escribe en su propia sesión, con su propio commit**, desacoplada del request. Si el
  ticket recién emitido se perdiera en un rollback, WSAA no emitiría otro por horas. La
  sesión se pide como `database.SessionLocal()` —el módulo, no el nombre importado— para que
  el test la pueda parchear, mismo criterio que `MAX_UPLOAD_BYTES`.
- **Margen de vencimiento de 5 minutos.** Un TA que vence en treinta segundos es inservible:
  la llamada que lo use tarda más que eso.

### `POST /fiscal-identities/{id}/verify-delegation`
- **La sonda es `FEParamGetPtosVenta`, no `FECompUltimoAutorizado`.** Balance360 usa la
  segunda, pero para otra cosa: necesita un punto de venta, que acá habría que adivinar, y
  contesta error cuando ese punto de venta no existe — un falso negativo justo con el usuario
  nuevo que sí nos delegó. `FEParamGetPtosVenta` no recibe parámetros, no escribe nada y
  necesita la misma delegación.
- **"No estás delegado" es un valor de retorno, no una excepción.** Es la mitad esperada de
  las respuestas. `DelegationCheck(granted, message)`; el endpoint contesta **200** en los
  dos casos. Un 4xx obligaría a la UI a distinguir "te equivocaste" de "todavía no
  autorizaste".
- **Código 600** ("No apareció CUIT en lista de relaciones") es el "no". **602** ("no hay
  datos") es un **sí**: un contribuyente delegado que todavía no dio de alta ningún punto de
  venta cae ahí, y la prueba de que la delegación está es que ARCA aceptó el `Auth` en vez de
  rechazar el token. Cualquier otro código **levanta excepción** en vez de contestar que no:
  contestar que no haría reintentar para siempre una delegación ya otorgada.
- **502 cuando no se pudo preguntar**, sin propagar el detalle de ARCA: no le dice nada al
  usuario y filtra cómo está armado nuestro lado.
- **Es POST y no GET** aunque parezca una consulta: sale a la red, tarda segundos y escribe
  `delegation_verified_at`. Un GET así lo repite solo un prefetch o un proxy.
- **`db.commit()` antes de la llamada SOAP**, para no dejar la transacción abierta durante
  decenas de segundos — misma solución que el commit explícito del registro antes del mail.
  `rollback()` no sirve: bajo el `join_transaction_mode="create_savepoint"` de los tests
  revertiría al savepoint y se llevaría puestas las filas que el test armó.
- **`delegation_verified_at` es timestamp y no booleano**, por lo mismo que
  `email_confirmed_at`: la delegación se puede revocar del lado de ARCA sin avisarnos, así
  que la columna dice "esto era verdad en esta fecha", no "esto es verdad". Desde el
  2026-08-27 eso tiene consecuencias y no es solo una advertencia — ver *Delegar tiene dos
  partes*.

### `GET /customers/lookup/{tax_id}`
- **No escribe nada.** Igual que `POST /invoice-templates/import`, devuelve una propuesta que
  el usuario confirma en el editor. Dar de alta acá convertiría una consulta en un efecto
  secundario, y consultar dos veces el mismo CUIT dejaría dos clientes.
- **El CUIT va en el path** y no en un query param sobre `/customers/lookup` a secas, que
  colisionaría con `GET /{customer_id}` y daría un 422 por UUID inválido.
- **404 si el padrón no tiene ese CUIT; 502 si no se pudo preguntar.** Por eso `PadronError`
  **no** baja de `ArcaError`: no es que ARCA falló, es que la pregunta no tiene respuesta.
  ARCA lo dice de dos formas —un Fault y una respuesta con `datosGenerales` vacío— y las dos
  terminan igual.
- **La condición IVA se deduce, no viene.** El monotributo llega en su propio bloque y se
  mira **antes** que la lista de impuestos, porque un monotributista puede traer también el
  30. Después, `idImpuesto` 30 → INSCRIPTO, 32 → EXENTO, y nada de eso → FINAL.
- **Se usa el A5 (`ws_sr_constancia_inscripcion`) y no el A13**, que devuelve razón social y
  domicilio pero no los impuestos: sin ellos no se puede deducir la condición frente al IVA,
  que es justo el dato que el editor no puede adivinar.
- **`TaxpayerLookup` no usa `from_attributes`.** El servicio llama `tax_id` a lo que el
  schema llama `doc_number`, y cada vocabulario es el correcto de su lado —"contribuyente" en
  ARCA, "cliente" en FactuMov—. El router traduce, que son cuatro líneas.
- **Los dos endpoints están rate-limited por usuario y no por IP.** Están autenticados, así
  que hay una clave mejor que la dirección; y sobre todo la cuota la fija ARCA contra **el
  certificado**, que es uno solo para toda la app: un usuario en loop se la gasta a todos.

### Tests de ARCA
- **Nada sale a la red.** El SOAP se mockea en `arca.build_client`, que es el nivel más bajo
  con sentido: así se ejercita de verdad la lectura de la respuesta, que es donde están las
  decisiones. `arca.get_access_ticket` se parchea aparte en los tests de router porque abre
  su propia sesión contra la base real.
- **El certificado de prueba se genera, no se versiona.** Un PEM guardado en el repo vence, y
  el día que venza el que falla es un test que no tiene nada que ver; además nadie tiene que
  preguntarse si ese archivo es una credencial real. El fixture es de scope `session` porque
  una RSA de 2048 cuesta décimas de segundo — mismo criterio que `PASSWORD_HASHED`.
- **El fixture `arca_settings` es autouse y desengancha el `.env`.** Pesa más que con el
  mail: un `.env` con `ARCA_CERT_PATH` apuntando a un certificado de producción convertiría
  un test en una llamada real a ARCA. El default es **sin certificado**, así el test que se
  olvide de pedir `arca_cert` falla con un `ArcaError` explícito.
- **El test de reúso del ticket parchea `request_ticket` para que falle el test si alguien la
  llama.** Comparar solo el token dejaría pasar una implementación que sale a la red igual —
  y salir a la red de más es exactamente el bug que rompe la app por doce horas.
- **La conexión real contra homologación es una prueba manual, no un test.** Depende de un
  certificado que no está en el repo y de que ARCA esté levantado. Los certificados de
  Balance360 (`certs/homo.crt`, `certs/balance360.key`) son los de este mismo CUIT.

#### Los 502 son transitorios, y no significan "no delegado"
ARCA homologación corta conexiones cada tanto. Cuando eso pasa, `check_delegation` levanta
`ArcaError` y el endpoint contesta **502** — que no es lo mismo que el **200 con
`granted: false`** de una delegación que falta. En la pantalla los dos son un cartel, así que
es fácil confundirlos: pasó el 2026-08-26 con el CUIT `27177624441`, que sí está delegado, y
el reintento inmediato dio `granted: true`.

Dos cosas cambiaron a partir de eso:

- **Se loguea con `logger.exception`.** El docstring decía "el traceback queda en el log" y
  era mentira: nadie lo escribía. Un 502 sin log es indistinguible de otro, y el síntoma que
  ve el usuario —"no me verifica"— no deja ningún rastro atrás. Va en los dos endpoints que
  salen a ARCA.
- **El texto del 502 dice explícitamente que no es una falta de delegación**, en vez del
  genérico "reintentá más tarde".

**No hay reintento automático, y es a propósito.** Sería natural que el adapter de `requests`
reintentara los errores de conexión, pero SOAP viaja por POST y urllib3 —con razón— no
reintenta POST por defecto. Habilitarlo alcanzaría también a `loginCms`: reintentar un TRA
que en realidad funcionó le pide a WSAA un segundo TA y devuelve "El CEE ya posee un TA
valido", que es justo el error que puede dejar la app afuera de ARCA por horas. El reintento
lo hace el usuario apretando el botón otra vez.

#### Verificado contra ARCA homologación — 2026-08-26
La cadena entera anduvo de punta a punta, no solo con SOAP mockeado:

| Llamada | CUIT | Resultado |
|---|---|---|
| `check_delegation` | `20182810674` (el propio) | `granted=True` |
| `check_delegation` | `27177624441` (**un tercero**) | `granted=True` |
| `get_taxpayer` | `30500010912` | INSCRIPTO |
| `get_taxpayer` | `20000000001` | MONOTRIBUTO |
| `get_taxpayer` | `33693450239` | FINAL |
| `get_taxpayer` | `27177624441` | `PadronError` — no está en el padrón de homo |

`27177624441` es el caso que importa: es un CUIT que le delegó a Balance360 de verdad, así
que prueba la delegación de un tercero y no la propia. Es el que hay que usar cuando se
toque `wsfe.py`, porque es el único que puede fallar de una manera que el propio no.

Que ese mismo CUIT dé `PadronError` **no es un bug**: el padrón de homologación tiene
contribuyentes de prueba, no los reales. Los tres de arriba sí están, y devuelven una
condición IVA cada uno, que es lo que hace que la deducción por `idImpuesto` esté probada
contra datos de ARCA y no solo contra un `SimpleNamespace`.

## Delegar tiene dos partes, y la segunda es nuestra (2026-08-27)
Descubierto mirando `serviciosweb.afip.gob.ar/clavefiscal/adminrel/pending.aspx`: el CUIT
`27177624441` había designado a FactuMov para Facturación Electrónica y la fila decía
**Aceptada: Pendiente**, con un link "Aceptar" esperando. O sea que el trámite no termina cuando
el contribuyente confirma:

1. El **representado** entra a ARCA con su Clave Fiscal → *Administrador de Relaciones* → *Nueva
   Relación* → servicio Facturación Electrónica → representante `20182810674`.
2. **FactuMov acepta esa designación** en *Aceptación de Designación*, con la Clave Fiscal del
   `20182810674`. A mano.
3. Recién ahí WSFE habilita el CUIT.

**Hasta el paso 2, WSFE contesta exactamente lo mismo que si nadie hubiera delegado nada**: el
código 600. Esa es la raíz de todo lo que sigue.

- **El `granted=True` de `27177624441` que figura en *Verificado contra ARCA homologación* es de
  homo, y homo no ejercita el paso 2.** La tabla ya estaba rotulada así; queda anotado igual
  porque es fácil leerla como si el camino de producción estuviera probado entero.

### El estado que ARCA no publica
`fiscal_identities.delegation_claimed_at` (migración `c8a1e4f60b92`): cuándo el usuario dijo "ya
delegué" con ARCA todavía diciendo que no.

- **Es la única forma de separar dos estados que WSFE colapsa**, y no puede salir de ARCA: no
  hay ningún web service que liste las designaciones pendientes. Sale del usuario, que es el
  único que sabe si hizo su parte.
- **Sin ella la pantalla daba consejo equivocado.** A quien ya había hecho los cinco pasos y
  estaba en nuestra lista de pendientes le decía "entrá a autorizarnos" con los cinco pasos de
  nuevo: mandarlo a rehacer un trámite que hizo bien, sin contarle que la demora es nuestra.
- Timestamp y no booleano, como las otras tres del proyecto.
- **La verificación lo borra.** El aviso existía para explicar una espera que terminó, y
  dejarlo puesto haría que los tres estados de la pantalla dejaran de ser excluyentes.

### `POST /fiscal-identities/{id}/claim-delegation`
- **Verifica antes de anotar.** Entre que la pantalla cargó y que el usuario apretó pudo haber
  delegado en otra pestaña; ahí lo que corresponde es verificar y terminar, no anotar un aviso
  que le genera trabajo manual al operador para algo que ya funciona.
- **El primer aviso es el que queda.** `mark_delegation_claimed` no pisa la fecha: mide cuánto
  hace que esa persona espera, y pisarla convertiría un botón en un generador de mails.
- **Comparte el presupuesto de ARCA con `verify-delegation`**, que subió de 10 a 30 por hora
  porque ahora la pantalla verifica sola al abrir. La cuota es del certificado, o sea de todos
  los usuarios: presupuestos separados por endpoint dejarían gastar el doble alternando.
- Es un flag `claim` y no dos funciones porque es exactamente la única diferencia entre los dos
  endpoints: los dos preguntan lo mismo y difieren en qué escriben cuando la respuesta es no.

### El aviso al operador
`OPERATOR_EMAIL` en `EmailSettings`, y `notifications.send_delegation_pending_email`.

- **Es el único mail de la app que no le va a un usuario.** Aceptar la designación es un click
  con Clave Fiscal que ARCA no expone por ningún web service, así que la app no puede enterarse
  sola de que alguien la está esperando. El click del usuario es la única evidencia que va a
  existir nunca, y desperdiciarla deja al usuario esperando a que el operador mire la lista de
  pendientes de ARCA por casualidad.
- **Una sola vez por identidad**, colgado del primer aviso.
- **Opcional y sin default.** Es el único destinatario que no sale de una fila de `users`, y una
  instalación sin operador tiene que poder arrancar. Sin él, el aviso queda en el log — misma
  política que `send_email_best_effort`, un escalón antes.

### El rechequeo, en dos lugares
Nadie nos avisa cuando la delegación empieza a funcionar, así que lo único que se puede hacer es
volver a preguntar. Se pregunta en dos momentos y por dos motivos distintos:

- **Al abrir la identidad en la pantalla**, una vez por montaje (`useRef`, contra el doble
  montaje de StrictMode). Solo si no está verificada **o si la verificación tiene más de una
  semana** — repreguntar por una verificada hace días no aprende nada y gasta cuota compartida.
  Es silencioso: no lo pidió nadie, así que un ARCA caído deja la pantalla como estaba en vez de
  pintar un cartel rojo.
- **`services/delegation_watch.py`, cada 15 minutos**, sobre las que avisaron y siguen sin
  verificar. Lo que se espera es que una persona lea un mail y haga un click, o sea tiempo
  humano: 15 minutos deja la espera del usuario en unos 7 de promedio y cuesta 4 llamadas por
  hora **por identidad pendiente**, que en el caso normal son cero.

**Descartado: un link en el mail del operador para avisarle al sistema que ya aceptó.** Era la
idea original y tiene dos problemas. El primero es que un link que *afirma* "ya acepté" es una
segunda fuente de verdad capaz de mentir —aceptaste otra fila, clickeaste antes de tiempo— y el
usuario se enteraría con un rechazo al emitir. Eso se arregla haciendo que el link solo
**dispare** la verificación. Pero entonces queda el segundo: con el barrido cada 15 minutos, el
link ahorra siete minutos a cambio de un endpoint sin sesión protegido por un secreto en el
`.env`, que además los clientes de mail suelen prefetchear. No paga.

Detalles del barrido:

- **`pg_try_advisory_xact_lock`, no el bloqueante** de las otras dos veces que el proyecto usa
  este mecanismo. Si otro worker ya está barriendo, este tick no tiene trabajo: quedarse
  esperando solo acumularía barridos para dispararlos juntos cuando el candado se libere.
- **Un solo commit, al final.** No es una optimización: el candado es de transacción, así que
  commitear adentro del loop lo soltaría en la primera identidad verificada.
- **Los mails salen después del commit y fuera del candado.** Lo primero porque el mail dice que
  ya puede emitir y tiene que ser verdad cuando llega; lo segundo porque un SMTP colgado no
  puede quedarse con el candado que le impide barrer al resto.
- **Solo mira las pendientes**, no todas las identidades. Barrer las verificadas sería buscar
  revocaciones sobre filas que nadie está mirando y multiplicar por N la cuota de ARCA.
- **Deja de repreguntar después de 30 días** (`CLAIM_MAX_AGE_DAYS`). Un aviso de hace un mes que
  sigue sin verificar no se arregla preguntando cuatro veces por hora para siempre: o el usuario
  se confundió de trámite o hay algo mal de nuestro lado, y las dos cosas necesitan una persona.
  El rechequeo al abrir la pantalla sigue funcionando, así que nadie queda sin salida.
- **El fallo de una identidad no se lleva puestas a las demás.** ARCA homologación corta
  conexiones cada tanto, y la próxima vuelta es en 15 minutos.
- **Vive en el `lifespan` de `main.py`** y no en un cron ni en un worker aparte. Un comando
  colgado del Task Scheduler es más prolijo en producción y **en desarrollo simplemente no
  corre**, o sea que el circuito que esto cierra no se podría probar donde se prueba todo. Con N
  workers barre uno solo: se encarga el advisory lock.
- **Duerme antes de la primera vuelta.** Arrancar barriendo alargaría el arranque con una
  llamada que nadie pidió y convertiría un proceso que crashea y se reinicia en un martillo
  contra ARCA.
- **`asyncio.to_thread`**, porque `recheck_pending` es sincrónico de punta a punta (SQLAlchemy
  sync y zeep sobre requests) y correrlo derecho bloquearía el event loop toda la conversación
  con ARCA.

### La revocación deja de ser una nota al pie
`delegation_verified_at` siempre significó "esto era verdad en esta fecha". Ahora tiene
consecuencias: **una respuesta negativa sobre una identidad verificada limpia la columna**, y la
identidad deja de poder emitir. Antes la app se enteraba de una revocación recién con un rechazo
al emitir, que es el peor momento posible.

- **Solo el 600 desverifica.** Cualquier otra respuesta de ARCA levanta excepción en
  `check_delegation` —eso ya era así— justamente para que una respuesta ambigua o un ARCA caído
  no le saquen a nadie la posibilidad de emitir. Hay un test de cada lado.
- **Por eso el estado verificado ya no tiene botón.** Lo tenía para poder repreguntar, pero
  depender de que alguien se acuerde de apretarlo para detectar una revocación nunca iba a
  funcionar. Lo reemplaza el rechequeo por vencimiento al abrir la pantalla.

## Emisión con CAE (2026-08-27)
`POST /invoice-templates/{id}/emit` le pide el CAE a ARCA y guarda la factura; el `GET
/{id}/preview` de al lado dice qué saldría sin emitir nada. Tablas `invoices` e
`invoice_lines` (migración `3610e7b47b8a`), la mitad que faltaba de `wsfe.py`, y las pantallas
`/modelos/:id/emitir`, `/facturas` y `/facturas/:id`.

**Es lo único irreversible hacia afuera que hace la app.** Con `ARCA_ENV=prod`, cuando el
endpoint contesta 201 hay un comprobante con validez legal a nombre de un CUIT real, y no
existe camino de vuelta: se deja sin efecto con una nota de crédito, que FactuMov no emite.
Casi todo lo de abajo sale de esa asimetría.

### Dos códigos heredados de Balance360 estaban mal
Lo encontró la primera emisión de prueba contra homologación, no un test: ARCA rechazó una
factura B con el código **10243** ("El campo Condicion IVA receptor no es valido para la clase
de comprobante informado"). Preguntándole a ARCA su propia tabla —`FEParamGetCondicionIvaReceptor`—
aparecieron dos errores que venían de Balance360 y que **ningún test podía ver**, porque los
tests comparaban el enum contra sí mismo:

| | Valía | Para ARCA ese código es | Es |
|---|---|---|---|
| `CondicionIva.FINAL` | 6 | Responsable Monotributo | **5** |
| `CondicionIva.MONOTRIBUTO` | 13 | Monotributista Social | **6** |

O sea que el nombre y el código decían cosas distintas. No era teórico: con `FINAL = 6`, la
factura B a un consumidor final —el caso más común que existe, y la mitad de las facturas B de
`tests/samples/`— la rechazaba ARCA. Con 5, la autoriza.

- **El cambio no toca la base.** La columna guarda el **nombre** del miembro
  (`Enum(CondicionIva)` sin `values_callable`), no su valor, así que no hubo migración. Lo que
  sí cambia es el número que viaja en el JSON, y por eso `api/types.ts` se corrigió a la par.
- **Y arrastró la tabla de letras.** Un receptor "Responsable Monotributo" es de clase
  `A/ALEY/C` para ARCA, no `B/C`: es la Ley 27.618. Ver *La letra del comprobante se deduce*.
- **Hay un test que fija los cuatro valores contra la tabla de ARCA**, que es lo único que
  hubiera atajado esto antes. Un enum que se compara solo consigo mismo siempre cierra.
- **Balance360 tiene los mismos valores**, y esto es una pista de que allá puede estar
  declarando la condición equivocada del receptor. Sin revisar.

### Verificado contra ARCA homologación — 2026-08-27
No es SOAP mockeado: son CAE de verdad, emitidos con la deducción de la letra y el enum de la
app, o sea el mismo camino que sigue el botón.

| Emisor → Receptor | Letra | Resultado |
|---|---|---|
| Inscripto → Inscripto | A | CAE `86350816969306` |
| Inscripto → Monotributo | A | CAE `86350816969495` |
| Inscripto → Exento | B | CAE `86350816969500` |
| Inscripto → Consumidor final | B | CAE `86350816969526` |

Con concepto "servicios" y su período, e importes con centavos (2 × 1234,56). El CUIT
`20182810674` **no tiene puntos de venta dados de alta en homologación** —`FEParamGetPtosVenta`
contesta 602— y aun así el punto de venta 1 emite: en homo ARCA no valida eso.

### Los importes: `services/invoice_totals.py`
Port de `Invoice.iva_breakdown` de Balance360, sacado del modelo ORM y convertido en función
pura sobre datos planos. Lo necesitan tres lugares que no comparten tipo —el request a WSFE,
el `Invoice` que se guarda y el PDF que viene después—, y colgarlo del modelo lo ataba al
último.

- **Se redondea cada subtotal por alícuota y recién después se suma.** ARCA valida que
  `ImpTotal == ImpNeto + ImpIVA + ImpTrib + ImpOpEx + ImpTotConc` con dos decimales exactos.
  Sumando en alta precisión y redondeando al final, algunos casos se van un centavo — y el
  rechazo de WSFE no nombra el redondeo por ningún lado. Hay un test parametrizado que fija la
  invariante para las tres letras.
- **`ROUND_HALF_UP` y no el `ROUND_HALF_EVEN` de Python.** El banquero es mejor
  estadísticamente y no es lo que hace ninguna calculadora: una diferencia de un centavo contra
  lo que el cliente sacó a mano es una llamada telefónica.
- **La C no lleva array `Iva`** y su `ImpNeto` es el `ImpTotal`. Mandarlo —aunque sea con
  alícuota 0— es un rechazo. La B **sí** lo lleva aunque no discrimine IVA en el impreso: no lo
  muestra, pero lo declara.
- **En la C se ignora la alícuota que tenga cargada la línea.** Un modelo que quedó al 21% de
  cuando el emisor era responsable inscripto no le puede inventar IVA a una factura C.

### La factura emitida es lo contrario del modelo
`Invoice` repite tres campos que `InvoiceTemplate` deliberadamente no guarda, y no es una
incoherencia: es la misma regla —"no guardes lo que podés deducir"— dando resultados opuestos
según si el dato describe una **intención** o un **hecho**.

- **`voucher_type` es columna acá y propiedad allá.** En el modelo se deduce para que no quede
  vieja: el día que un cliente se inscribe en IVA, sus modelos tienen que pasar de B a A solos.
  En la factura, deducirla sería el bug — la letra la fijó ARCA ese día, y recalcularla mañana
  reescribiría un comprobante ya emitido.
- **Los importes se guardan.** Son derivables de las líneas, pero lo que vale no es lo que la
  fórmula dé mañana sino lo que ARCA autorizó: el CAE cubre **esos** números.
- **El emisor y el receptor están copiados campo por campo.** Las FK quedan para navegar y para
  el scoping. Sin la copia, que un cliente corrija su domicilio reescribiría el PDF de todas las
  facturas que ya se le mandaron — y su documento y su condición frente al IVA son además parte
  de lo que ARCA autorizó. **El mail es la excepción y se lee en vivo** — ver *Mandar la factura
  por email*.
- **Las líneas no guardan neto ni IVA**, aunque la factura guarde sus totales. Es la misma
  distinción: el total es el hecho autorizado; el importe de la línea es una multiplicación
  exacta de dos números que están al lado. Lo que puede cambiar es el reparto por alícuota, y
  eso es justamente lo que sí está guardado.
- **No hay `update` ni `delete`**, ni en el CRUD ni en el router, y la ausencia es la decisión.
  El router contesta 405. Una factura emitida no se corrige.
- **`(fiscal_identity_id, pos, voucher_type, number)` es único**, el mismo invariante que ARCA
  sostiene de su lado.
- **Ni `fiscal_identities` ni `customers` se pueden borrar si tienen facturas** (NO ACTION por
  default, mapeado a los `InUseError` que ya existían). `template_id` sí es `SET NULL`: el
  modelo es procedencia, no dependencia, y el del año pasado tiene que seguir siendo borrable.

### La transacción se sostiene abierta durante la llamada a ARCA
Contra lo que hace el resto del proyecto —el registro commitea antes de mandar el mail, la
verificación de delegación commitea antes del SOAP— y a propósito. Lo que hay que serializar es
la **secuencia entera**: preguntar el último número, pedir el CAE para el siguiente y guardar el
resultado. Un candado que se suelte en el medio no protege nada, y dos emisiones simultáneas del
mismo punto de venta tomarían el mismo número. El precio es una conexión tomada unos segundos,
en una operación que se hace unas pocas veces por mes.

- **`pg_advisory_xact_lock` sobre `(fiscal_identity_id, pos, voucher_type)`**, con la clave
  derivada de un `blake2b` — `hash()` no sirve, Python lo aleatoriza por proceso. Es el mismo
  mecanismo que el de `arca_tickets`, con la diferencia de que este tiene que sobrevivir a la
  llamada a ARCA.
- **El CAE se loguea apenas ARCA contesta, antes de tocar la base.** Es la red de seguridad del
  único momento verdaderamente peligroso de la app: entre que ARCA autoriza y que el commit
  termina, la factura existe para el fisco y no existe para nosotros. Si el insert fallara, ese
  renglón es lo único que permite reconstruirla a mano.
- **409 si falta la delegación, 409 si el número ya estaba tomado, 502 si ARCA no contestó.**
  Tres remedios distintos: ir a ARCA, reintentar, esperar. El detalle de ARCA no se propaga —
  mismo criterio que en `verify-delegation`— y queda en el log, que acá importa más que en
  ningún otro lado.

### La pantalla de confirmación
`/modelos/:id/emitir` es una **ruta propia** y no un diálogo dentro del modelo. Un botón
"Emitir" al lado de "Guardar cambios" es, en un celular, un dedo mal apoyado y una factura de
verdad.

- **No es un `window.confirm`.** Hay que mostrar la letra, el destinatario y el importe exacto,
  y eso no entra en un diálogo del sistema — que además bloquea el hilo, no se puede estilar, y
  queda suprimido si el usuario marcó "no mostrar más". Mismo criterio que el borrado de las
  tarjetas.
- **Los importes salen del `preview` del backend**, no de la cuenta del editor. Las dos dan lo
  mismo hoy; la diferencia es que este número es el que se va a declarar, y dos cuentas capaces
  de discrepar justo en esa pantalla no valen lo que ahorran.
- **El `preview` avisa antes de apretar** cuando falta la delegación (`blocked_reason`), en vez
  de dejar que el botón falle con un 409.
- **`if (busy) return` además del `disabled` del botón.** El `disabled` cubre el click y no el
  Enter en un campo del formulario, y un segundo submit en vuelo son dos facturas.
- **La fecha del comprobante se puede elegir, con hoy puesto por default** (2026-08-27). Hasta
  ese día no se podía, con el argumento de que emitir es un acto de hoy. El argumento se cae solo
  en el caso que lo motivó: se factura el viernes, se carga el lunes, y el papel tiene que decir
  viernes. Lo que sigue siendo cierto es que el 99% de las veces la fecha es hoy, así que el
  campo viene lleno y nadie lo toca.
  - **Los límites los pone ARCA y son tres, de tres fuentes distintas.** La ventana alrededor de
    hoy —±5 días corridos para productos, ±10 para servicios, y "productos y servicios" cuenta
    como servicios— la fija el concepto, y sale de `emission_date_bounds` en `services/emission.py`.
    El tercero solo lo conoce ARCA: **la numeración de un punto de venta no puede retroceder en el
    tiempo**, así que la fecha tampoco puede ser anterior a la del último comprobante autorizado
    de esa serie.
  - **La ventana la calcula el backend y viaja en el `preview`** (`date`, `min_date`, `max_date`),
    no la pantalla. Es el mismo argumento que el de los importes: si la calcularan las dos, el
    campo podría ofrecer una fecha que el servidor rechaza, y el borde de la ventana es
    exactamente donde eso pasaría.
  - **Los dos rechazos son 422 y no 502**, y son la única excepción a que el detalle de ARCA no
    se propague: es sobre lo que el usuario eligió, no sobre cómo estamos armados. El de la
    numeración se chequea en `wsfe.py` con la fecha que ya trae `FECompUltimoAutorizado`, o sea
    sin una llamada extra, y el mensaje **nombra esa fecha** — el rechazo real de ARCA es el
    código 10016, que no la dice y llega después de haber pedido un CAE.
  - **`get_last_voucher_number` pasó a ser `get_last_voucher`** y devuelve número y fecha. Los
    dos salen de la misma respuesta y los dos son lo que esa respuesta implica sobre el
    comprobante que se está por pedir.
  - **El default de hoy se arma con `isoDate` y no con `toISOString()`.** El segundo devuelve
    **UTC**: en Argentina, de las 21:00 en adelante ya es el día siguiente allá, así que una
    factura emitida un jueves a la noche saldría propuesta con fecha del viernes. Es el mismo
    error de un día que `formatDate` evita en la otra dirección, y acá pega sobre la fecha de un
    comprobante fiscal.
- **El período y el vencimiento aparecen solo si el modelo es de servicios**, con el mes en
  curso puesto por default. Los tres van juntos o no va ninguno: el schema lo valida, y qué
  hacen falta lo decide el concepto, que el schema no ve y el router sí.

## Mandar la factura por email (2026-08-27)
`GET /invoices/{id}/pdf` y `POST /invoices/{id}/send`, con `services/invoice_pdf.py`, el
template `templates/invoice.html`, adjuntos en `services/email.py` y la columna
`invoices.sent_at` (migración `49023933c5a4`). Cierra la funcionalidad #5 y con ella el
circuito completo: importar un PDF, guardar el modelo, emitir y mandar.

Dependencias nuevas: `weasyprint` (HTML → PDF), `segno` (el QR) y `jinja2` **declarado
explícitamente** — ya venía como transitiva de `fastapi[standard]`, y depender de la
transitiva de otro paquete es una rotura esperando el día que ese paquete la saque.

### El PDF se genera al vuelo, no se guarda
Es determinístico: sale de columnas que no cambian nunca. Guardarlo sería una copia más de un
dato que ya está, con su propio almacenamiento y su propia forma de quedar vieja frente a una
corrección del template. Cuesta unas décimas de segundo y se pide pocas veces.

- **El template no hace cuentas ni navega relaciones.** Todo llega resuelto y formateado desde
  `invoice_pdf.py`, porque los importes que van al papel son los que ARCA autorizó y no algo
  que se calcule al imprimir. Y como el `Invoice` ya trae copiadas las dos partes, el PDF de
  una factura de hace un año sale hoy idéntico — que es la otra mitad del motivo por el que
  esas columnas existen.
- **`StrictUndefined` y `autoescape`.** Lo primero para que una variable mal escrita explote
  en vez de imprimir vacío: en un comprobante fiscal, un campo que desaparece en silencio es
  peor que un error. Lo segundo porque el nombre y el domicilio del cliente son texto que
  cargó una persona.
- **El import de weasyprint va adentro de la función.** Al importarse carga las librerías GTK
  del sistema, y en una máquina sin ellas el import falla: arriba del módulo se llevaría
  puesta la app entera al arrancar en vez de solo esta operación. Mismo criterio que
  `EmailSettings` y el `lifespan` de `main.py`.
- **El template es un paquete (`factumov/templates/`) y se lee con `importlib.resources`**, no
  con una ruta relativa a `__file__`: así sigue funcionando desde un wheel, donde el paquete
  puede no estar desplegado en el disco. Verificado: el `.html` viaja adentro del wheel.
- **El QR lleva los tipos que ARCA espera.** `cuit`, `nroDocRec` y `codAut` van como números
  y `importe` como float. Un string donde va un número se ve igual y el validador de ARCA lo
  rechaza — es la clase de error que ningún test superficial encuentra, así que el suyo
  decodifica el payload y chequea los tipos.
- **Los importes se formatean a mano y no con `locale`.** `setlocale` es global del proceso y
  depende de que el sistema tenga `es_AR`, que en un contenedor no pasa.
- **Una sola copia, no las tres de "Comprobantes en línea".** El original electrónico es uno;
  duplicado y triplicado son del papel.
- **`inline` y no `attachment` en el endpoint del PDF**: en el celular abre el visor del
  navegador, que es lo que uno quiere antes de mandarlo. Bajarlo sigue estando a un toque.

### Enviar sí se puede repetir
Es lo contrario de emitir, y por eso esta pantalla **no** tiene confirmación. Reenviar es
legítimo y frecuente —el cliente dice que no le llegó— así que no hay ninguna guarda contra el
segundo envío: `sent_at` se pisa y ya.

- **`sent_at` es la marca del último envío, no un historial.** La pregunta que la pantalla
  contesta es "¿esto ya se mandó?". Un historial de reenvíos sería una tabla para una pregunta
  que nadie hace; si algún día se hace, eso sí es una tabla y no una columna más.
- **El mail del cliente no se copia al emitir** (2026-08-27, migración `b2d5f80c3e17`). Es la
  excepción a que el receptor esté copiado campo por campo, y la excepción tiene la misma raíz
  que la regla. Las otras cuatro columnas congelan un **hecho fiscal**: son lo que ARCA autorizó
  y lo que salió impreso. El mail no se imprime, no viaja a ARCA y no es parte de nada
  autorizado — es a dónde entregar el PDF, o sea una pregunta sobre **hoy**.
  - **Copiarlo producía un callejón sin salida.** Una factura emitida cuando el cliente todavía
    no tenía dirección se quedaba sin dirección para siempre: el aviso mandaba a cargarla en la
    ficha, cargarla no cambiaba nada, y una factura emitida tampoco se puede editar. La única
    salida era emitir de nuevo, que es la única equivocación cara que se puede cometer en esta
    app.
  - **`Invoice.customer_email` es ahora una propiedad** que lee `customer.email`, y la columna
    pasó a llamarse **`sent_to`**: la dirección a la que salió el **último** envío, `NULL` si
    nunca se mandó. Es el compañero de `sent_at` y sí es una copia — a dónde fue este envío es un
    hecho, y que el cliente cambie de casilla después no puede reescribirlo.
  - Consecuencia: `crud/invoice.py` trae el cliente con `joinedload` en las dos lecturas. Sin
    eso, listar N facturas son N queries más.
  - El `downgrade` de la migración restituye la forma y no los datos, como el de `cf79c4f7610c`:
    las direcciones de las facturas nunca enviadas se van, y no se pueden re-deducir porque el
    cliente pudo haber cambiado de mail.
- **No es acuse de recibo**, y la pantalla lo dice: significa que el servidor de mail lo
  aceptó, no que el cliente lo haya abierto. Eso necesitaría un proveedor con webhooks.
- **503 si el mail no sale, con un texto que aclara que la factura está emitida igual.** El
  error es del envío y no de la emisión; confundirlos haría que alguien vuelva a emitir, que
  es la única equivocación cara que se puede cometer acá.
- **409 si el cliente no tiene email**, con el link a su ficha. Es un dato que falta, no un
  error del servidor.
- **El mail usa `send_email` y no la versión best effort**: es el producto del request. Misma
  regla que el resto — ver *El fallo de SMTP se ve*.
- **`Attachment` recibe los bytes, no una ruta.** El único adjunto que manda FactuMov se
  genera al vuelo y nunca toca el disco, así que un archivo temporal sería basura que alguien
  tiene que acordarse de limpiar.
- **"Sin enviar" es la única marca en la grilla de facturas**, con el mismo criterio que el
  "Sin verificar" de las identidades fiscales: es el único pendiente que puede tener una
  factura ya emitida, y sin eso habría que entrar a cada una para encontrar la que falta.

### `/facturas` no es la grilla de tarjetas
Es una pila de links con tres datos por renglón: qué comprobante, a quién y por cuánto. La
grilla existe para pantallas donde se entra a un elemento **y se lo elimina**, y donde alcanza
el nombre para reconocerlo. Acá no se elimina nada y un solo dato no alcanza. Sigue sin ser una
`<table>`: es lo que la tabla se volvía en angosto, sin el `<thead>` escondido ni el
`data-label` en cada celda.

## Frontend (2026-08-26)
La SPA: autenticación, identidades fiscales con verificación de delegación, clientes con carga
desde el padrón, y la **grilla de modelos con su editor e importación de PDF** — que cierra la
funcionalidad #1 de punta a punta. Vite 8 + React 19 + TypeScript 6, `react-router` como única
dependencia agregada al scaffold.

### Cómo se corre — y cómo llegar desde el celular
Son tres procesos, cada uno en su terminal. Los comandos son de PowerShell, que no tiene `&&`.

```powershell
# terminal 1 — la base
docker compose up -d

# terminal 2 — el backend
cd E:\Capacitacion\InSoft\FactuMovackend
uv run alembic upgrade head          # solo si hay migraciones nuevas
uv run uvicorn factumov.main:app --reload --port 8000

# terminal 3 — el frontend
cd E:\Capacitacion\InSoft\FactuMovrontend
npm run dev
```

**Al backend no se le pasa `--host`, y no es un olvido.** El celular nunca le pega al 8000: le
pega a Vite, y Vite reenvía `/api` a `127.0.0.1:8000` desde la misma máquina (ver *El proxy de
Vite en vez de CORS*). Exponer uvicorn en la LAN abriría un puerto que nadie usa.

El que sí escucha en todas las interfaces es Vite, por el `host: true` de `vite.config.ts`.
Al arrancar imprime la URL *Network*; desde el celular, en la misma Wi-Fi, hay que abrir **esa**
y aceptar la advertencia del certificado autofirmado:

```
https://192.168.1.37:5173      # ejemplo — la IP la da el router y puede cambiar
```

Conviene leer siempre la línea *Network* que imprime Vite en vez de fiarse de la IP anotada
acá: la asigna el DHCP del router y cambia sola.

**Con `https://`, no con `http://`.** Por http la cookie de sesión no se guarda y todo contesta
401 — ver el punto siguiente, que es el error más caro de esta pantalla.

#### Lo que falta si el celular no engancha
- **El firewall de Windows.** Vite escucha, pero el perfil de red (Privado, en la máquina de
  Miguel) bloquea la conexión entrante si nadie la permitió. Normalmente Windows lo pregunta con
  un cartel la primera vez que node abre el puerto y alcanza con darle *Permitir* en redes
  privadas. Si el cartel no aparece, la regla se crea una vez, en PowerShell **como
  administrador**:
  ```powershell
  New-NetFirewallRule -DisplayName "Vite dev 5173" -Direction Inbound -Protocol TCP `
    -LocalPort 5173 -Profile Private -Action Allow
  ```
- **`APP_BASE_URL`, solo para probar el registro.** Ver el detalle al final de *HTTPS en
  desarrollo*.

### HTTPS en desarrollo, y por qué no es opcional
El dev server usa `@vitejs/plugin-basic-ssl`, que genera un certificado autofirmado solo, y
escucha en todas las interfaces (`host: true`).

**La cookie de sesión es `Secure`, y el navegador solo la guarda en un contexto seguro.**
`localhost` cuenta como seguro aunque sea http —por eso en la computadora anda sin
certificado—, pero `http://192.168.0.x:5173` **no**. Probando desde el celular por http la
cookie se setea, nunca vuelve, y todo contesta 401 por un motivo que no se parece en nada a
la causa. Es el mismo problema que resuelve el `base_url="https://testserver"` del TestClient
de la suite del backend, y conviene tenerlos juntos en la cabeza: son el mismo error con dos
disfraces.

La alternativa era hacer configurable el `secure=True` de la cookie y apagarlo en desarrollo.
Se descartó: sería un flag capaz de viajar a producción y dejar la sesión viajando en claro,
a cambio de ahorrarse una advertencia del navegador que se acepta una vez.

Verificado el 2026-08-26: login por `https://192.168.1.37:5173`, cookie guardada, y el
request siguiente autenticado.

**`APP_BASE_URL` va con `https://`, y eso no es un detalle.** De esa variable cuelga el link
de confirmación que sale en el mail, y el 5173 habla TLS. Con `http://localhost:5173` el
navegador manda una request en texto plano a un puerto que espera un handshake, el server
cierra sin contestar, y Chrome muestra **`ERR_EMPTY_RESPONSE`** — que no nombra la causa por
ningún lado y se lee como "la app está caída". Pasó el 2026-08-26: el mail llegó bien y el
link estaba muerto desde el repo, no desde la instalación. Por eso el default de
`EmailSettings` también es `https`.

Para probar el registro **desde el celular** hace falta además cambiar `localhost` por la IP
de LAN, porque el link se abre en el teléfono y ahí `localhost` es el teléfono.

### El proxy de Vite en vez de CORS
`/api` se reenvía a `127.0.0.1:8000` y se le saca el prefijo. El navegador ve **un solo
origen**, así que no hace falta CORS.

La alternativa era pegarle directo al 8000 y agregarle `CORSMiddleware` al backend, con
`allow_credentials=True` y una lista de orígenes. Es una superficie real: la cookie de sesión
es `httpOnly` justamente para que ningún JS la toque, y abrir CORS con credenciales es la
forma más común de aflojar esa decisión sin darse cuenta. En producción la SPA y la API van
detrás del mismo nginx, que es exactamente lo que el proxy imita — o sea que esto no es un
apaño de desarrollo, es la topología final.

Consecuencias: el cliente pega siempre a rutas relativas y **no hay ninguna variable de
entorno con la URL del backend**. Y el puerto es `strictPort: true`: `APP_BASE_URL` del
backend apunta al 5173, y si Vite se corriera al 5174 por estar ocupado el puerto, el link de
confirmación de los mails llegaría roto.

### Las pantallas sin sesión
Cinco, todas fuera de `RequireAuth`: `/login`, `/registro`, `/confirmar-email`,
`/olvide-password` y `/restablecer-password`. Las tres últimas aterrizan un link de mail o
disparan uno, y **sus paths los fija el backend** (`_CONFIRMATION_PATH`,
`_PASSWORD_RESET_PATH` y `_REGISTER_PATH` de `notifications.py`): cambiarles el nombre acá sin
cambiarlo allá deja apuntando a la nada los mails ya enviados.

### Sesión
- **No se guarda nada del lado del cliente.** La cookie es `httpOnly`, así que el JS no la
  puede leer; la única forma de saber si hay sesión es un `GET /auth/me` al montar el
  `AuthProvider`. Un flag en `localStorage` sería más rápido y mentiría en los dos casos que
  importan: la sesión revocada desde otra pestaña y la vencida.
- **`user` tiene tres estados, no dos:** `undefined` es "todavía no sé", `null` es "no hay
  sesión". Sin esa distinción, recargar en `/clientes` rebota al login antes de que conteste
  `/auth/me`, y el usuario logueado se ve pateado afuera en cada refresh.
- **`credentials: 'include'` en el cliente.** Sin eso el navegador no manda la cookie y
  *todo* contesta 401 — una falla que no se parece en nada a su causa.
- **`RequireAuth` no es seguridad, es navegación.** Quien quiera los datos le pega a la API
  igual; ahí decide `get_current_user`. Se aplica al grupo de rutas y no pantalla por
  pantalla, mismo criterio que el `APIRouter(dependencies=[...])` del backend: la regla
  escrita una vez no se puede olvidar en la pantalla que se agregue mañana.

### Mobile-first
El estilo base es el de pantalla angosta; `@media (min-width: 700px)` agrega lo de escritorio.
El corte está elegido por el contenido —el ancho a partir del cual dos campos conviven en un
renglón sin apretarse— y no por el tamaño de ningún dispositivo.

- **Ya no hay tablas.** Las tres pantallas de listado son la grilla de tarjetas — ver *La
  grilla de tarjetas*. Hasta el 2026-08-26 eran `<table>` que en angosto se volvían tarjetas con
  `data-label` en el `<td>` y el `<thead>` escondido con `clip-path` (no con `display: none`,
  que se lo esconde también al lector de pantalla y deja a las celdas sin nombre). El truco
  seguía siendo bueno; lo que dejó de haber es una tabla que pintar, así que el CSS se borró en
  vez de quedar decorando el archivo. **Queda anotado acá por si vuelve a hacer falta** — el día
  que aparezca una pantalla que sea de verdad tabular, como el listado de facturas emitidas.
- **Los inputs van a 16 px como mínimo.** Safari en iOS hace zoom automático al enfocar un
  campo con tipografía más chica y después no vuelve solo: el usuario queda con la página
  agrandada y la despincha a mano. No es estética.
- **Objetivo táctil de 44 px** (`--touch`) en botones, campos y pestañas. Es el piso común de
  las guías de Apple y de Material.
- **Los botones ocupan el ancho en angosto** y vuelven a su tamaño natural en ancho. En un
  celular el botón es el objetivo más grande que se puede dar, y evita el "apreté al lado".
- **La barra superior es `sticky`** y la navegación baja a su propio renglón, a lo ancho: en
  el celular la lista es larga y volver arriba para cambiar de sección es la mitad de la
  navegación. La dirección de mail aparece recién cuando hay lugar.
- **`overflow-x: hidden` en el `body`.** Sin eso, cualquier cosa ancha estira la página y todo
  se va de costado.

### La grilla de tarjetas (2026-08-26)
**Las tres pantallas de listado tienen la misma forma**: una tarjeta por elemento con el nombre,
una vacía con un `+` al final, se entra tocando y se elimina manteniendo apretado. Vale para
modelos (`/`), identidades fiscales (`/identidades`) y clientes (`/clientes`). Confirmado por
Miguel el 2026-08-26: la grilla de modelos es la forma que pidió, y pidió explícitamente que las
otras dos se comportaran igual.

Cada elemento tiene su pantalla: `/modelos/:id`, `/identidades/:id`, `/clientes/:id`; y el `+`
lleva a `/modelos/nuevo`, `/identidades/nueva`, `/clientes/nuevo`.

- **El markup y los gestos viven en `components/TileGrid.tsx`, una sola vez.** No es un patrón
  visual que se pueda copiar y pegar: adentro tiene el estado de cuál tarjeta está armada, el
  gesto y las tres precauciones de `useLongPress`. Copiado tres veces, la próxima corrección del
  gesto arregla una pantalla y deja dos rotas — y el síntoma sería "en clientes el borrar se
  comporta raro", que nadie va a atribuir a un `onClickCapture` que falta.
- **Identidades y clientes dejaron de ser una tabla con el formulario de alta arriba.** Esa
  forma no estaba mal en la computadora, pero en 360 px una tabla de cinco columnas es una pila
  de tarjetas improvisadas con dos íconos de 44 px apretados al final de cada una — y el celular
  es el caso principal. De paso desaparece la pregunta de "en esta pantalla cuál era el gesto".
- **La raíz sigue siendo la grilla de modelos y no las identidades fiscales.** Identidades y
  clientes son configuración: se tocan al empezar y después casi nunca. Dejar una de ellas de
  portada le cobra un toque a la pantalla que se abre cien veces por semana.
- **La tarjeta muestra solo el nombre.** Lo que hace falta ahí es reconocer el elemento de un
  vistazo y llegar con un dedo; el CUIT, el cliente y los importes están adentro, que es donde
  se los mira. Una lista con cuatro columnas diría más y se leería peor.
- **La única excepción es "Sin verificar" en la identidad fiscal**, y está acotada a ese caso a
  propósito: una identidad sin delegación verificada **no puede emitir**, así que sin el aviso el
  usuario tendría que entrar tarjeta por tarjeta a buscar cuál lo está frenando. Aparece solo
  cuando falta, o sea que el estado normal sigue siendo una grilla de nombres. La regla que fija
  el `warning` de `TileItem` es esa: un estado que bloquea, no un dato más que mostrar.
- **Se fue `DeleteButton` con las tablas.** El tacho de dos pasos ("¿Eliminar? Sí / No") existía
  para las filas; en la grilla, sostener el dedo medio segundo ya *es* el paso deliberado, y lo
  que hace falta después es un objetivo grande y sin ambigüedad. Lo que se conserva de él es la
  decisión que importaba: nada de `window.confirm` —bloquea el hilo, no se puede estilar, y en
  algunos navegadores queda suprimido si el usuario marcó "no mostrar más", o sea que la
  confirmación desaparece sin que nadie se entere—, y el error del 409 se muestra **adentro de
  la tarjeta**, porque "tiene modelos asociados" es sobre ese elemento y mostrarlo arriba obliga
  a adivinar cuál se quejó.
- **Se entra tocando y se borra manteniendo apretado.** Que eliminar quede detrás de un gesto
  y no de un tacho siempre visible es a propósito: en una grilla de objetivos de 150 px, un
  ícono de borrar pegado al área que se toca cien veces por semana se aprieta solo. La tarjeta
  armada muestra dos botones con su nombre escrito —"Eliminar" y "Cancelar"— y no el tacho de
  dos pasos de las listas: sostener el dedo medio segundo ya fue el paso deliberado, y lo que
  falta es un objetivo grande.
- **El gesto no puede ser la única puerta.** Sostener el dedo es invisible con un mouse y no
  existe con un teclado, así que `useLongPress` engancha además `contextmenu`, que es el mismo
  evento para el botón derecho, la tecla Menú y Shift+F10. Una sola acción, tres entradas.
- **`useLongPress` usa eventos de puntero**, no `touchstart`/`mousedown`: cubre dedo, mouse y
  lápiz con un juego de handlers y evita que un toque dispare las dos ramas (los navegadores
  emiten eventos de mouse sintéticos después de un toque). Tres detalles que costaron pensarlos
  y sin los cuales el gesto se siente roto: una tolerancia de 10 px para que arrastrar la lista
  no abra el menú de la tarjeta de abajo; un `onClickCapture` que se come el `click` que el
  navegador manda igual al soltar —si no, mantener apretado abre el menú **y** entra a la
  tarjeta—; y `user-select: none` + `-webkit-touch-callout: none` en el CSS, porque si no iOS
  abre su menú de copiar justo encima del gesto.
- **La identidad fiscal y el cliente son un `PickerField`, no un `<select>`.** Tocar abre la
  lista; mantener apretado entra a editar el elegido. El `<select>` nativo abre el picker del
  sistema —que en el celular está muy bien— pero no deja colgarle un gesto propio ni mostrar
  dos renglones por opción, y el CUIT abajo del nombre es lo que distingue dos clientes que se
  llaman parecido.
- **El id a editar viaja en el path** (`/identidades/<id>`), no en un estado compartido. Es lo
  que hace que el gesto sea un link común: sin eso haría falta un canal aparte para decirle a la
  pantalla de identidades con qué fila arrancar. Fue `?editar=<id>` sobre la lista mientras la
  edición era un formulario arriba de una tabla; con una pantalla por elemento el path dice lo
  mismo sin que haya que explicar la URL. El alta y la edición comparten componente, con un `key`
  que lo remonta al cambiar de id — copiar la prop al estado con un efecto es el mismo resultado
  con un render de más y una forma conocida de pisar lo que el usuario ya tipeó.
- **El alta vuelve a la grilla; la edición se queda y dice "Guardado".** La tarjeta nueva en la
  grilla es la confirmación de que se creó, y es además donde el usuario iba a ir igual. En la
  edición no hay tarjeta nueva que mirar, así que hace falta decirlo — y el cartel se apaga al
  primer cambio, que es la forma más barata de que nadie salga creyendo que guardó lo que acaba
  de tipear.
- **El formulario es controlado desde afuera.** Que el editor se guarde el estado adentro no
  serviría para la pantalla de importación, que después de dar de alta un cliente tiene que
  meterle el id al formulario que el usuario ya empezó a tocar.
- **`forms/templateForm.ts` está separado de `TemplateEditor.tsx` por Fast Refresh**, que solo
  recarga en caliente un módulo que exporta componentes y nada más — el mismo motivo por el que
  el contexto de sesión vive en tres archivos.
- **Los importes se tipean con coma o con punto.** `parseAmount` acepta `1.234,56` y `1234.56`;
  sin eso el que escribe como se escribe acá manda `NaN`. Y viajan como **string** al backend,
  no como `number`: `Decimal` se serializa con su escala, y pasar por el binario de coma
  flotante en el camino de ida es pedirle centavos al azar.
- **El total de la pantalla aplica la convención del proyecto**: en A el precio va neto y en B
  y C ya viene con el IVA adentro. No es una regla nueva, es la misma que usa el parser al leer
  un PDF. La letra que decide cuál de las dos aplica es la **deducida** —ver *La letra del
  comprobante se deduce*—, así que el total se recalcula solo al cambiar de cliente. Mientras
  falte elegir emisor o cliente no hay letra y se asume IVA incluido, que es lo que vale en tres
  de las cuatro combinaciones. Está escrito abajo del total que es una cuenta nuestra y que el
  importe que vale es el que autorice ARCA.
- **La importación ofrece dar de alta el cliente que trajo el PDF.** El draft trae los datos
  del receptor pero no un id cuando no está cargado, y sin ese botón importar una factura de un
  cliente nuevo es un callejón sin salida: el editor pide un id. El alta sigue siendo explícita
  —un botón, no un efecto de la importación—, que es la misma regla que hace que `/import` no
  escriba nada.
- **"Empezar en blanco" no es un extra.** Hay un segundo layout de factura que el parser
  todavía no sabe leer, y un PDF escaneado contesta 200 con el modelo vacío a propósito. Con
  una sola puerta, cualquiera de esos dos casos queda sin salida.
- **La palabra de la UI es "modelo".** Miguel dice indistintamente "modelo" y "plantilla"; se
  eligió "modelo" porque es lo que ya dicen los mensajes de error del backend ("Modelo no
  encontrado", "No se puede eliminar un cliente con modelos asociados") y tener la pantalla
  diciendo una cosa y el error otra es peor que cualquiera de las dos.

### El PDF que llega de la nube (2026-08-26)
Importar una factura elegida **desde Google Drive** en el selector de Android fallaba con «No se
pudo conectar con el servidor», que es el mensaje de `ApiError(0, …)` — el que el cliente HTTP
usa cuando `fetch` **rechaza**, o sea cuando no hubo respuesta: backend apagado, DNS, red
cortada. Nada de eso pasaba: la sesión andaba y el resto de las pantallas cargaban.

**Un `File` recién elegido no es memoria, es un puntero.** El navegador lo resuelve recién
cuando alguien lee sus bytes, y con un proveedor de la nube esa lectura sale a buscar el archivo
a Drive. Si falla —o si el proveedor entrega un archivo vacío— y el `File` se le pasó directo al
`fetch`, la falla revienta **adentro del `fetch`**, que rechaza igual que si el server no
estuviera. De ahí el mensaje: era verdadero sobre el `fetch` y falso sobre el mundo, y mandaba a
Miguel a mirar la red cuando el problema era el archivo.

Entonces `api.upload` pasó a recibir un `Blob` ya leído más el nombre, y la pantalla lee los
bytes con `file.arrayBuffer()` antes de armar el request. Con eso el error aparece donde ocurre y
con el texto que corresponde: «bajalo al teléfono primero y volvé a intentar», que es la acción
que lo resuelve. Un archivo de largo cero cae en la misma rama, porque para el usuario es el
mismo problema.

Dos detalles que van con esto:

- **El `<input type=file>` se limpia en el `finally`, no antes de subir.** Se limpia porque sin
  eso elegir el mismo archivo dos veces seguidas no dispara `change` y el botón parece roto; pero
  hacerlo antes de leer los bytes es soltar la referencia al archivo que todavía falta leer, que
  es una segunda forma de llegar al mismo bug.
- **No convierte a `ApiError` un problema local.** El 415 por magic bytes y el 200 con draft
  vacío siguen siendo del backend y siguen significando lo que significaban; esto es una tercera
  cosa —el archivo no se pudo leer— y se contesta antes de salir a la red.

### Sin TanStack Query y sin Tailwind
Las dos por el mismo motivo: resuelven problemas que esta app todavía no tiene.

TanStack Query da caché compartida entre pantallas, deduplicación y revalidación en foco —
y acá son cuatro pantallas, cada una con su propia lista. `useResource` son treinta líneas.
Revisar cuando dos pantallas necesiten los mismos datos y empiecen a discrepar.

Tailwind: son formularios y tablas, y lo que se ahorraría en clases se pagaría en una
dependencia con su propio build. Revisar cuando el editor de facturas traiga drag-and-drop.

### Detalles que costaron una vuelta
- **`types.ts` se escribe a mano y tiene que coincidir *exactamente*.** `UserRead` del backend
  son dos campos, `id` y `email`. Declarar acá un `created_at` que el JSON no trae lo tipa
  como presente y el error sale recién en runtime, como un `undefined` en la pantalla. Y
  `MessageResponse` es `{detail}`, no `{message}`.
- **`EmailStr` rechaza los TLD reservados**: `@algo.local` y `@algo.test` dan 422. Para un
  usuario de prueba hay que usar un dominio real (`@factumov.com.ar`).
- **El token de confirmación es de un solo uso y StrictMode monta dos veces.** Sin un `useRef`
  de guarda, la confirmación anda y la pantalla muestra igual "el link no es válido", porque
  el segundo POST da 400.
- **El contexto, el provider y el hook van en tres archivos.** Fast Refresh solo recarga en
  caliente un módulo que exporta componentes nada más; mezclarlos hace que cada cambio
  recargue la página entera y se pierda el formulario que uno estaba probando.
- **El linter es `oxlint`** (viene con el scaffold) y avisa de `setState` sincrónico adentro
  de un efecto. Tenía razón las dos veces: en `useResource` el `loading` se prende ahora
  desde `reload`, que es el evento que lo causa, y en `ConfirmEmailPage` el caso "link sin
  token" se resuelve en el estado inicial porque ya se sabe al primer render.
- **Los enums viajan como el código de ARCA** (`condicion_iva: 1`), igual que en el backend.
  El texto de pantalla sale de `CONDICION_IVA_LABELS`; traducirlos en el cliente agregaría
  una tabla que se puede desincronizar.
- **Consumidor final no está en el desplegable de identidad fiscal**, porque no puede emitir y
  el backend lo rechaza con 422. No se ofrece una opción que siempre falla.
- **El lookup del padrón prellena el formulario y no da de alta.** Que quede editable es el
  punto: el backend devuelve una propuesta. Si guardara directo, consultar dos veces el mismo
  CUIT dejaría dos clientes.
- **El 502 y el `granted: false` se muestran distinto.** "No se pudo preguntar" y "no estás
  delegado" son cosas distintas; mezclarlas haría que un ARCA caído se vea como una
  delegación faltante y el usuario iría a otorgar una que ya tiene. **Pasó de verdad el
  2026-08-26:** ARCA homologación no contestó, salió el 502, y el cartel rojo se leyó como un
  rechazo. Ver *ARCA → Los 502 son transitorios*.

## Ownership scoping (2026-08-26)
`user_id` en `fiscal_identities` y `customers`, todas las queries de esas dos tablas
scopeadas al usuario de la sesión, y las de `invoice_templates` scopeadas por join.
Migración `2c2b5ddd2d8d`.

- **`invoice_templates` no lleva `user_id`.** Cuelga de `fiscal_identity_id`, que ya está
  indexado, así que el scoping sale de un join. Denormalizar la columna acortaría las
  queries a cambio de una tercera fuente de verdad capaz de contradecir a sus padres —un
  modelo cuyo `user_id` dice A y cuya identidad fiscal es de B— y no ahorraría ninguna
  validación: chequear que los dos padres son del usuario hace falta igual al escribir.
  Con esa validación puesta, alcanza con joinear una sola de las dos relaciones, porque
  ambas apuntan siempre al mismo dueño.
- **Todos los uniques de esas dos tablas pasaron de globales a por-usuario:**
  `fiscal_identities.name` y `.tax_id` a `(user_id, name)` y `(user_id, tax_id)`, y
  `(doc_type, doc_number)` de `customers` a `(user_id, doc_type, doc_number)`. Global
  rompía casos normales —dos usuarios le facturan al mismo cliente; el contador carga el
  CUIT de su cliente mientras el titular tiene su propia cuenta— y sobre todo reintroducía
  por la puerta del 409 el oráculo de existencia que el 404 cierra en la lectura: "CUIT
  duplicado" sobre una fila ajena confirma que esa fila existe. Aflojar el unique del CUIT
  no afloja el control de titularidad, que lo da la verificación de la delegación en ARCA.
  `uq_invoice_templates_fiscal_identity_id_name` no cambió: ya queda scopeado
  transitivamente.
- **El 404 sale del filtro, no de una comparación.** Ningún `get_*_or_404` compara dueños:
  los getters filtran por `user_id` en la query, así que la fila ajena y la fila
  inexistente son el mismo caso y no hay rama que pueda contestar 403 por descuido. Por
  eso también `get_by_id` dejó de usar `db.get()`, que busca por PK y no admite filtro.
- **Escribir apuntando a un padre ajeno da 422, con el mismo mensaje que un id
  inexistente.** Es el caso que la base no puede atajar sola: la FK apunta a una fila que
  sí existe. Lo valida el CRUD de `invoice_template` en create y en update —el PATCH
  también, o el modelo se reapunta después de creado— levantando las `Unknown*Error` que
  ya existían, así que el router no cambió. El `exception_map` sigue mapeando las
  violaciones de FK como backstop para dos requests concurrentes.
- **Los dos lookups de `/import` van scopeados.** Era el bug más silencioso de la unidad:
  nadie escribía nada mal, pero el draft volvía con el `customer_id` de una fila ajena, el
  usuario lo confirmaba en el editor y el modelo guardado terminaba apuntando al cliente
  de otro.
- **`user_id` no entra por el body ni sale en los schemas `Read`.** Sale de la sesión y es
  argumento del CRUD, no campo del schema: aceptarlo por el body dejaría al cliente elegir
  a nombre de quién escribe, y devolverlo sugiere que es un campo del recurso cuando su
  valor es siempre el que consulta.
- **Sin `ondelete` en las dos FK a `users`.** El NO ACTION por defecto hace fallar el
  borrado de un usuario que todavía tiene datos, que es lo correcto mientras no exista el
  endpoint de baja de cuenta — esa unidad es la que va a elegir entre cascada y
  anonimizar. Por lo mismo no se declararon `User.customers` ni `User.fiscal_identities`:
  nada necesita navegar en esa dirección, y declararlas obliga a decidir hoy ese cascade.
- **La migración se niega a inventar un dueño.** Si hay filas huérfanas y no hay
  exactamente un usuario al cual atribuirlas, corta con `RuntimeError` en vez de adivinar
  — mismo criterio que `cf79c4f7610c`. El `downgrade` corta también, porque devolver los
  uniques a globales puede chocar con datos que el esquema nuevo permite legalmente (dos
  usuarios con el mismo CUIT o el mismo cliente).
- **Las factories piden `user_id` obligatorio** en `make_fiscal_identity` y
  `make_customer`. Con default hubieran sido más cortas de llamar y le habrían dado a la
  identidad fiscal y al cliente de un mismo test dos dueños distintos; la falla que sigue
  —`UnknownCustomerError` saliendo de un create de modelo— no se parece en nada a la
  causa. `make_invoice_template` no necesita dueño propio: lo lee de la identidad fiscal.

## Tests
- **Los tests de CRUD no pasan por HTTP; los de router sí**, con el fixture `client` de
  `conftest.py`. Ese fixture depende de `db` y sobreescribe `get_db` con
  `app.dependency_overrides`: sin eso el request abriría su propia sesión contra la base
  real y no vería nada de lo que el test armó. El override no commitea a propósito —
  revertir es trabajo del fixture `db`. La limpieza final no es opcional: `app` es un
  singleton de módulo y un override olvidado se filtra a todos los tests siguientes.
- **`Decimal` viaja como string en JSON** (`"1.00"`, no `1.0`): Pydantic lo serializa así
  para no perder la escala. Los asserts sobre importes comparan strings.
- **Desde la unidad de autenticación, `client` va autenticado y el anónimo es
  `anonymous_client`** — el porqué, y los detalles de la cookie `Secure` y del costo de
  argon2 en los fixtures, están en *Autenticación → Tests de autenticación*.
- **`other_user` es el segundo usuario, para los tests de scoping.** Va activo y confirmado
  a propósito: si estuviera dado de baja, un test que espera 404 podría estar pasando por
  el 401 de `get_current_user` y no por el scoping. Los fixtures `fiscal_identity` y
  `customer` son del usuario de `client`; las filas de `other_user` se arman con la factory
  en el propio test, que es donde se lee de quién es cada cosa.
- **El cliente de test es `httpx2`.** Starlette 1.5 importa `httpx2` primero y solo cae a
  `httpx` con un `StarletteDeprecationWarning`; la rama de fallback ya tiene un
  `RuntimeError` para cuando no esté ninguno. `httpx` igual sigue instalado porque
  `fastapi[standard]` lo requiere: es esperable, no un resto sin limpiar.

## Marca, landing y producción (2026-08-27)
Tres pedidos de Miguel del 2026-08-27 que no son funcionalidad de la app: ponerle la marca de
InSoft, publicarla en la landing y sacarla a producción. Van en ese orden porque cada una es
insumo de la siguiente: sin ícono no hay tarjeta ni favicon, y sin URL de producción la
tarjeta no tiene a dónde linkear.

**La marca está hecha** — ver *La marca, hecha*. Producción y la landing siguen pendientes, y
lo que hay abajo de ellas es el relevamiento para que la sesión que las implemente no lo tenga
que rehacer.

### Lo que ya existe y hay que reusar
La landing vive en `E:\Capacitacion\InSoft\LandingPage`, **fuera de este repo y sin git**: un
solo `insoft-v3-seo.html` (~570 líneas, CSS y JS inline), las imágenes sueltas al lado y
`scp.ps1`, que lo publica.

| Cosa | Dónde |
|---|---|
| Logo horizontal, vertical y tagline, en claro y oscuro | `LandingPage/insoft-logo-pack/*.svg` |
| Ícono suelto (la pastilla verde con el círculo blanco) | `LandingPage/insoft-icono.svg` |
| Favicons y `icon-512` ya generados | `LandingPage/insoft-logo-pack/` |
| Paleta | `--green:#2EBD59`, `--deep:#1B9E4B`, `--night:#0E1626`, tinta `#1E293B` |
| Tipografía de la landing | Manrope |

**El logo de InSoft es un interruptor**: una pastilla con gradiente vertical `#2EBD59 →
#1B9E4B` y un círculo blanco a la derecha, o sea encendido. Eso es la idea de toda la marca
("el software puede ser intuitivo"), y es lo que un ícono de producto tiene que citar sin
copiar.

### El ícono en la línea de Gastin
El de Gastin está inline en la landing (`<button class="mini">`, cerca de la línea 470) y su
construcción es la receta a seguir:

- `viewBox="0 0 120 120"`, fondo `<rect rx="23">` — o sea el radio de un ícono de app.
- **Un solo trazo** de 14 px con `stroke-linecap="round"`, que dibuja la inicial: una `G` que
  es un arco abierto.
- **El trazo termina en un punto** (`<circle r="6">`), que es la cita al círculo blanco del
  interruptor de InSoft.
- Dos estados: apagado en grises (`#E4EAE5` / `#BDC9C0`) y encendido con fondo `#0F172A` y el
  trazo en `var(--green)`. La landing los usa para su truquito de "encender" la tarjeta.

O sea que el de FactuMov es: fondo redondeado, un trazo verde que dibuje la `F`, y el punto al
final del trazo. La familia es la construcción, no el dibujo. Es lo que se construyó — ver
*La marca, hecha*.

**Cuidado con no inventar una tercera marca.** El acento de la SPA era `#1f6feb`, el azul del
default del scaffold, que no tenía nada que ver con InSoft. Ya es verde.

### La marca, hecha (2026-08-27)
`frontend/public/factumov-icon.svg` y su variante maskable, los PNG que salen de ellos, el
`manifest.webmanifest`, el acento verde de la SPA y el logo de InSoft en las pantallas sin
sesión. Se fueron el `favicon.svg` y el `icons.svg` del scaffold —una flecha violeta y un
juego de íconos de redes sociales que nadie importaba—.

#### El ícono: una F de dos trazos, con el punto al final
La receta es la del de Gastin: `viewBox="0 0 120 120"`, fondo `#0F172A` con `rx="23"`, un trazo
de 14 con puntas redondas que dibuja la inicial, y un `<circle r="6">` donde ese trazo termina.
El punto es la cita al círculo blanco del interruptor de InSoft, que es la idea de toda la
marca.

- **La F no se puede dibujar de un trazo continuo, y la G sí.** A la F le sobra una rama: no
  hay recorrido que pase por el travesaño del medio, el asta y el travesaño de arriba sin
  levantar el lápiz. Son dos subpaths de un mismo `path` —`M82 33 H38 V87 M38 60 H68`— y el
  del medio arranca **sobre** el asta, así que su punta redonda queda escondida adentro y la
  unión no se ve. Lo que sí se conserva es dónde cae el punto: el travesaño corto de la F es
  el análogo exacto de la barra interna de la G.
- **El trazo lleva el gradiente vertical de la pastilla** (`#2EBD59` → `#1B9E4B`) y no el
  verde plano del de Gastin. Es el rasgo más reconocible de la marca de la casa y sale gratis.
  Va con `gradientUnits="userSpaceOnUse"` sobre la altura real del trazo con sus puntas (26 a
  94) y no sobre el bounding box, que en un path con stroke no incluye el ancho del trazo y
  dejaría el gradiente corrido.
- **Hay una variante maskable** (`factumov-icon-maskable.svg`): el mismo dibujo con el fondo
  llegando hasta el borde, sin las esquinas redondeadas. Android recorta el ícono con la forma
  que elija el launcher, así que uno que ya viene redondeado queda con un halo del fondo del
  sistema en las esquinas. La condición que hay que cumplir es que el contenido entre en el
  círculo seguro del 80% central: la punta más lejana de la F está a 45 del centro, contra los
  48 que mide ese radio.

#### Los PNG salen del SVG, con las dependencias del backend
`frontend/scripts/render_icons.py` genera `icon-192`, `icon-512`, `icon-maskable-512` y
`apple-touch-icon`. Los PNG se versionan —ni el `apple-touch-icon` ni el manifest aceptan otra
cosa— pero **el SVG es la fuente**, y dibujarlos aparte sería una segunda versión del ícono
que nadie se va a acordar de actualizar.

En la máquina no hay ningún rasterizador de SVG: ni ImageMagick, ni Inkscape, ni cairosvg. Lo
que sí hay es el venv del backend, con **WeasyPrint** —que vino con el PDF del comprobante— y
**pypdfium2**, que viene de arrastre con él. WeasyPrint dibuja SVG y pypdfium2 rasteriza PDF,
así que el camino SVG → PDF → PNG usa dos dependencias que ya estaban en vez de sumar una
tercera solo para esto. Se corre desde `backend/` con su propio Python:

```powershell
cd E:\Capacitacion\InSoft\FactuMov\backend
.venv\Scripts\python.exe ..\frontend\scripts\render_icons.py
```

La página del PDF se arma del tamaño del `viewBox` en puntos y el escalado se hace al
rasterizar, así que cada tamaño se dibuja de nuevo desde las curvas y no es el chico agrandado.

#### El acento de la SPA es verde, pero no *el* verde
`--accent` pasó de `#1f6feb` —el default del scaffold— a `#15803d`, y que no sea ninguno de
los dos verdes de la marca es a propósito. `--accent` es el color de **todos los links** y el
fondo de los botones primarios con texto blanco encima, o sea texto: necesita 4,5:1. El
`#2EBD59` de la marca da 2,5:1 contra el blanco y el `#1B9E4B` da 3,5:1 — los dos reprueban.
`#15803d` es el mismo tono bajado hasta 5,0:1 contra el blanco y 4,7:1 contra el fondo de la
página. El verde de la marca sigue vivo tal cual adentro de los SVG, que es donde es un dibujo
y no un texto.

`--ok` (`#1e7f4f`) quedó como estaba. Ahora es casi el mismo verde que el acento, y no molesta:
el aviso de "Guardado" es una caja de fondo pálido con texto oscuro y el botón primario es un
rectángulo lleno — se distinguen por la forma y no por el color, y que los dos verdes sean de
la misma familia es mejor que el verde contra azul de antes.

#### Dónde aparece la marca
- **`components/BrandMark.tsx`** tiene las dos piezas: `BrandMark` —el ícono con "FactuMov" al
  lado— e `InSoftCredit` —"Una app de" más el logo de la casa, linkeado a insoft.net.ar—. Es un
  `<img>` al SVG de `public/` y no un SVG inline, porque el mismo archivo lo usan el favicon,
  el manifest y el script de los PNG: copiar el dibujo adentro del componente crearía una
  cuarta versión.
- **`components/PublicLayout.tsx` es una ruta de layout** que envuelve a las cinco pantallas
  sin sesión, con la marca arriba y el crédito de InSoft abajo. Es layout y no un componente
  que cada pantalla incluya, por el mismo motivo por el que `RequireAuth` envuelve al grupo:
  la regla escrita una vez no se puede olvidar en la pantalla que se agregue mañana.
- **El logo de InSoft va en las pantallas sin sesión y no en la barra de arriba.** Adentro de
  la app la marca que importa es la de FactuMov —es la pantalla que se abre cien veces por
  semana— y al que ya entró no hace falta recordarle de quién es esto. El lugar donde esa
  pregunta sí existe es antes de entrar.
- **El `<img>` del logo de InSoft va a 40 px y no a los 22 del renglón**: el SVG de la casa
  trae su propio margen adentro del `viewBox` —el dibujo ocupa 70 de sus 160 de alto— así que
  se ve a poco menos de la mitad de lo que mide el `<img>`.
- **El `<h1>` del login dejó de decir "Entrar a FactuMov"** y dice "Entrar". Con el nombre
  arriba en la marca, la otra mitad era el mismo nombre dos veces en dos renglones seguidos.

#### El manifest, sin service worker
`manifest.webmanifest` con nombre, descripción, `start_url`, `display: standalone`, el
`background_color` del fondo de la página y el `theme_color` **del blanco de la barra de
arriba**, que es lo que queda pegado a la barra del sistema cuando corre instalada.

**No hay service worker, y eso significa que la app todavía no anda offline.** Con el manifest
alcanza para que Android ofrezca "agregar a la pantalla de inicio" y para que el ícono sea el
correcto; el prompt de instalación de Chrome en escritorio sí pide un service worker. Sumarlo
es su propia unidad —hay que decidir qué se cachea y cómo se invalida— y no bloquea nada.

#### Lo que quedó abierto
- **El PDF del comprobante sigue sin ninguna marca** (`templates/invoice.html`). Es lo que ve
  el cliente del usuario, no el usuario, y el emisor es el contribuyente y no FactuMov, así que
  es **decisión de Miguel** y no un olvido. Lo razonable es a lo sumo un pie chiquito.

### Producción
Balance360 ya está en producción y su `docs/DEPLOYMENT.md` es la plantilla: **VM Ubuntu 24.04
con todo en `docker-compose.prod.yml`** (servicio `db` sin puerto publicado + servicio `app`
construido con el `Dockerfile` del repo), y **`srv-nginx` en `192.168.100.9`** terminando el
HTTPS y proxeando por HTTP al 8000 de la VM. El `.env` de producción vive solo en la VM.
Balance360 está publicado en `balance360.insoft.net.ar`, así que FactuMov va en
`factumov.insoft.net.ar`.

**Va en la misma VM que Balance360** (decidido el 2026-08-27). Miguel puede armar las que
hagan falta; la pregunta era si una segunda aporta algo, y aporta poco: Compose ya aísla lo
que se puede aislar —red propia, Postgres propio, volúmenes propios— así que lo único
realmente compartido es el kernel, el disco y la RAM. Una VM aparte compra que un deploy de
FactuMov no pueda tumbar a Balance360, y eso Compose ya lo compra casi entero. Lo que cuesta
sí es concreto: otro host que parchear, otra copia de los certificados de ARCA en disco, otra
rutina de backup y un segundo lugar donde mirar cuando algo anda mal.

- **Balance360 se queda con el 8000**, así que FactuMov publica otro puerto — 8001 — y es el
  contenedor nginx el que lo publica, no el `app`.
- **Antes de empezar hay que mirar el espacio y la memoria de la VM** (`df -h`, `free -h`).
  Son dos Postgres y dos apps Python con WeasyPrint; el modo de falla compartido que queda es
  justamente el disco lleno, y llenarlo se lleva puesta la contabilidad de Balance360.
- Se revisa si FactuMov empieza a tener carga propia, o el día que convenga poder reiniciar
  una sin tocar la otra.

Lo que FactuMov necesita y Balance360 no tenía:

- **Hay una SPA que servir, no solo una API.** Balance360 es HTMX, o sea que su contenedor
  contesta HTML y listo. Acá hay un `dist/` estático y un backend JSON, y **el prefijo `/api`
  lo inventa el proxy de Vite**: el backend no sabe nada de él (`rewrite` en
  `vite.config.ts`). En producción eso lo tiene que hacer alguien, y hay dos formas:
  - **nginx en `srv-nginx` con dos `location`** — `/api/` proxeado a la VM con la barra final
    que come el prefijo, y `/` sirviendo el `dist`. Es lo que el comentario de
    `vite.config.ts` dice que imita el proxy, pero obliga a subir el `dist` a `.9` en cada
    deploy, o sea un segundo camino de publicación al lado del de la VM.
  - **un contenedor nginx más en el compose de la VM**, que sirve el `dist` y proxea `/api` al
    `app`. El deploy sigue siendo un solo `git pull` + `up -d --build`, y `srv-nginx` no
    necesita saber de FactuMov más que "proxeá todo a la VM". **Es la que conviene**, y de
    paso es donde va el `client_max_body_size`.
  - El `dist` se puede construir en el mismo Dockerfile con una etapa `node`, así el deploy no
    depende de que alguien se acuerde de correr `npm run build`.
- **`client_max_body_size`** cierra el pendiente que dejó anotado el endpoint de importación:
  el guard de `MAX_UPLOAD_BYTES` acota lo que el proceso parsea, no lo que el server ingiere.
- **`--proxy-headers` y `--forwarded-allow-ips` en uvicorn.** Sin eso `request.client` es el
  proxy y **todos los usuarios comparten un solo cubo** en el rate limiter — ver *Rate
  limiting*, que decidió leer `request.client` justamente porque esa reescritura es
  responsabilidad de uvicorn.
- **`limit_req` en nginx**, porque el limitador en memoria es un piso por worker y no un techo.
- **El `.env` de producción**: `APP_BASE_URL` con el dominio real y `https://` (de ahí cuelgan
  los links de los mails), `SMTP_*` reales, `OPERATOR_EMAIL` —que hoy es lo único que avisa que
  alguien está esperando que aceptemos su designación en ARCA— y `ARCA_WSDL_CACHE_PATH` en un
  volumen, o cada deploy vuelve a bajar los WSDL.
- **`ARCA_ENV`: la decisión más cara de todas.** En `prod` cada emisión es un comprobante con
  validez legal y no hay vuelta atrás — ver *Emisión con CAE*. El default es `homo` a
  propósito. Los certificados de producción del `20182810674` ya existen y son los que usa
  Balance360; van montados como volumen de solo lectura igual que allá
  (`./certs:/app/certs:ro`, excluidos de la imagen por el `.dockerignore`). **Se sale con
  `homo` y el pasaje a `prod` es un paso aparte y deliberado** — confirmado por Miguel el
  2026-08-27. Estar en producción y estar emitiendo de verdad son dos hitos distintos, y
  juntarlos hace que la primera prueba contra el server sea también la primera factura
  irreversible.
- **Las dos apps no pueden compartir el certificado de producción, y eso hay que resolverlo
  antes del pasaje a `prod`.** WSAA se niega a emitir un TA nuevo mientras el anterior siga
  vigente —es el "El CEE ya posee un TA valido" que los dos proyectos ya tienen documentado— y
  cada app cachea el suyo en **su propia** tabla `arca_tickets`, en **su propia** base. O sea
  que Balance360 y FactuMov pidiendo un TA de `wsfe` con el mismo certificado se lo van a
  arrebatar mutuamente, y el que pierde queda afuera de ARCA hasta doce horas. No es teórico:
  es exactamente la falla contra la que FactuMov puso el advisory lock, solo que el candado
  vive adentro de una app y estas son dos.
  - **Hoy no pasa** porque FactuMov va a `homo` y Balance360 está en `prod`: son sistemas
    separados, con certificados separados. La colisión aparece el día del cambio, que es lo
    que la vuelve fácil de no ver venir.
  - **La salida esperada es un certificado propio para FactuMov**, del mismo CUIT
    `20182810674`. La delegación es al CUIT, así que las que ya nos otorgaron siguen valiendo;
    lo que hay que hacer es habilitarle a ese certificado nuevo los servicios (WSFE y
    `ws_sr_constancia_inscripcion`), que es el mismo trámite que ya está documentado en *ARCA*.
  - **Falta confirmar que un certificado distinto obtiene su propio TA.** El nombre del error
    dice CEE —el certificado— y no el CUIT, así que todo apunta a que sí, pero es la premisa
    entera de la salida y conviene verificarla en homologación antes de depender de ella. Si
    resultara que el TA es por CUIT y servicio, las opciones son que las dos apps compartan un
    cache de tickets —acoplarlas, feo— o que FactuMov emita bajo un CUIT propio.
- **Backups.** Hoy no hay ninguno de FactuMov. La sección 4 del `DEPLOYMENT.md` de Balance360
  sirve tal cual.
- **El barrido de delegaciones no necesita nada especial**: vive en el `lifespan` y con N
  workers barre uno solo, por el `pg_try_advisory_xact_lock`.

### La landing
La tarjeta de FactuMov va en `#productos`, al lado de Balance360 y Gastin, y **la entrada en el
lanzador de apps del header** (`.apps-panel`), que es donde el usuario que ya la conoce va a
buscarla. Las dos con el mismo criterio que ya usa la página: un `chip` de estado ("En
producción" / "Beta") y un `.go` con el link.

- El texto tiene que decir qué hace en una línea, en el registro de las otras dos ("Tus
  finanzas completas en un solo lugar…"). Algo de la forma "Facturá desde el celular en dos
  toques: importás una factura, la guardás como modelo y emitís con CAE".
- Las capturas van como PNG al lado del HTML y **hay que sumarlas al `scp.ps1`**, que lista los
  archivos a subir uno por uno y no sube lo que no esté nombrado.
- La landing no tiene git. Antes de tocarla, copia de respaldo — el `scp.ps1` ya guarda un
  `index.html.bak` **del lado del server**, que es la única red que hay.

## Notas
- Este archivo es un documento vivo — editalo a medida que el proyecto avance.
- Convenciones de código, estructura de carpetas y decisiones técnicas que se vayan
  tomando en las sesiones de Code deberían agregarse acá para que persistan.
