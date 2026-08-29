# FactuMov — Autenticación

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

## Registro y delegación en ARCA — decisión de producto
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

## Registro self-serve
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

## El login no revela si un email está registrado
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

## Sesiones
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

## Dónde vive cada cosa
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

## Capa HTTP (2026-08-26)
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

## Tests de autenticación
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

## Registro y confirmación por email (2026-08-26)
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

### El `commit` explícito antes de mandar el mail
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

### El aviso de que alguien se registró (2026-08-28)
Cada alta nueva le manda un mail a `OPERATOR_EMAIL`. Pedido por Miguel: hoy, para enterarse de
que alguien empezó a usar FactuMov, hay que entrar a la base — que es la peor forma posible de
seguir el único número que importa en una app recién publicada.

- **Sale del registro y no de la confirmación**, o sea que avisa de una cuenta que todavía no
  se puede usar. Es a propósito: el que se registró y no confirmó también es información, y es
  la mitad interesante —alguien entró, quiso, y quedó a mitad de camino—. El cuerpo lo dice con
  todas las letras para que nadie lea "usuario nuevo" donde dice "intento".
- **Solo cuando aparece una fila que no estaba.** Las otras dos ramas de `register` —dirección
  sin confirmar que se vuelve a registrar, dirección ya confirmada— no son alguien
  registrándose: son alguien volviendo.
- **En `BackgroundTasks` y best effort, y acá eso es parte de la seguridad, no una costumbre.**
  `register` contesta lo mismo exista o no la dirección, y las tres ramas mandan un mail
  justamente para que las tres puedan fallar igual. Un envío sincrónico de más en una sola de
  las tres la haría tardar el doble que las otras dos, y el reloj contestaría la pregunta que
  el 202 idéntico se cuida de no contestar — el mismo oráculo que el hash de Argon2 evita
  hasheando antes de mirar la base. Corriendo después de la respuesta, la rama nueva no se
  distingue de las otras; y si el mail no sale, el registro ya ocurrió igual.
- **Sin `OPERATOR_EMAIL` queda un INFO en el log**, no un WARNING. Es la diferencia con el
  aviso de la delegación: allá hay una persona esperando un click que nadie va a dar, acá no
  hay nada pendiente. La línea nombra la variable, que es lo único que hace falta saber para
  prenderlo.
- **Es el segundo mail de la app que no le va a un usuario.** El otro es el de la designación
  pendiente en ARCA — ver *ARCA → La designación que hay que aceptar a mano*.

### Mail: dónde vive cada cosa
| Archivo | Rol |
|---|---|
| `services/email.py` | Transporte: `EmailSettings`, SMTP, STARTTLS, timeout, `send_email` / `send_email_best_effort` |
| `services/notifications.py` | Contenido: asunto y cuerpo de los mails, y cuál de los dos transportes usa cada uno |

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

### `generate_opaque_token` / `hash_opaque_token`
Antes se llamaban `*_session_token`. La mecánica es la misma para la sesión y para la
confirmación —256 bits de `secrets`, guardados como SHA-256— y el nombre no tenía nada de la
sesión adentro. Un segundo par idéntico con otro nombre habría sido peor que el rename.

### Tests
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

## Rate limiting (2026-08-26)
Cierra el registro: la documentación ya decía que el rate limiting está en el camino crítico del
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

## El fallo de SMTP se ve (2026-08-27)
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

## Reset de contraseña (2026-08-27)
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

