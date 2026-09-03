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

- **Al principio, un solo layout: ARCA "Comprobantes en línea".** Todas las facturas de
  Miguel salen de ahí. Se borraron los otros nueve layouts de Balance360: un regex que no
  se puede verificar contra un PDF real es un pasivo, no una función. Desde el 2026-09-02
  hay dos, y del segundo también hay PDFs reales — ver *Dos layouts* más abajo.
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

## Dos layouts (2026-09-02)
El parser lee dos generadores, y del segundo también hay facturas reales:

- **`arca`**: "Comprobantes en línea", el sitio de ARCA.
- **`factumov`**: el comprobante que imprime `services/invoice_pdf.py`, que es **el mismo
  que imprime Balance360** — el template de acá es un port del de allá y los dos salen
  iguales. Reimportar una factura propia es el caso natural: se emitió una en julio y en
  agosto se quiere volver a facturar lo mismo.

Antes el segundo no se leía. De `factura_A_00005-00000001.pdf` —una A de Miguel impresa por
Balance360— salían `pos`, `number`, `date`, CAE, IIBB y fecha de inicio, y nada más: sin CUIT
del emisor, sin receptor y sin líneas. No estaba roto nada; era otro generador:

| | Comprobantes en línea | El comprobante propio |
|---|---|---|
| Copias | ORIGINAL + DUPLICADO + TRIPLICADO | una sola, `Pág. 1/1` |
| CUIT | `20182810674` | `20-18281067-4`, con guiones |
| Columnas de items | `Código` `Producto/Servicio` `Cantidad` `U. Medida` `Precio Unit.` `% Bonif` … | `Producto/Servicio` `Cantidad` `Precio Unit.` `Subtotal` … |
| Importes | `35000,00` | `$ 35.000,00` |
| Vencimiento del período | `Fecha de Vto. para el pago:` | `Vto. para el pago:` |
| Tipo de comprobante | rótulo suelto | `COD. 01`, pegado a la razón social |
| Datos del emisor | un campo por renglón | varios por renglón (`Condición frente al IVA: … CUIT: …`) |
| Peso | ~86 KB | 19 KB |

### El registry es flaco a propósito
Es el registry de layouts que Balance360 tenía y que acá se había borrado, pero con la
diferencia que hacía a aquella decisión: de los dos hay PDFs contra los cuales verificar.

Lo que un `_Layout` guarda es **la tabla de items y la marca que lo identifica, y nada más**.
Los rótulos —"Razón Social:", "Condición frente al IVA:", "Período Facturado Desde:"— los
fija la RG 1415 y no el generador, así que la extracción del emisor y del receptor quedó
**una sola**: tener una copia por layout serían dos listas capaces de discrepar, y la segunda
se escribiría copiando la primera y cambiándole una palabra.

Donde los rótulos difieren en algo, la diferencia entró como una alternativa más en el mismo
patrón (`(?:Fecha de\s+)?Vto\. para el pago:`) y no como un patrón nuevo. **Cada alternativa
sale de un PDF que se leyó**; ninguna está puesta por las dudas, que es la regla que sigue
distinguiendo esto de los diez layouts heredados.

### Cómo se reconoce cuál es
Por una marca que está en **todo** comprobante de su generador, tenga items o no: ARCA
imprime el rótulo largo del receptor (`Apellido y Nombre / Razón Social`) y nunca pone
guiones en el CUIT; el comprobante propio hace exactamente al revés. Reconocerlos por el
encabezado de la tabla habría dejado sin identificar justo a los PDFs cuyas líneas no se
pudieron leer, que son los que más interesa ubicar.

Un generador desconocido cae en el de ARCA. Lo que sale de eso no es un error: las filas no
matchean, `needs_manual_items` queda en `True` y la UI ofrece carga manual — el mismo camino
que un PDF escaneado.

### Las dos columnas del encabezado se mezclan
El encabezado del comprobante son dos celdas lado a lado, y el texto que sale de pdfplumber
las intercala renglón por renglón: **qué campo de la derecha queda pegado a qué campo de la
izquierda depende de dónde cortó cada línea**, o sea del largo de la razón social y del
domicilio. Con una razón social larga, `Domicilio Comercial:` deja de terminar en `CUIT:` y
pasa a terminar en `Ingresos Brutos:`, o en nada.

