# FactuMov — Parser de PDF e importación

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

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

