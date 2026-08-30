# FactuMov — ARCA: WSAA, padrón y delegación

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

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
No en el `ticket_arca.json` del cwd que usa Balance360. Dos workers pidiendo un TA a la vez
gastan dos veces la cuota de WSAA para quedarse con un solo ticket útil, y un archivo en el cwd
de un contenedor no coordina eso ni sobrevive al deploy.

> **Corregido el 2026-08-29.** Acá decía que WSAA *se niega* a emitir un TA nuevo mientras el
> anterior siga vigente, y que por eso el segundo pedido dejaba a la app afuera de ARCA hasta
> doce horas. En producción emitió uno nuevo sin problema — ver *El ticket viejo miente*. La
> tabla sigue siendo lo correcto por las otras razones, que no dependían de aquella; lo que
> cambia es que renovar a mano dejó de ser algo que no se puede hacer.

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

### `GET /fiscal-identities/{id}/points-of-sale` (2026-08-29)
- **Existe porque el usuario no puede saber qué número poner.** El punto de venta se da de
  alta en ARCA, no en FactuMov, y el editor de modelos se lo pedía escrito con un `1` de
  default: acertaba solo por casualidad y, al parecer un valor ya elegido, hacía que ni se lo
  mirara. El que emitía con el punto de venta 5 se enteraba recién al pedir el CAE.
- **Es la misma llamada que `verify-delegation`**, leída entera. `FEParamGetPtosVenta`
  siempre devolvió la lista completa en `ResultGet.PtoVenta`; hasta ahora solo se le miraban
  los errores. Por eso los puntos de venta viajan adentro de `DelegationCheck`: parsear el
  payload de una llamada que ya se hacía no cuesta ni un ticket ni una ida a la red más.
- **Se descartan los bloqueados (`Bloqueado = "S"`) y los dados de baja (`FchBaja` con
  valor).** Ofrecerlos sería ofrecer un rechazo al pedir el CAE. `FchBaja` llega vacío de tres
  formas —`""`, `None` y `"NULL"`— y las tres significan que sigue vigente.
- **No se filtra por `EmisionTipo`.** El vocabulario exacto de ese campo depende del régimen
  con el que se dio de alta el punto de venta; descartar por un valor que no conocemos
  escondería uno que sí sirve. Viaja para mostrarlo al lado del número y desempatar.
- **Un número ilegible se saltea, no rompe la consulta.** Esto alimenta un desplegable: un
  dato que no se entiende tiene que costar un renglón de menos, no un 502.
- **Es GET y no POST**, al revés que `verify-delegation`, porque no escribe nada. Sellar
  `delegation_verified_at` de paso —la información está, sale gratis— se descartó por lo
  mismo que se documenta arriba: un GET con efectos lo repite solo un prefetch.
- **200 con `granted=false`** cuando falta la delegación y **200 con `points` vacío** cuando
  la delegación está pero el CUIT no tiene ninguno dado de alta. Son dos respuestas distintas
  y la pantalla las explica distinto; el 502 queda para "no se pudo preguntar".
- **Limitador propio, 60 por hora.** Compartir el de `verify-delegation` haría que armar
  modelos le comiera los turnos a la verificación, que es la que desbloquea al usuario nuevo.

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

### El alta de una identidad fiscal empieza por el CUIT (2026-08-28)
Pedido por Miguel. `GET /fiscal-identities/lookup/{tax_id}` y la pantalla `/identidades/nueva`
partida en dos pasos: se pide el CUIT, y la razón social, el domicilio y la condición frente al
IVA los trae el padrón de ARCA. Es el mismo servicio que ya usaba el alta de un cliente
(`services/padron.py`), del otro lado del mostrador.

- **El CUIT es lo único que el usuario sabe de memoria.** La razón social exacta y el domicilio
  fiscal tal como están registrados se tipean mal, y la condición frente al IVA se dice mal: de
  ella depende **la letra de todo lo que emita**. Anotarse monotributista cuando ARCA lo tiene
  como inscripto es emitir C donde iba A, y eso no se arregla después — se arregla con una nota
  de crédito, que FactuMov no emite.
