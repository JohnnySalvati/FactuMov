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
2. **`TimestampMixin` sin `created_by` / `modified_by`.** Los de Balance360 son FK a
   `users.id`; copiarlos tal cual obligaría a crear la tabla `users` antes de tiempo.
   Desde 2026-08-18 la tabla existe, así que el bloqueo se levantó — pero se siguen
   difiriendo hasta la unidad de *ownership scoping*, que es la que va a decidir de una
   vez qué columnas de usuario lleva cada tabla. Agregar la autoría antes sería una
   migración a cuenta de otra.
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
| `User` | Cuenta: email, hash de contraseña, confirmación, alta/baja |
| `UserSession` | Sesión abierta: hash del token, vencimiento absoluto, revocación |

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
| `routers/auth.py` | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |

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

### Unidades pendientes, en orden
La capa HTTP de autenticación quedó cerrada el 2026-08-26 (login, logout, `/me`,
`dependencies.py` y los tres routers protegidos).

1. **Ownership scoping.** `user_id` en `fiscal_identities` y `customers`, queries scopeadas,
   404 (nunca 403) sobre la fila de otro usuario, y scopear los lookups de `/import`, que
   hoy filtran si otro usuario ya tiene guardado un cliente dado.
2. **Registro + confirmación por email + el mail con las instrucciones de delegación.**
3. **Verificación de la delegación contra ARCA.**

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
- **El cliente de test es `httpx2`.** Starlette 1.5 importa `httpx2` primero y solo cae a
  `httpx` con un `StarletteDeprecationWarning`; la rama de fallback ya tiene un
  `RuntimeError` para cuando no esté ninguno. `httpx` igual sigue instalado porque
  `fastapi[standard]` lo requiere: es esperable, no un resto sin limpiar.

## Notas
- Este archivo es un documento vivo — editalo a medida que el proyecto avance.
- Convenciones de código, estructura de carpetas y decisiones técnicas que se vayan
  tomando en las sesiones de Code deberían agregarse acá para que persistan.
