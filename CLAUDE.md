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
│   │       ├── invoice_parser.py   # PDF → ParsedInvoice
│   │       └── invoice_draft.py    # ParsedInvoice → InvoiceTemplateDraft
│   └── tests/
│       └── samples/                # 10 facturas PDF reales (1 A, 4 B, 5 C)
│           └── unsupported/       # otros layouts, fuera del glob de los tests
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

**Actualización 2026-08-26:** apareció un servicio que no estaba en el relevamiento original,
`padron.py` — consulta al padrón de ARCA (`ws_sr_constancia_inscripcion`) para completar un
contacto a partir del CUIT. Ya está portado (ver *ARCA*). Al 2026-08-26 están portados
`arca.py`, `padron.py` y la mitad de consulta de `wsfe.py`; falta `FECAESolicitar`, que es la
unidad de emisión.

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
| Identidad / relaciones | `entity_id`, `fiscal_identity_id`, receptor, `voucher_type`, `pos`, `concepto` | ✅ Sí — es lo que define al modelo |
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
| `FiscalIdentity` | Emisor: CUIT, razón social, condición IVA, IIBB, domicilio, estado de la delegación |
| `Customer` | Receptor |
| `InvoiceTemplate` | Emisor + cliente + tipo de comprobante + punto de venta + concepto |
| `InvoiceTemplateLine` | Descripción, cantidad, precio unitario, alícuota, posición |
| `User` | Cuenta: email, hash de contraseña, confirmación, alta/baja |
| `UserSession` | Sesión abierta: hash del token, vencimiento absoluto, revocación |
| `EmailConfirmation` | Token de confirmación de email, de un solo uso |
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
| `crud/email_confirmation.py` | Tokens de confirmación |
| `services/email.py`, `services/notifications.py` | Transporte SMTP y textos de los mails |
| `services/rate_limit.py` | Contador de ventana fija en memoria |
| `routers/auth.py` | `login`, `logout`, `/me`, `register`, `confirm`, `resend-confirmation` |

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
Los mails van en `BackgroundTasks`, y **en FastAPI 0.141 los background tasks corren antes
del cierre de las dependencias con `yield`** — o sea antes del `db.commit()` de `get_db`.
Está medido, no supuesto. Sin un `commit` explícito en el endpoint pasan dos cosas:

1. el mail sale con un token que todavía no está en la base, y si la transacción termina
   abortando el usuario recibe un link que nunca va a funcionar;
2. la transacción queda abierta durante toda la conexión SMTP, hasta
   `SMTP_TIMEOUT_SECONDS`. Diez segundos de transacción abierta por registro es el más caro
   de los dos problemas.

Por eso el router commitea, contra la convención del proyecto de que eso es trabajo de
`get_db`. El segundo commit de `get_db` no tiene nada que escribir, y en los tests el
`join_transaction_mode="create_savepoint"` del fixture `db` hace que este commit cierre un
savepoint y el rollback siga revirtiendo todo. El test que lo protege mira el **orden** y no
el resultado, que es lo único que distingue este caso: ningún otro test nota que la línea
falte.

#### Mail: dónde vive cada cosa
| Archivo | Rol |
|---|---|
| `services/email.py` | Transporte: `EmailSettings`, SMTP, STARTTLS, timeout |
| `services/notifications.py` | Contenido: asunto y cuerpo de los tres mails |

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
- **`ARCA_DELEGATE_TAX_ID` tiene como default un placeholder legible**, "(CUIT de FactuMov,
  a completar)", y no un CUIT plausible: el certificado todavía no existe, y un número falso
  bien formado saldría en el mail sin que nadie lo mire dos veces. **Pendiente para cuando
  exista.**

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
- **Cuatro limitadores, dos ejes.** Por IP: login 10 cada 15 min, registro y reenvío 5 por
  hora. Por dirección: 3 por hora, **compartidos entre registro y reenvío**, porque los dos
  le mandan mail a la misma casilla y presupuestos separados dejarían duplicar el bombardeo
  alternando endpoints. El login es el más holgado a propósito: el que se equivoca de
  contraseña de verdad reintenta varias veces seguidas.
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

### Unidades pendientes, en orden
Cerradas el 2026-08-26: la capa HTTP de autenticación (login, logout, `/me`,
`dependencies.py` y los tres routers protegidos), el *ownership scoping*, el registro con
confirmación por email con su rate limiting, y la **integración con ARCA** (verificación de
delegación + consulta al padrón) — ver la sección *ARCA*.

1. **Reset de contraseña.** Lo pide el registro: quien se equivocó de contraseña en una
   cuenta sin confirmar no tiene hoy ninguna salida, porque re-registrarse a propósito no
   la pisa.
2. **Emisión con CAE** (`FECAESolicitar`). Es la mitad de `wsfe.py` que todavía no se
   portó, y ahora es lo único que separa a la app de emitir de verdad.
3. **Segundo layout del parser** — ver *Parser → Pendiente: un segundo layout*. Va último
   porque no bloquea nada: hoy el usuario puede cargar el modelo a mano.

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
- **Pendiente:** `EmailSettings.arca_delegate_tax_id` sigue con el placeholder. Cuando el
  certificado exista, ese valor tiene que salir de `get_certificate_tax_id()` y no de una
  variable, para que el CUIT del mail y el que ARCA autoriza no puedan discrepar. El
  endpoint de verificación ya lo lee del certificado; el mail todavía no.

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
  que la columna dice "esto era verdad en esta fecha", no "esto es verdad".

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
  Balance360 (`certs/homo.crt`, `certs/balance360.key`) sirven para probar la cadena entera,
  con la salvedad de que verifican la delegación de Miguel contra sí mismo: no ejercitan una
  delegación de un tercero, que es el caso real de FactuMov.

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

## Notas
- Este archivo es un documento vivo — editalo a medida que el proyecto avance.
- Convenciones de código, estructura de carpetas y decisiones técnicas que se vayan
  tomando en las sesiones de Code deberían agregarse acá para que persistan.