- **No puede ser la única puerta**, misma regla que el "Empezar en blanco" de la importación de
  PDF: el padrón contesta 502 cuando ARCA no está —hoy mismo, mientras falte el certificado
  propio— y un CUIT recién inscripto puede no figurar. El fallo muestra qué pasó y ofrece
  "Cargarla a mano" con el CUIT ya tipeado. El botón de cargar a mano **aparece recién cuando
  el padrón falló**: ofrecerlo antes sería invitar a saltear el camino que trae los datos bien.
- **La condición frente al IVA ya no tiene valor por default.** El desplegable arranca en un
  placeholder y el `required` no deja guardar sin elegir. Antes venía con "Responsable
  inscripto" puesto, que es el mismo error que la app rechaza en todos lados: un valor plausible
  y equivocado en el campo del que cuelga la letra del comprobante.
- **Consumidor final vuelve como `null` y no como `CondicionIva.FINAL`.** Un emisor no puede ser
  consumidor final —`FiscalIdentityCreate` lo rechaza con 422 y el desplegable ni lo ofrece— así
  que devolverlo sería proponer un valor que el guardado va a rechazar, y la pantalla tendría
  que aprender a descartarlo. La decisión se toma en el borde: el CUIT que el padrón no muestra
  como emisor vuelve con la condición vacía y un aviso que dice por qué.
- **`iibb` y `start_date` no vienen del padrón, y no es un olvido.** Ingresos Brutos es
  provincial —Rentas, ARBA, AGIP— y ARCA no lo tiene. La fecha de inicio de actividades tampoco
  está como tal en la respuesta del A5: lo más parecido son los períodos de cada actividad, que
  dicen desde cuándo está registrada *esa* actividad. Deducirla de ahí daría una fecha creíble y
  equivocada, impresa en un comprobante fiscal.
- **El limitador se mudó de `routers/customer.py` a `services/padron.py`.** El presupuesto es
  uno solo: las dos pantallas hacen la misma llamada al mismo servicio contra el mismo
  certificado, así que un limitador por router dejaría gastar el doble alternando entre ellas —
  el mismo argumento por el que `verify-delegation` y `claim-delegation` comparten el suyo.
  Dejarlo en uno de los dos routers habría obligado al otro a importar de un router hermano, que
  es lo que el proyecto evita desde que `get_current_user` se mudó a `dependencies.py`. Hay un
  test que gasta la cuota por una pantalla y verifica que la otra recibe el 429.
- **El formulario conserva un botón "Traer del padrón" al lado del CUIT**, como el de clientes.
  Sirve para el CUIT que se tipeó mal en el primer paso y para la razón social o el domicilio
  que cambiaron desde que se cargó la identidad — que es la única forma que hay de enterarse,
  porque ARCA no avisa.

### La importación también pregunta al padrón (2026-08-28)
Pedido por Miguel. Cuando el PDF importado nombra un CUIT emisor que no está entre las
identidades del usuario, o un receptor que no está en la cartera, la pantalla ya no manda a
cargarlo a otro lado: **consulta el padrón sola, apenas se importa**, con los dos endpoints de
`lookup` que ya existían. El detalle de la pantalla está en *Frontend*; lo que importa acá es lo
que pasa con ARCA y con lo que se escribe.

- **No hay botón "Buscar en ARCA".** Fue el primer intento y Miguel lo bajó: es hacerle apretar
  un botón al usuario para averiguar algo que la app puede averiguar sola, en el medio de una
  tarea que ya empezó. La consulta sale al montarse la tarjeta.
- **El cliente se da de alta solo y se avisa después.** Es una fila en la agenda del propio
  usuario: se edita, se borra y no le dice nada a ARCA, así que el costo de equivocarse es un
  cliente de más en una lista y el de preguntar se paga en cada importación. El cartel dice qué
  se creó y **con los datos de quién**, que es la parte que no se puede omitir cuando el alta la
  hace la app sola.
- **La identidad fiscal no.** Declara "yo emito desde este CUIT": después FactuMov le verifica
  la delegación contra ARCA sola, y el PDF importado puede ser una factura **recibida**, donde
  el emisor es el proveedor. Darla de alta sola convertiría al proveedor en un emisor propio,
  elegido en el modelo, que además no va a poder emitir nunca. Ahí la consulta es automática y
  el alta la confirma un botón.
