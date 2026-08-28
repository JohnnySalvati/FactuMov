# FactuMov — Emisión con CAE y envío

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

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

