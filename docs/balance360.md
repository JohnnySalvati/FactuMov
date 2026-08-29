# Integración con Balance360

FactuMov emite el comprobante y Balance360 lo asienta en la contabilidad. Es para los usuarios
que tienen las dos apps: la factura que salió con CAE acá aparece allá como comprobante de
venta, sin volver a cargarla a mano.

Toca las dos aplicaciones. Del lado de Balance360 el detalle está en su propio `CLAUDE.md`, en
*Registro de comprobantes de FactuMov*; acá está lo de este lado y las decisiones del contrato,
que son de las dos.

## Las tres decisiones que dan forma a todo

**Empuja FactuMov.** Es FactuMov el que llama a `POST /api/invoices/issued` de Balance360, y no
Balance360 el que viene a buscar. La alternativa —que Balance360 consulte cada tanto— obligaba
a abrir FactuMov a un cliente externo, a inventarle un endpoint de listado por fecha y a que
alguien decidiera cada cuánto preguntar. Empujando, el evento existe: se emitió una factura.

**Solo el comprobante, impago.** Lo que se copia es la factura con su CAE, su letra, su número
y sus líneas. **No se crea ningún movimiento de dinero.** El cobro es otro hecho, con otra
fecha y a veces en otra moneda, y adivinarlo desde la emisión sería inventar un pago que no
ocurrió. Se registra en Balance360 cuando pasa, como cualquier otro.

**Después de emitir, desacoplado.** El CAE se pide y se guarda exactamente como antes; el
registro ocurre después, en un `BackgroundTask`, y cada factura lleva su propio estado. Es la
decisión más importante de todas: **una emisión no puede fallar porque Balance360 esté caído.**
Cuando el registro corre, ARCA ya autorizó un comprobante irreversible; hacer que la respuesta
del `/emit` dependa de que la otra app conteste convertiría una app caída en un CAE huérfano
del que el usuario nunca se entera.

## El estado del registro

Cuatro columnas en `invoices` (`balance360_status`, `balance360_invoice_id`,
`balance360_error`, `balance360_synced_at`) y no una tabla aparte: es uno a uno con la factura,
no hay historia que guardar —importa el último intento— y sacarlas afuera obligaría a un join
en la grilla, que es justo donde se muestra el indicador.

`balance360_status` es nullable y **`NULL` es un cuarto estado, el más común**: la factura se
emitió sin la integración conectada y nunca entró al circuito. No es `FAILED` —no falló nada— ni
`PENDING` —no hay nada esperando—, y la pantalla no muestra ningún indicador. Que sea la
ausencia de valor es además lo que deja la consulta de reintentos (`PENDING` o `FAILED`) sin
arrastrar todo el historial: sin eso, el botón de "reintentar lo que falló" sería un botón de
"registrar retroactivamente todo lo que emití en mi vida", que es una decisión del usuario.

## La conexión: una por usuario

`balance360_connections` tiene un `unique` sobre `user_id`. Alcanza una porque **del otro lado
el token *es* un usuario**: Balance360 deduce a qué entidad va cada comprobante buscando el CUIT
del emisor entre las entidades de las que el dueño del token es miembro. Un token cubre todos
los CUIT de la persona, y tener uno por identidad fiscal sería pedir N veces la misma credencial
para que el ruteo lo siga haciendo el CUIT igual.

Queda un caso sin resolver **a propósito**: el mismo CUIT ligado a dos entidades de Balance360
en las que el usuario está. Ahí la otra app no puede elegir y contesta que se elija; el contrato
acepta una entidad explícita pero acá no hay dónde guardarla. Una tabla de mapeo CUIT → entidad
se agrega el día que el caso exista: hoy serían una tabla, una pantalla y una migración a cuenta
de una situación hipotética, y mientras tanto el mensaje de Balance360 llega entero a la
pantalla y explica qué hacer.

## El token va cifrado, no hasheado

Es la excepción a `services/security.py`. La contraseña, el token de sesión y el de confirmación
se guardan hasheados porque nunca hay que recuperarlos: llega uno, se hashea y se compara. El de
Balance360 hay que **mandarlo** en cada request, así que hashearlo lo volvería inservible.

En texto plano tampoco: en Balance360 el token vive hasheado, o sea que la base de FactuMov es
el único lugar del mundo donde existe en forma usable. Un dump entregaría acceso de escritura a
la contabilidad de cada usuario conectado. Cifrarlo mueve el secreto de la base al entorno del
proceso.

Fernet, de `cryptography`, que ya es dependencia por el certificado de ARCA: trae AES-CBC con
HMAC ya combinados y la parte que se suele hacer mal —el modo, el IV, la autenticación— no queda
de nuestro lado. La clave es `SECRET_ENCRYPTION_KEY`.