- **El receptor deja de darse de alta con lo que dice el PDF.** Ese texto sale de una factura
  ajena: la razón social viene cortada por el ancho de la columna y la condición frente al IVA
  es un rótulo impreso que puede estar viejo. El padrón es la fuente buena de las dos cosas, y de
  la condición depende la letra de todo lo que se emita después. Los datos del PDF siguen siendo
  el alta cuando no hay padrón que consultar —un DNI— o cuando ARCA no contesta, **y ahí el
  cartel es amarillo y lo dice**: no se puede dar de alta con datos de un PDF en silencio.
- **Un PDF puede gastar dos consultas sin que nadie apriete nada.** El presupuesto es de treinta
  por hora **por usuario** (`services/padron.py`), así que el que importa de a uno no lo va a
  ver nunca y el que importa cincuenta seguidos se queda sin turno a mitad de camino — y eso cae
  en el mismo camino que un 502: se da de alta con los datos del PDF y se avisa. Lo que la cuota
  protege es la cuota global del certificado, que es una sola para toda la app.
- **La consulta va detrás de una guarda de `useRef`.** StrictMode monta dos veces en desarrollo:
  sin eso, cada importación gasta dos consultas y —en el cliente, que además escribe— daría de
  alta la fila dos veces. Es la misma trampa que ya había costado el token de confirmación de
  mail, que es de un solo uso.
- **El 404 y el 502 no dejan sin salida**, misma regla que en las otras dos pantallas: el alta
  cae en los datos del PDF, y si el PDF tampoco los trajo completos queda el link a cargarlo a
  mano, avisando que irse descarta lo importado.
- **Comparar contra el PDF es parte de la respuesta.** Lo que trajo el padrón se muestra con lo
  que decía el PDF abajo **solo cuando difieren**: si coinciden es ruido, y si no coinciden es
  justo lo que el usuario necesita ver para saber si el parser leyó bien el CUIT.

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

### Aceptar la designación tampoco alcanza: hay un tercer paso (2026-08-29)
Descubierto en producción, otra vez con `27177624441`. El *Administrador de Relaciones* mostraba
las once relaciones delegadas al `20182810674` y la de **Facturación Electrónica** decía
`Aceptada: SI` — y WSFE seguía contestando 600. La lista de arriba estaba incompleta:

3. **FactuMov le pasa ese servicio a su certificado**: *Administrador de Relaciones* → *Nueva
   Relación*, con **Representado** el CUIT delegante, **Servicio** → BUSCAR → WebServices →
   Facturación Electrónica, y **Representante** → BUSCAR → el **computador** cuyo certificado usa
   la app. No el CUIT `20182810674`, que es el que viene puesto por default.
4. Recién ahí WSFE habilita el CUIT.

**Por qué:** WSAA no le emite el ticket a una persona, se lo emite a un **certificado**, y la
lista de relaciones que WSFE valida al leer `Auth.Cuit` es la que cuelga de ese certificado y no
la del CUIT que lo posee. Aceptar la designación habilita a la persona; el paso 3 es el que
traslada ese permiso al certificado. De ahí que el 600 diga literalmente `ValidacionDeToken`.

- **Va por cada CUIT que nos delegue.** No es un alta que se hace una vez y queda.
- **Los dos estados se ven idénticos desde la app**, y por eso el diagnóstico costó una sesión
  entera: una designación sin aceptar y una aceptada sin el paso 3 devuelven el mismo 600. Lo
  único que los separa es abrir el Administrador de Relaciones y mirar.
- **La sonda de control que lo aísla**: `FEParamGetPtosVenta` con `Auth.Cuit` = el CUIT del
  propio certificado. Eso no depende de ninguna delegación, así que si el control contesta bien
  y el CUIT delegado contesta 600, el problema está en las relaciones de ese CUIT y no en
  nuestro acceso a WSFE. Es lo primero que conviene correr ante un 600 inesperado, antes de
  tocar una línea de código.