Por eso ningún campo del encabezado termina en fin de renglón sino **en el rótulo
siguiente**, con la lista de rótulos posibles compartida (`_NEXT_LABEL`). Y por eso el
domicilio partido en dos renglones se rearma descartando de cada continuación lo que venga
pegado de la columna derecha, en vez de exigir que la continuación tenga una forma fija.

### Lo que ancla una fila de items es el `$`
El comprobante propio no imprime ni código, ni unidad de medida, ni bonificación: la fila es
`descripción cantidad $ precio $ subtotal`, más `alícuota% $ subtotal c/IVA` cuando es A. Sin
el `$` como ancla, una descripción terminada en número —"Instalacion 2", cantidad 1— se leería
como la descripción "Instalacion" y la cantidad 2: una línea plausible y equivocada. La cola
es opcional en vez de contarse por ancho como en ARCA, porque las dos columnas del IVA
existen solo en la A: o está la alícuota, o hay que caer en la de la letra.

### Una descripción larga se parte, y los números quedan en el medio
Cuando la celda de la descripción ocupa más renglones que las de los números, el generador
centra los números y **la fila con las columnas queda en el renglón del medio**: el principio
de la descripción está arriba y el final abajo. Ignorar lo de arriba dejaba la línea con la
mitad del texto, así que ahora también se junta hacia atrás.

Ahí aparece un choque: los restos del encabezado partido caen exactamente en el mismo lugar
—"IVA" abajo de "Alicuota" en ARCA, "UNIT. IVA IVA" abajo del título en el propio—. Se los
distingue porque **no tienen ni una minúscula**, que es lo que deja el `text-transform` del
encabezado, y una descripción escrita por el usuario no.

### La alícuota de Balance360 viene con punto decimal
Balance360 imprime la alícuota sin pasarla por ningún formateador: sale el `Decimal` crudo de
una columna `Numeric(5, 2)`, o sea `10.50%` y no `10,5%`. Con la regla argentina a secas —el
punto agrupa miles— eso se leía **1050**, `IvaAliquot.get_by_rate` no encontraba ninguna
alícuota con esa tasa y toda factura A de Balance360 perdía el IVA de sus líneas.

`_to_decimal` acepta ahora esa forma: **un punto seguido de una o dos cifras, en un número sin
ninguna coma, es una coma decimal**. Tres cifras después del punto siguen siendo miles, que es
lo que deja intacto a `2.805.000`.

### El `&nbsp;` del propio
El comprobante propio separa el punto de venta del número con `&nbsp;`, que sale del PDF como
U+00A0. `\s` lo matchea y `[ \t]` no, así que se lo normaliza a espacio apenas se extrae el
texto en vez de tener que acordarse de eso en cada patrón — y `[ \t]` hace falta en varios,
porque `\s` cruza el salto de línea y un rótulo vacío se llevaba el contenido del renglón de
abajo.

### Cómo se verifica
`factura_A_00005-00000001.pdf` dejó de estar en `samples/unsupported/` —esa carpeta ya no
existe— y entró al glob de `test_every_sample_parses_end_to_end` con sus valores fijados.

Pero la prueba que importa es otra: `test_invoice_parser.py` **imprime una factura con
`services/invoice_pdf.py` y la lee de vuelta**. Es más caro —hay que levantar weasyprint— y
es lo único que sigue diciendo la verdad el día que el template cambie. Un PDF nuestro
guardado en `samples/` envejecería sin que nada lo delate, y encima ese directorio está
gitignoreado: los PDFs son facturas reales y no viajan al repo, así que un test que dependa
solo de ellos no corre en ningún lado que no sea la máquina de Miguel.


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
- **El draft sí lleva la letra que leyó el parser (`voucher_type`, 2026-09-01)**, aunque no se
  guarde en ningún lado: el modelo la deduce del emisor y del receptor. Es lo que le dice al
  editor **cómo leer el `unit_price` que viene acá** —neto en A, con el IVA adentro en B y C—
  para sembrarlo en la columna que corresponde (ver [*El precio se carga sin IVA o con
  IVA*](frontend.md)). No alcanzaba con deducirla del par emisor/receptor: al importar la
  factura de un cliente que todavía no está en la cartera no hay par, y una A sembrada como si
  el precio trajera el IVA adentro se guardaba un 21% abajo. Va `None` cuando el PDF no dijo la
  letra, y ahí el editor asume IVA incluido.
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