**Sin la variable la app arranca igual**, como con el mail: lo único que no funciona es esta
pantalla, que lo dice antes de que alguien escriba una credencial (`available: false`) — y lo
dice antes de salir a la red, así que una contraseña que no se va a poder guardar tampoco llega
a viajar. Y perder la clave no es una catástrofe: los tokens guardados dejan de abrirse y cada
usuario vuelve a conectar, que emite otro y revoca el que quedó ilegible.

## El contrato

### Los enums viajan por nombre

`CondicionIva.FINAL` vale **5 acá y 6 en Balance360** —los códigos de FactuMov se corrigieron
contra la tabla de ARCA el 2026-08-27 y los de allá todavía no— y el valor de `IvaAliquot` es
directamente el código de ARCA de este lado. Por valor, un consumidor final entraría del otro
lado como monotributista **sin ningún error**: el 6 es un valor válido de las dos tablas y nadie
se enteraría hasta ver el libro de IVA.

Por nombre eso no puede pasar: `FINAL` es `FINAL` de los dos lados, un nombre que no existe
explota en la validación, y el día que se corrijan los códigos de allá el contrato no se entera.
Vale para `condicion_iva`, `doc_type` e `iva_aliquot`. `voucher_type` y `concepto` van por valor
porque su valor **es** el nombre legible ("A", "products") y coincide.

### Los importes viajan como texto

`str(Decimal)` y no un número. `json` serializa un float, y ahí 0,1 deja de ser 0,1; del otro
lado pydantic lo lee como `Decimal` exacto, que es lo que después tiene que cerrar contra el CAE
al centavo.

### El precio no se traduce de este lado

FactuMov guarda el precio **tal como se carga**: neto en la A, con el IVA adentro en la B y en
la C. Balance360 guarda siempre el neto. La traducción ocurre **allá**, en su
`services/issued_invoice.py`, y es al revés de lo que parece natural: si tradujera el que llama,
cambiar algo del modelo de datos de Balance360 obligaría a redeployar FactuMov.

Esa traducción es también lo que obligó a ampliar `invoice_lines.unit_price` de Balance360 a
cuatro decimales: una B de $100 al 21% tiene neto 82,6446… y con dos decimales el total vuelve a
dar 99,99 o 100,01. Contra un CAE eso no es un redondeo, es un comprobante distinto.

### Los totales viajan para ser verificados

Balance360 no tiene columnas de total: los deriva de las líneas. Los tres números que se mandan
no se guardan en ningún lado — se comparan contra lo que dan las líneas recién creadas, y si no
coinciden **no se registra nada**. Es la única forma de que un error de traducción de precios se
note en el momento y no en la declaración mensual. Mejor un comprobante que falta que uno
cargado con otro total.

### Idempotencia por el id de la factura

El `id` de la factura de FactuMov viaja como `external_id` y Balance360 tiene un unique sobre
`(external_source, external_id)`. Reintentar devuelve el comprobante que ya estaba en vez de
duplicarlo — y por eso el botón de reintentar no tiene confirmación, al revés del de emitir.

## Los caminos

**Automático, al emitir.** Si hay conexión con `auto_register`, `/emit` marca la factura
`PENDING`, commitea, contesta el 201 y recién ahí corre el `BackgroundTask`. La tarea recibe
**ids y no objetos**: cuando corre, la sesión del request ya se cerró.

**Manual, por factura.** `POST /invoices/{id}/register` es el botón que aparece al lado del
error, para cuando el usuario cargó el CUIT que faltaba del otro lado. **Contesta 200 ande o no
ande**: el resultado del intento no es el resultado del request, y la factura vuelve con su
estado y su motivo adentro. Un 502 obligaría a la pantalla a leer el error de dos lugares.

**Manual, en lote.** `POST /balance360/register-pending` reintenta todas las `PENDING` y
`FAILED`. Existe porque el modo normal de fallar de esto es en lote —Balance360 estuvo caído una
tarde— y **sigue de largo cuando una falla**: los errores no son homogéneos, así que cortar en
la primera dejaría el resto sin intentar por un problema que no las toca.

## `register` no levanta nunca

`services/balance360.register` convierte cualquier fallo en un estado de la factura. Es la misma
política que `send_email_best_effort` y por el mismo motivo: acompaña a una operación que ya
terminó, no es el producto de ningún request. El `register_in_background` además atrapa
`Exception` a secas y loguea — corre fuera del ciclo del request, así que una excepción que suba
ahí no la ve nadie y puede terminar tirando el worker abajo por una copia contable que se
reintenta con un botón.

El mensaje de error que se guarda es **el que dio Balance360**, entero: "el CUIT no está
cargado", "elegí una entidad". Está escrito para que lo lea un usuario y es lo único que le dice
qué arreglar; reescribirlo acá sería perder la única información accionable. Se recorta a 300
caracteres al guardarlo, para que un fallo de registro no se convierta en un fallo al *guardar*
el fallo.

## Lo que se cerró del lado de Balance360