- **El mail al operador describía solo el paso 2**, o sea que documentaba un trámite que no
  alcanza — la causa raíz de que esto llegara a producción. Corregido: ahora lista los dos y
  nombra el error fácil de cometer, que es dejar el propio CUIT como Representante. Desde el
  2026-08-30 además linkea `/como-aceptar-delegacion`, que lo muestra con una captura por paso.
- **Sigue sin poder automatizarse.** Igual que la aceptación, es Clave Fiscal y una página que
  ningún web service expone. Lo que cambia es que ahora el mail lo dice completo.

### El ticket viejo miente (2026-08-29)
Tercera vuelta con `27177624441`, el mismo día que la anterior. Con el paso 3 hecho —el
Administrador de Relaciones contestaba `La autorizacion: (20182810674-FactuMov)-27177624441-
ws://wsfe-20182810674 ya existe` al intentar rehacerlo— la app seguía diciendo que no. Esta vez
no faltaba ningún trámite: lo viejo era el ticket.

**Un TA lleva la lista de relaciones tal como estaba cuando se emitió.** El de producción se
había emitido a las 12:12 UTC y el paso 3 se hizo a las 14:09: el 600 que la app leía era la
respuesta correcta a la pregunta "¿estaba delegado a las 12:12?". Como el TA dura doce horas, la
delegación recién otorgada tarda hasta doce horas en verse — y el barrido de quince minutos no
ayuda, porque repregunta con ese mismo ticket.

- **La sonda de control lo aisló en un minuto**: con `Auth.Cuit` = nuestro propio CUIT contestó
  `granted=True` mientras el CUIT delegado daba 600. O sea que el acceso a WSFE estaba bien y el
  problema era de ese CUIT — o del ticket.
- **WSAA emitió un TA nuevo teniendo uno vigente**, y eso corrige una premisa que estaba escrita
  en tres lugares. Hasta acá se daba por hecho que se negaba (`El CEE ya posee un TA valido`).
  Con el ticket nuevo, el mismo CUIT contestó `granted=True` al instante. Es **una** observación,
  en producción, con `wsfe`: alcanza para dejar de afirmar lo contrario, no para prometer que
  siempre lo hace. `request_ticket` sigue tratando ese Fault como el error que puede ser.
- **`arca_tickets.issued_at`** (migración `e5c2a9f3d418`) y **`get_access_ticket(max_age=...)`**:
  un ticket puede estar vigente y ser viejo a la vez, y hasta ahora la tabla solo sabía lo
  primero. La edad se compara en SQL contra `func.now()`, igual que el vencimiento, para no
  meter el reloj de la app en la comparación.
- **La política la fija cada llamador, no el servicio.** El click del usuario exige un ticket de
  menos de **5 minutos** —del otro lado hay alguien que acaba de hacer el trámite y está
  mirando—; el barrido se conforma con **una hora**. El resto de la app no pasa `max_age` y reusa
  el ticket mientras valga, que es lo correcto para emitir una factura.
- **Cuesta un login por barrido, no uno por identidad.** El TA es del certificado y lo comparten
  todos los CUIT que se consulten después, así que el techo son 24 pedidos a WSAA por día haya
  una pendiente o cincuenta. Con los quince minutos del barrido serían 96, y la diferencia no
  compra nada: lo que se está esperando es que una persona haga un trámite.

**La renovación no se ata a `delegation_claimed_at`, y esa fue la primera versión equivocada de
este arreglo.** El aviso del usuario ocurre *antes* de nuestros dos pasos, así que un TA emitido
en ese momento tampoco ve la delegación — y peor, quedaría marcado como más nuevo que el aviso y
no se renovaría nunca más. El evento que habilita al CUIT no es el aviso del contribuyente sino
**nuestro paso 3**, que ocurre en la web de ARCA sin que la app se entere. Por eso el criterio es
la edad del ticket y no un evento: es lo único que no depende de enterarse de algo que nadie
avisa.

- **Queda una punta para más adelante**: un link "ya hice mi parte" en el mail que le llega al
  operador cerraría la espera del todo, porque ese sí es el momento exacto. No se hizo ahora
  porque la edad del ticket ya baja la espera de doce horas a una, y el link necesita una pantalla
  y un token que hoy no existen.

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
- Es un parámetro y no dos funciones porque es exactamente la única diferencia entre los
  endpoints: todos preguntan lo mismo y difieren en qué escriben cuando la respuesta es no. Desde
  el 2026-08-29 ese parámetro es `claim_token_hash: str | None` y no un `bool`: el aviso y el
  token del link del operador se emiten juntos, y como un `bool` más un hash aparte serían el
  mismo dato dicho dos veces, podrían contradecirse. No hay aviso sin link.

