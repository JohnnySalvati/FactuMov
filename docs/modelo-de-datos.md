# FactuMov — Modelo de datos

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

**Principio rector.**
Un `InvoiceTemplate` es una `Invoice` **menos todo lo que cambia en cada emisión**. Los
campos de `Invoice` de Balance360 se parten en tres grupos:

| Grupo | Campos | ¿Va en el template? |
|---|---|---|
| Identidad / relaciones | `entity_id`, `fiscal_identity_id`, receptor, `pos`, `concepto` | ✅ Sí — es lo que define al modelo |
| Derivados | `voucher_type` | ❌ No — sale de los dos anteriores; ver *La letra del comprobante* |
| Contenido | líneas (descripción, cantidad, precio, alícuota) | ✅ Sí — se ajusta al emitir |
| Hechos de la emisión | `date`, `number`, `cae`, `cae_expiry`, `confirmed`, `paid`, `authorized`, `from_date`/`to_date`/`due_date` | ❌ No — los asigna ARCA o el momento de emisión |

Emitir = tomar un `InvoiceTemplate`, permitir retoques, y crear una `Invoice` nueva.

## Desviaciones deliberadas respecto de Balance360
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

## Tablas del modelo
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
| `Subscription` | El plan de la cuenta: estado, hasta cuándo llega lo pagado y el id del otro lado. **No guarda el plan efectivo** — se deduce; ver [`monetizacion.md`](monetizacion.md) |
| `ArcaTicket` | Ticket de acceso de WSAA, por entorno y servicio. La única tabla sin dueño |

## Decisiones sobre `InvoiceTemplate` (2026-08-15)
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
- **`email_subject` y `email_body` son nullable y sin `server_default`** (2026-09-01, migración
  `d7f3b0c81a95`). `NULL` no significa "sin texto" sino "el mail que la app manda desde
  siempre", que es lo que tienen todos los modelos anteriores a las columnas; un
  `server_default` con el texto de hoy le congelaría a cada fila una copia que dejaría de
  actualizarse el día que se corrija la redacción. El texto se lee en vivo al enviar y no se
  copia a la factura — ver *Emisión y envío → El texto del mail vive en el modelo*.

## La letra del comprobante se deduce (2026-08-26)
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