`/api` estaba **completamente abierto**: cualquiera con la URL leía y escribía toda la base. La
integración no podía sumarse a eso, así que en el mismo trabajo se agregaron `api_tokens` y
`get_api_user`, y todos los routers de `/api` pasaron a pedir credencial. Además el 401 y los
errores de dominio contestan JSON para `/api`: antes el 401 redirigía al login y un cliente que
seguía el redirect veía un 200 con HTML — habría creído que registró.

El token **se lo emite el usuario desde FactuMov**: `POST /api/tokens` de Balance360 recibe
mail, contraseña y un nombre, y devuelve uno nuevo. Es el único router de `/api` montado sin
`get_api_user` —es el que autentica— y por eso es también el único de esa app con límite de
intentos. El `create_api_token.py` sigue existiendo (`uv run python create_api_token.py <mail>
<nombre>`) y sale por pantalla una sola vez, para emitir a mano cuando hace falta.

Antes era el único camino, y ahí estaba el problema: conectar la integración dependía de que
alguien entrara por ssh al servidor de Balance360, o sea de quien administra la VM y no del
usuario que la quiere usar. Y el token, que es un secreto de escritura sobre la contabilidad,
tenía que viajar de esa persona al usuario por algún chat o algún mail.

**No caduca**: `api_tokens` no tiene expiración, solo `revoked_at`. Sigue valiendo hasta que
alguien lo revoque con `revoke_api_token.py`, que sin nombre los lista con su `last_used_at` y
con un nombre o un prefijo de id revoca ese. Es **por base** —dev y prod son dos Postgres
distintos, así que son dos tokens—, y hay que reemitirlo si se filtró, si se perdió el texto
plano, o si se perdió la `SECRET_ENCRYPTION_KEY` de acá: en ese caso el guardado deja de poder
abrirse y el original ya no existe en ningún lado. Volver a conectar desde Ajustes hace las dos
cosas de una.

Justamente porque no caduca, **emitir uno revoca el anterior con el mismo nombre**. FactuMov
manda siempre `"FactuMov"`, así que reconectar reemplaza en vez de acumular; sin eso, cada
reconexión dejaría viva una credencial de escritura que no usa nadie y que nadie va a acordarse
de apagar. Por nombre y no por usuario: apagarle todo lo que tenga emitido porque reconectó
FactuMov le rompería las otras integraciones sin avisarle.

## La pantalla

`/ajustes`, a la que se llega por el engranaje de la barra. No es una quinta pestaña: los
ajustes se tocan una vez y le cobrarían ancho a las cuatro que se usan todas las semanas. Y el
engranaje no cuelga del mail del usuario, que es donde estaría en un escritorio, porque en el
celular ese mail está oculto abajo de 640px — o sea justo en el caso principal.

**El token no vuelve nunca del backend**: lo único que sale es `token_hint`, los últimos cuatro
caracteres, que alcanzan para reconocer cuál está guardado. Un endpoint que devolviera la
credencial completa convertiría cualquier XSS en la SPA en un robo de acceso a la contabilidad,
y no compraría nada: quien la quiera cambiar vuelve a conectar y se emite otro.

**Se piden mail y contraseña, no un token.** El `PUT` los cambia por un token contra
`/api/tokens` de Balance360 y recién con lo que vuelve escribe la fila. Guardar y verificar
después dejaría al usuario con una conexión que la pantalla muestra como puesta y que falla en
silencio en cada emisión; acá el orden lo resuelve solo, porque lo que se guarda es el resultado
de esa llamada.

**La contraseña se usa una vez y no se guarda en ningún lado.** Ni en claro ni cifrada: no hay
columna donde pudiera terminar. Es lo único que hace aceptable pedirla — se la cambia por una
credencial acotada y revocable, que es exactamente el intercambio que `models/api_token.py` de
Balance360 describe como el motivo por el que los tokens existen. Guardarla sería peor que el
token pegado a mano: le daría a la base de FactuMov la cuenta entera de Balance360 de cada
usuario, y cortar la integración pasaría a ser cambiar la contraseña.

**Dos límites de intentos, y el que importa es el de allá.** Este endpoint está autenticado, así
que no es un oráculo de contraseñas de FactuMov — pero sí es un intermediario para probar
contraseñas de Balance360, así que conectar se limita a 10 por hora y por usuario. La defensa de
verdad es la de la otra app: cinco intentos por cuarto de hora **por dirección de mail**, que es
la clave correcta porque todos los pedidos legítimos llegan desde la misma IP, la del servidor de
FactuMov. Con un límite por IP, el primero que se pasara dejaría afuera a todos los demás.

**El 404 tiene mensaje propio.** Si la dirección contesta pero no conoce `/api/tokens`, del otro
lado hay un Balance360 anterior a este circuito. Decir "contestó 404" mandaría a revisar una
dirección que está bien; lo que hay que hacer es actualizar la otra app, o pedir un token a mano
mientras tanto.