### El aviso al operador
`OPERATOR_EMAIL` en `EmailSettings`, y `notifications.send_delegation_pending_email`.

- **Es el único mail de la app que no le va a un usuario.** Aceptar la designación es un click
  con Clave Fiscal que ARCA no expone por ningún web service, así que la app no puede enterarse
  sola de que alguien la está esperando. El click del usuario es la única evidencia que va a
  existir nunca, y desperdiciarla deja al usuario esperando a que el operador mire la lista de
  pendientes de ARCA por casualidad.
- **Una sola vez por identidad**, colgado del primer aviso. Esa unicidad es también la del
  link que lleva adentro: hay un solo token por identidad justamente porque hay un solo mail.
- **Termina con un link** (2026-08-29) — ver abajo.
- **Y empieza con otro** (2026-08-30): `/como-aceptar-delegacion`, el instructivo ilustrado con
  una captura de ARCA por paso y el botón marcado. Va antes del texto porque la pantalla de ARCA
  es críptica y el paso 2 —la relación con el **computador**— es el que se saltea. El resumen en
  texto sigue en el cuerpo. El detalle de las dos pantallas (`/como-delegar` para el
  contribuyente y esta) está en *Los instructivos ilustrados de la delegación* en
  `docs/frontend.md`.
- **Opcional y sin default.** Es el único destinatario que no sale de una fila de `users`, y una
  instalación sin operador tiene que poder arrancar. Sin él, el aviso queda en el log — misma
  política que `send_email_best_effort`, un escalón antes.

### El rechequeo, en cuatro lugares
Nadie nos avisa cuando la delegación empieza a funcionar, así que lo único que se puede hacer es
volver a preguntar. Se pregunta en cuatro momentos y por motivos distintos:

- **Al abrir la identidad en la pantalla**, una vez por montaje (`useRef`, contra el doble
  montaje de StrictMode). Solo si no está verificada **o si la verificación tiene más de una
  semana** — repreguntar por una verificada hace días no aprende nada y gasta cuota compartida.
- **Al abrir la grilla de identidades** (2026-08-29), sobre las mismas que necesitarían chequeo,
  de a una y en orden. Se agregó porque el aviso "Sin verificar" de las tarjetas salía de la
  columna guardada y nada más: una identidad ya habilitada en ARCA seguía marcada como sin
  verificar hasta que alguien entrara a ella. La marca existe justamente para no tener que entrar
  tarjeta por tarjeta, o sea que era la única pantalla donde el dato tenía que estar fresco y la
  única que no lo refrescaba. **Secuencial y no `Promise.all`**: son varios segundos de
  conversación con ARCA por un certificado compartido, y dispararlas juntas es la forma más
  rápida de comerse el 429. **Se corta en el primer fallo**, porque lo que hace fallar a una las
  hace fallar a todas.
- **`services/delegation_watch.py`, cada 15 minutos**, sobre las que avisaron y siguen sin
  verificar. Lo que se espera es que una persona lea un mail y haga un click, o sea tiempo
  humano: 15 minutos deja la espera del usuario en unos 7 de promedio y cuesta 4 llamadas por
  hora **por identidad pendiente**, que en el caso normal son cero.
- **Cuando el operador entra al link de su mail** (2026-08-29), sobre esa identidad y en el acto
  — ver *El link del mail al operador*.

Los tres comparten el criterio y el freno, que viven en `api/delegation.ts` del lado del
cliente: `needsChecking` decide si el dato guardado ya sirve, y `checkedRecently` pone un piso de
cinco minutos entre dos consultas por la misma identidad. Ese segundo freno es nuevo y lo trajo
la grilla: una identidad sin verificar la necesita *siempre*, así que sin él entrar y salir de la
lista diez veces son diez llamadas por CUIT — y con el limitador en 30 por hora, el propio
usuario se dejaría afuera. Vive a nivel de módulo y no en un `useRef` justamente porque lo que
hay que sobrevivir es el desmontaje al navegar entre la grilla y el detalle.

**Los dos chequeos del cliente ya no son mudos** (2026-08-29). Siguen sin pintar el cartel rojo
—no los pidió nadie, y el rojo es de las acciones que el usuario eligió—, pero el
`.catch(() => {})` que tenían dejaba un 502 o un 429 viéndose *exactamente igual* que un "ARCA
dice que todavía no": la pantalla se quedaba en «Falta un paso nuestro» afirmando que estamos
mirando, justo cuando no habíamos podido mirar. Ahora queda una línea en gris que dice que no se
pudo consultar, y el 429 se distingue del resto porque tiene otra salida (esperar) que el usuario
puede tomar.

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

### El link del mail al operador (2026-08-29)
`POST /delegations/accepted`, la pantalla `/delegacion-aceptada` y la columna
`fiscal_identities.delegation_claim_token_hash`.

El operador termina los dos pasos en ARCA y **ARCA no le contesta nada**: la pantalla de
«Aceptación de Designación» dice "Aceptada: SI" tanto si con eso alcanzó como si falta la
relación con el computador, que es el error que este mail existe para prevenir. Hasta acá lo
único que le quedaba era esperar al barrido —quince minutos, y sin ninguna señal de que el que
falló fue él— o abrir la app con la cuenta de otro, que no existe. El link es donde pregunta.

- **No le cree.** Lo que escribe la verificación es la respuesta de ARCA y nada más, igual que
  los otros dos endpoints: el link es un "andá a fijarte ahora", no un "dalo por hecho". Por eso
  el `granted=False` no es un fracaso del link sino su otra mitad útil, y llega en el único
  momento en que el operador todavía tiene las pantallas de ARCA abiertas para corregir.
- **Sin sesión, y no por comodidad.** La identidad fiscal es de otro: `get_fiscal_identity_or_404`
  le contestaría 404 aunque el operador tuviera cuenta. Lo autoriza el token, igual que en la
  confirmación de mail. Vive en un segundo router del módulo (`delegation_router`) porque el
  primero exige sesión en todas sus rutas.
- **Un token por identidad, no un secreto del `.env`.** 256 bits de `secrets`, guardado como
  SHA-256 en la fila y emitido junto con el aviso. Se borra en `mark_delegation_verified`, o sea
  que **muere con la espera que acorta**, la cierre quien la cierre: el link, el barrido o la
  pantalla del usuario. Un link que sigue vivo después es una credencial sin dueño capaz de
  gastar cuota de ARCA para siempre.
- **No es de un solo uso**, al revés que el de confirmación. El caso normal es justamente el
  "todavía no": el operador completa el paso que faltaba y vuelve a apretar sin pedir un mail
  nuevo, que es lo que haría inservible al link en el único momento en que sirve.
- **Columna y no tabla**, al revés que `email_confirmations`. Aquella es tabla porque el reenvío
  emite un token nuevo sin invalidar el anterior y hacen falta varios vivos a la vez; este mail
  sale una sola vez por identidad, así que nunca hay más de un link dando vueltas.
- **Limitado por IP** (10/hora), que es lo que reemplaza al presupuesto por usuario cuando no hay
  usuario. La cuota de ARCA es del certificado, o sea de todos.
- **La pantalla pregunta sola al montar** y ofrece un botón para volver a preguntar. Que un
  cliente de mail prefetchee el link cuesta a lo sumo una consulta a ARCA con techo por IP, y no
  quema nada: el token no es de un solo uso.

**Revierte el "descartado" que estaba escrito acá.** La versión descartada era un link que
*afirmaba* "ya acepté" —una segunda fuente de verdad capaz de mentir— protegido por un secreto
compartido en el `.env`, y se valuó en "ahorra siete minutos de espera del usuario". Las tres
cosas cambiaron: este link no afirma nada, el secreto es por identidad y muere con ella, y lo que
compra no es la espera del usuario sino **la única respuesta que el operador puede recibir sobre
un trámite que ARCA no le contesta**. Ese último punto es el que no estaba en la cuenta original.

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

