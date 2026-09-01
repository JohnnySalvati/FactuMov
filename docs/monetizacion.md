# FactuMov — Monetización: planes, límites y cobro

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

## Los dos planes (2026-08-31)

**Free** y **Pro**, y nada más. No hay "Enterprise": esa palabra promete vendedor, contrato,
SSO y factura contra orden de compra, o sea cuatro cosas que no existen. Si algún día aparece
el contador con cuarenta clientes, el tercer plan se llama **Estudio**, que es la palabra con
la que ese comprador se nombra a sí mismo en Argentina — pero eso es después de tener los
primeros Pro pagando, no antes.

| | Free | Pro |
|---|---|---|
| Comprobantes por mes | 5 | sin límite |
| Identidades fiscales | 1 | sin límite |
| Dictado por voz | no | sí |
| Texto del mail de cada modelo | no | sí |
| Todo lo demás | sí | sí |

**El corte del Free es por volumen, no por cantidad de entidades, y esa es la decisión de
producto más importante de la unidad.** La idea original era "Free = una sola entidad", y se
descartó porque el usuario típico de FactuMov —monotributista, profesional independiente—
tiene **un solo CUIT**: un Free limitado a una entidad le regala el producto completo y no lo
hace pagar nunca, dejando como único comprador al contador con varios clientes, que es un
segmento mucho más chico y que además ya tiene software. El volumen, en cambio, crece con el
uso: el que factura tres veces por mes se queda gratis y recomienda, y el que factura treinta
convierte. Multi-entidad sigue siendo Pro, pero como el segundo límite y no como el único.

El límite se cuenta **por mes calendario y por usuario**, no por identidad fiscal: es una
propiedad de la cuenta, y repartirlo por CUIT haría que el Free de una entidad valiera más que
el de dos.

## Los treinta días de prueba

Toda cuenta nace con **30 días de Pro completo**, y el reloj arranca en el registro.

- **Sin pedir tarjeta.** Pedir medio de pago para probar corta los registros a la mitad en
  este mercado, y hoy hace falta volumen arriba del embudo antes que tasa de conversión.
- **Al vencer no se bloquea: se degrada a Free.** Un usuario degradado convierte; uno
  bloqueado desinstala. Lo único que cambia es que choca el tope mensual.
- **Los comprobantes ya emitidos nunca quedan detrás del paywall**, ni por vencimiento ni por
  falta de pago. Son documentación fiscal que el usuario está obligado a conservar: se cortan
  las emisiones **nuevas**, jamás el acceso a lo viejo. Por eso el único gate de emisión está
  en `POST /{id}/emit` y no hay ninguno en `GET /invoices` ni en el PDF.
- **Arranca en el registro y no en la confirmación del mail.** Son minutos de diferencia en el
  caso normal, y ponerlo en el registro deja un solo lugar donde la fila puede nacer. La
  alternativa considerada —arrancar en la primera emisión, o sea cuando el usuario obtiene
  valor real— convierte mejor pero necesita un disparador en `/emit` y un cuarto estado
  ("trial sin empezar") que hoy no paga lo que cuesta.

## Por qué el plan no es una columna

`subscriptions` guarda **hechos**: en qué estado está la relación (`SubscriptionStatus`) y
hasta cuándo llega lo pagado (`current_period_end`). **Quién es Pro se deduce**, en
`services/subscription.py`.

Es el mismo argumento que sacó `voucher_type` de `invoice_templates` — ver
[*Modelo de datos → La letra del comprobante se deduce*](modelo-de-datos.md). Con una columna
`plan`, el día que `current_period_end` queda en el pasado la fila dice "PRO" y "vencida" a la
vez, y hay que acordarse de correr algo que la reescriba. Sin ella no hay nada que se pueda
quedar viejo: la pregunta se contesta contra el reloj cada vez que se hace.

Y por eso mismo **la política vive en cuatro constantes de un módulo y no en la base**:
`TRIAL_DAYS`, `PAST_DUE_GRACE_DAYS`, `FREE_MONTHLY_INVOICES` y `FREE_FISCAL_IDENTITIES` son
números comerciales que se van a cambiar. Subir la gracia de 10 a 15 días tiene que ser editar
un número y correr los tests, no una migración que reescribe filas — y una fila vieja seguiría
diciendo lo que la política decía el día que se escribió.

### Los cuatro estados, y qué hace cada uno con el acceso

| Estado | Qué pasó | ¿Es Pro? |
|---|---|---|
| `TRIALING` | Cuenta nueva, nunca pagó | Hasta `current_period_end`, **sin gracia** |
| `ACTIVE` | Hay un cobro acreditado | Hasta `current_period_end` + gracia |
| `PAST_DUE` | Falló el cobro de la renovación | Hasta `current_period_end` + gracia |
| `CANCELED` | Pidió la baja | Hasta `current_period_end`, **sin gracia** |

No hay miembro `FREE`: Free es lo que queda cuando ninguno de los cuatro está vigente.

- **La gracia son 10 días y se aplica solo a los dos estados en los que un cobro puede llegar
  tarde.** Las tarjetas se vencen, se reemiten y se rechazan por saldo todo el tiempo; cortar
  al primer rechazo pierde clientes que sí querían pagar. Sumársela al trial haría que treinta
  días de prueba fueran cuarenta, y dársela al que se dio de baja sería pagarle por irse.
- **La gracia no se guarda sumada.** `current_period_end` es la fecha que la pantalla muestra
  ("se renueva el 28"); guardarla ya corrida haría que una sola columna dijera dos cosas.
  Consecuencia: `mark_past_due` **no toca la fecha**, y ahí está toda la mecánica de la gracia
  sin una segunda columna que mantener sincronizada.
- **`CANCELED` no corta el acceso.** El que da de baja el 3 con el mes pago hasta el 28 sigue
  siendo Pro hasta el 28: ya lo pagó. Cortar en el momento de la baja es quedarse con plata
  por un servicio que no se presta, y le enseña al usuario a no dar de baja hasta el último día.
- **`activate` sirve para las tres transiciones que terminan en un pago** —primera compra,
  renovación y el reintento que rescata a un `PAST_DUE`— porque para la fila son la misma
  escritura. Distinguirlas obligaría a que quien cobra sepa de dónde venía el usuario, que es
  justo lo que un webhook de Mercado Pago no sabe.

## El contador del mes se cuenta, no se guarda

`count_invoices_this_month` es un `COUNT` sobre `invoices` joineado a `fiscal_identities`.

- **Va por `created_at` y no por `invoices.date`.** La fecha del comprobante la elige el
  usuario dentro de la ventana que ARCA permite (±10 días para servicios), así que contar por
  ella dejaría esquivar el límite fechando para atrás — y peor, haría que elegir una fecha
  legítima del mes pasado devolviera cupo de este mes. El límite mide **uso del servicio**; el
  calendario fiscal lo lleva ARCA, no nosotros.
- **El mes se corta en hora argentina, no en UTC.** Con UTC, lo emitido entre las 21 y la
  medianoche del último día del mes caería en el mes siguiente: el contador se reiniciaría tres
  horas antes de tiempo y un 30 a la noche gastaría cupo del mes que todavía no empezó. Es el
  mismo error de un día que `isoDate` evita en el frontend.
- **Sin columna acumulada.** Habría que rebobinarla cada mes y podría desincronizarse de las
  filas que dice contar — la misma regla de no guardar lo deducible. El `COUNT` sale de un
  índice que ya existe.
- **El chequeo no es un candado.** Dos emisiones en vuelo podrían colarse las dos; el daño de
  un comprobante de más en un mes es cero y el precio de serializar la emisión detrás de un
  lock de cuota sería real. El candado que sí existe es el de la numeración, y ese protege algo
  irreversible.

## 402 y no 403

`PlanLimitReachedError` termina en **402 Payment Required** en los dos endpoints que cortan.
El 403 diría "no tenés permiso", que acá es falso: el usuario tiene todo el permiso del mundo
sobre sus propios datos, lo que falta es el plan. El 402 existe exactamente para esto y le deja
al frontend distinguir "necesitás Pro" —que se resuelve con una pantalla de suscripción— de
cualquier otro rechazo sin tener que leer el texto.

Una sola excepción para los dos límites, porque el router hace lo mismo con las dos: contestar
402 con el mensaje que la excepción trae. La diferencia que importa —qué límite se chocó y qué
hacer— ya está en el mensaje, que es lo único que el usuario lee.

- **`POST /fiscal-identities`** chequea antes del insert. El PATCH no lo lleva: editar la
  identidad que ya se tiene no agrega ninguna.
- **`POST /invoice-templates/{id}/emit`** chequea antes de mirar las fechas y mucho antes de
  salir a ARCA: es lo único que puede decir que no sin gastar cuota del certificado, que es una
  sola para todos los usuarios.
- **Y el `preview` lo anuncia antes**, en el `blocked_reason` que ya existía para la
  delegación. Con los dos bloqueos puestos gana el de la delegación: es el que hace que ese
  CUIT no pueda emitir aunque el plan sobre, así que mostrar el del plan primero sería cobrarle
  a alguien por un botón que igual no va a andar.
- **Bajar de plan nunca borra datos.** El Pro que se dio de baja con tres identidades las
  conserva y las sigue usando; lo que no puede es agregar una cuarta. Elegir cuál de las tres
  sobrevive no es una decisión que le corresponda tomar a la app, y un emisor que desaparece se
  lleva puestos los modelos y las facturas que cuelgan de él.

**El dictado por voz es el único derecho que el backend no puede hacer cumplir**: corre entero
en el navegador (Web Speech API) y lo único que llega al servidor es el formulario que llenó.
`voice_enabled` le dice al frontend qué *ofrecer*, no qué permitir. Y está bien: lo que la voz
ahorra es la parte reversible del camino —llenar campos—, mientras que emitir, que es lo
irreversible, pasa igual por `can_emit`.

### El texto del mail es el único límite que se aplica dos veces (2026-09-01)
`custom_email_enabled` decide **si el texto se puede guardar** —el 402 de
`POST`/`PATCH /invoice-templates`— y además **si se usa al enviar**, que lo mira
`POST /invoices/{id}/send` en el momento del envío. Los otros límites se aplican una sola vez,
en la acción que corta.

La segunda mitad es la excepción a *bajar de plan nunca borra datos*, y es una excepción de
uso y no de datos: el texto que un ex-Pro escribió sigue guardado y vuelve solo el día que
vuelve el plan; lo que sale mientras tanto es el mail de FactuMov, que dice lo mismo con otras
palabras. La diferencia con las identidades fiscales —donde el ex-Pro conserva las tres **y las
sigue usando**— es qué significa dejar de usar cada cosa: allá, no poder facturar con un CUIT;
acá, mandar el otro texto. Ver *Emisión y envío → El texto del mail vive en el modelo*.

**Borrarlo no pide Pro**, y esa asimetría es deliberada: es la única salida del que ya no puede
editarlo, y lo que deja en su lugar es el default. Un límite que impide *sacar* algo no protege
nada; solo deja al usuario encerrado con un texto ajeno a su plan.

### El Free se paga con el pie del mail (2026-09-01)
El mail por default de cada factura termina en una firma que nombra a FactuMov, dice cuántos
comprobantes por mes salen gratis y linkea a la app. Es el único canal de adquisición que el
producto tiene hoy y no cuesta nada: el mail sale igual, y lo lee el cliente del que facturó —
alguien que muy probablemente también emite facturas.

**El Free es el que más lo reparte**, y eso es exactamente lo que se buscaba con el corte por
volumen: el que factura tres veces por mes se queda gratis y **recomienda**. Los cinco
comprobantes no son solo un tope, son cinco mails con el link adentro.

**Sacarlo es escribir el texto propio del modelo, que es Pro.** No hay un interruptor de "quitar
la marca": la función que ya existe alcanza, y de paso le da al Pro un motivo más concreto que
"sin límites". Un Pro que no personaliza nada lo sigue llevando, y está bien — el que le molesta
tiene la herramienta para sacarlo en treinta segundos, con el texto por default a la vista en el
placeholder para copiar y editar.

El texto y el resto de las decisiones están en *Emisión y envío → El pie de FactuMov*.

## La baja (2026-08-31)

`POST /subscription/cancel`, sin body y devolviendo el estado ya recalculado.

- **`POST .../cancel` y no `DELETE /subscription`.** El DELETE diría que la suscripción
  desaparece, y no desaparece nada: la fila queda, el acceso sigue hasta `current_period_end`
  y volver a pagar es la misma fila pasando a `ACTIVE` otra vez (`activate` limpia
  `canceled_at`). Es una transición de estado y la ruta tiene que decir eso.
- **Sin body**, que es la otra mitad del diseño de `schemas/subscription.py`: la baja es el
  único cambio de plan que el usuario pide desde la app. Un PATCH del plan sería un endpoint
  para hacerse Pro gratis.
- **Devuelve los entitlements y no un 204.** La pantalla que aprieta el botón muestra el estado
  y la fecha, y las dos cambian con la llamada; un 204 la obligaría a un `GET` inmediato para
  pintar lo que el usuario acaba de hacer.
- **Es idempotente y no reescribe `canceled_at`.** Esa columna registra *cuándo lo pidió*, así
  que el segundo click —o el reintento de una respuesta que se perdió— la haría mentir sobre
  una fecha que ya ocurrió.
- **Un Free también puede llamar y no es un error**: su fila queda en `CANCELED` y el acceso no
  cambia, porque ya no había ninguno que cortar. Quien decide a quién ofrecerle el botón es la
  pantalla —solo a `ACTIVE` y `PAST_DUE`, que son los estados donde hay una renovación que
  frenar—, pero esa es una regla de presentación y no puede vivir en la API: un 409 ahí sería
  un caso más para el frontend a cambio de nada.
- **Primero Mercado Pago y después la fila** (2026-09-01). Si la fila tiene
  `provider_subscription_id`, el endpoint cancela el `preapproval` del otro lado **antes** de
  marcar nada, y si esa llamada falla contesta 502 sin tocar la suscripción. Marcarla igual
  dejaría a Mercado Pago cobrando todos los meses algo que la app da por terminado, y el
  usuario se enteraría por el resumen de la tarjeta: hacerlo reintentar es molesto, cobrarle de
  más no tiene arreglo. Un `preapproval` que Mercado Pago ya no conoce (404) cuenta como
  cancelado — lo que se busca es que no se cobre más, y eso ya se cumple.

## Las pantallas del plan (2026-08-31)

`/plan` es la contraparte de `GET /subscription`: qué plan hay, cuánto del cupo va usado, qué
agrega Pro y cómo darse de baja. **Existe para que chocar un límite deje de ser un 402 crudo** —
los dos gates contestan un texto que dice "pasate a Pro" y hasta ahora ese texto era una pared
sin ningún lado adonde ir.

- **Ruta propia y no una sección de Ajustes**, aunque se llegue desde ahí. La linkean los dos
  avisos de límite y la franja de cupo, y una sección adentro de otra pantalla no se puede
  linkear sin mandar al usuario a buscarla. Ajustes se queda con dos renglones y el link.
- **El plan se pide una vez por sesión, en un contexto** (`SubscriptionProvider`) y no con un
  `useResource` por pantalla. Lo consultan seis lugares que fueron a hacer otra cosa —la franja
  de cupo, el alta de identidad fiscal, la pantalla de emitir, los dos micrófonos y la pantalla
  del plan—, y uno por pantalla serían seis `GET /subscription` por vuelta, tres de ellos sobre
  pantallas que se abren cien veces por semana. Está montado **adentro** de `RequireAuth`, al
  revés que `AuthProvider`, porque el endpoint exige sesión.
- **Quien mueve un contador lo recarga**: emitir, dar de alta una identidad fiscal y borrarla.
  El contexto vive lo que dure la sesión, así que sin eso la franja seguiría mostrando el
  número de antes de emitir — que es justo el momento en el que ese número importa.
- **La franja de cupo aparece recién con el último comprobante**, y no antes. Es una tira arriba
  de todas las pantallas: un contador permanente diciendo "1 de 5" sería una publicidad del plan
  Pro en la pantalla que se abre cien veces por semana. Y no aparece nunca si el plan no se pudo
  cargar — avisar de un cupo que no se conoce es peor que no avisar.
- **Los dos botones de pago viven en `SubscribeBox`** (2026-09-01), y esa caja **pide los
  precios con su propio `useResource`**, no desde el contexto. Es el caso que
  `SubscriptionProvider` no cubre a propósito: el plan de la cuenta lo leen seis lugares en cada
  sesión y la lista de precios la mira solo quien está mirando esa caja, así que montarla ahí
  adentro hace que la consulta ocurra cuando se muestra y no cuando se abre la app. El botón
  termina en un `location.href` y no en un `navigate`: el checkout lo hostea Mercado Pago, o sea
  otro dominio.
- **El regreso del checkout no activa nada.** `back_url` trae `?pago=listo`, y lo único que hace
  la pantalla con eso es volver a preguntar y explicar que la confirmación puede tardar unos
  segundos. Quien activa es el webhook: creerle a una query string sería dejar que cualquiera se
  haga Pro escribiéndola a mano.
- **Al `PAST_DUE` se le ofrece contratar de nuevo, y a ningún otro Pro.** Es el caso de la
  tarjeta vencida o reemplazada, donde el reintento de Mercado Pago va a fallar siempre con la
  misma. El backend cancela la autorización anterior antes de crear la nueva.
- **El dictado por voz se esconde entero para el Free**, sin cartel ni micrófono deshabilitado,
  por lo mismo que la franja no es un contador permanente. Son tres componentes —el comando, el
  micrófono de cada fecha y el interruptor de la respuesta hablada— y la regla está escrita una
  vez, en `useVoiceEnabled`. La respuesta hablada se apaga además con una llave aparte
  (`setVoiceAllowed` en `speak.ts`) porque `say()` se llama desde efectos que no tienen
  contexto; que sea una llave **aparte** de la preferencia del usuario es lo que hace que el día
  que se haga Pro recupere la que tenía elegida.
- **Cuando no se sabe el plan, la voz queda prendida.** Las dos formas de equivocarse no cuestan
  lo mismo: empezar callado le saca los micrófonos al Pro en cada carga de la app —y para
  siempre si la consulta falla—, y empezar hablando se los deja medio segundo de más al Free. La
  voz es la parte reversible del camino; lo irreversible lo sigue cortando `can_emit` del lado
  del backend.

## Precios y cobro

**Anclado en USD y mostrado en pesos**, con revisión periódica anunciada. Precio en pesos fijo
se come la inflación; precio *cobrado* en dólares genera más fricción de la que resuelve en una
app de consumo local.

**El anual vale 10 mensuales**, o sea dos meses bonificados (~17%). La propuesta original era
USD 2/mes y USD 10/año, y las dos mitades se movieron: 10 contra 24 es 58% de descuento, con lo
cual todos eligen anual —hacen bien— y se pierde más de la mitad del ingreso a cambio de un
flujo de caja que a esta escala no hace falta. Y USD 2/mes no lo mata la comisión sino el
soporte: un solo mail respondido se come meses de ingreso de ese usuario, hacen falta ~500
pagos para USD 1000/mes en un nicho argentino donde conseguirlos es mucho trabajo, y un precio
así señaliza "proyecto de hobby" — atrayendo justo al segmento más sensible al precio y más
demandante. Subir después es mucho más difícil que arrancar bien.

### Mercado Pago Suscripciones, no transferencia

La premisa de que "la tarjeta tiene costo y MP no" mezcla dos cosas: **MP cobra comisión por
todo lo que pase por MP**, incluso dinero en cuenta. La tarjeta no es la opción cara frente a
MP; la tarjeta *es* MP. La comisión varía según el plazo de acreditación y hay que chequearla
vigente antes de fijar precio.

La transferencia CVU→CVU sí es gratis, y aun así es la peor opción para una suscripción:

1. **No renueva sola.** Cada mes el usuario decide de nuevo pagarte, y el churn involuntario
   —el que te quería seguir pagando pero se olvidó— se come mucho más que cualquier comisión.
2. **Conciliación manual.** Con 10 usuarios se mira el homebanking; con 100 es un trabajo de
   medio tiempo, y dos referencias mal puestas lo rompen.
3. **No hay webhook.** No se sabe cuándo activar ni cuándo cortar sin que alguien mire.

Por eso el camino principal es la API de **`preapproval`** de Mercado Pago: débito automático
sobre tarjeta o dinero en cuenta, checkout hosteado por ellos —así FactuMov nunca toca datos de
tarjeta ni entra en PCI— y webhooks por cada cobro exitoso o fallido. Del otro lado se guarda
solo el `preapproval_id` y el estado, que es lo que `subscriptions.provider_subscription_id`
tiene reservado. La transferencia queda como **excepción atendida a mano** y solo para el plan
anual (`BillingProvider.MANUAL`): cobrar todo junto una vez al año sin comisión es buen
negocio, y como cobro mensual sería un recordatorio por mes y una baja por olvido.

### La lista de precios está en el código, no en el `.env` (2026-09-01)

`PRICES` vive en `services/subscription.py`, al lado de `TRIAL_DAYS` y de los dos límites del
Free, y por el mismo motivo: es política comercial. Una variable de entorno haría que dos
servidores pudieran cobrar distinto por el mismo plan, que es un problema bastante peor que
tener que deployar para cambiar un precio.

El número en pesos es lo único de toda la política que **se desactualiza solo**, porque el ancla
es en dólares. Se revisa periódicamente y se anuncia; el importe de cada cobro queda guardado en
`subscription_payments.amount` tal como lo informó el proveedor, así que subir el precio no
reescribe lo que alguien pagó el mes pasado.

## El checkout y el webhook (2026-09-01)

Dos endpoints y una tabla. `POST /subscription/checkout` devuelve una URL, y
`POST /webhooks/mercado-pago` es **lo único en toda la app que puede escribir un `ACTIVE`**.

### El checkout no cambia el plan

Lo único que produce es el `init_point` de Mercado Pago. El usuario autoriza el débito allá, la
notificación llega por atrás y recién ahí la fila se mueve. Si esta llamada activara algo, sería
un endpoint para hacerse Pro con un `curl` — es la misma razón por la que
`schemas/subscription.py` no tiene un schema de escritura del plan. `CheckoutRequest` no lo
contradice: elige **qué se va a pagar**, no qué plan se tiene, y ni el precio ni la moneda
viajan desde el cliente.

- **El `preapproval_id` no se guarda al crear el checkout.** Hasta que el webhook confirme, el
  vínculo lo lleva `external_reference` con el id del usuario adentro. Guardarlo antes ataría la
  cuenta a una autorización que quizás nadie complete, y el `unique` de esa columna convertiría
  el segundo intento en un error sobre una fila que no se llegó a usar.
- **El que paga durante la prueba no pierde los días que le faltaban.** El preapproval se crea
  con un `free_trial` de exactamente los días que quedan, así que la autorización queda hecha ya
  mismo y el primer cobro cae el día que la prueba se terminaba. Sin eso, el que decide pagar en
  el día 5 compra treinta días teniendo veinticinco gratis en la mano — que es un pedido de
  reembolso, y castiga justo al que convirtió antes de que se lo pidieran.
- **El `ACTIVE` no puede volver a contratar** (409): dos `preapproval` sobre la misma cuenta son
  dos débitos por el mismo servicio. El `PAST_DUE` **sí**, porque es el de la tarjeta vencida y
  el reintento de Mercado Pago va a fallar siempre con la misma; ahí se cancela la anterior
  **antes** de crear la nueva, porque el orden inverso deja dos vivas si algo falla en el medio.

### La firma es toda la autenticación del webhook

El endpoint no tiene sesión —lo llama un servidor de Mercado Pago— así que el HMAC de
`x-signature` es lo único que separa un cobro real de un `curl` que se hace Pro. Sin
`MERCADOPAGO_WEBHOOK_SECRET` no se procesa **nada**.

**No se chequea que el `ts` sea reciente**, y es deliberado. Rechazar por antigüedad evitaría
que alguien reenvíe una notificación vieja capturada, pero reenviarla no logra nada —el cobro ya
aplicado cae en la idempotencia, y el estado del preapproval se relee de Mercado Pago cada vez—
y a cambio se perdería cualquier entrega demorada, que sí puede ser el cobro que activa una
cuenta.

### La idempotencia: dos mecanismos, porque son dos problemas

`subscription_payments` es a la vez el historial y el registro de idempotencia. Una tabla y no
dos: "¿este cobro ya lo procesamos?" y "¿de qué se le cobró?" se contestan las dos con la lista
de cobros, y una tabla de ids vistos guardaría lo mismo sin el importe ni la fecha.

- **El estado del `preapproval` no necesita registro.** El evento no dice qué pasó, dice qué
  recurso mirar: se relee de Mercado Pago y se copia. Procesarlo dos veces escribe dos veces lo
  mismo, y procesar uno viejo escribe el estado de **ahora**.
- **El dinero sí.** Sin la tabla, tres entregas del mismo cobro empujarían el período tres
  meses. El `unique` de `provider_payment_id` está en la base y no solo en el servicio porque el
  chequeo pierde contra dos entregas simultáneas y la restricción no.
- **La clave es el par (id, estado) y no el id solo.** Mercado Pago **recicla** un cobro
  rechazado: lo reintenta durante días con la misma referencia, y cuando entra manda otro aviso
  sobre ese mismo id ya aprobado. Filtrando por id, esa aprobación se descartaría como duplicada
  y el usuario se quedaría en `PAST_DUE` hasta que se le acabe la gracia, habiendo pagado.

### Qué contesta, y por qué importa

Del otro lado hay una máquina que lee el status y decide si reintenta:

| Status | Cuándo | Qué logra |
|---|---|---|
| 200 | Se aplicó, o no había nada que aplicar (tema ajeno, cobro en vuelo, duplicado) | Que deje de reintentar algo que nunca va a cambiar |
| 401 | La firma no cierra | Nada que reintentar: no va a mejorar |
| 503 | Falta `MERCADOPAGO_WEBHOOK_SECRET` | Que reintente cuando la variable esté puesta |
| 502 | Mercado Pago no contestó cuando fuimos a leer el recurso | Que reintente: perder ese aviso puede ser perder el cobro que activa la cuenta |

El 502 cubre además un caso que pasa de verdad: **los dos avisos pueden llegar al revés**. Si el
cobro de la primera cuota llega antes que la autorización, la fila todavía no tiene el id del
proveedor y ese cobro no es de nadie; pedir el reintento lo resuelve solo.

### El período y el importe salen de Mercado Pago, no de un reloj propio

`current_period_end` es el `next_payment_date` que ellos informan, y el importe es su
`transaction_amount`. Son quienes deciden cuándo vuelven a cobrar: una cuenta local solo podría
discrepar, y discrepar acá es cortarle el acceso a alguien a quien le van a cobrar igual.

### Cómo se prueba

El webhook lo llama Mercado Pago desde internet, así que **contra `localhost` no llega**: hace
falta un túnel y cargar esa URL pública en el panel. Sin túnel se puede probar todo menos la
acreditación — el checkout se crea, la pantalla redirige, y la cuenta queda como estaba porque
nadie avisó. Y una cuenta de Mercado Pago **no se puede pagar a sí misma**: hacen falta las dos
cuentas de prueba, una como vendedor y otra como comprador.

### Lo que falta

Están el modelo, la política, los dos gates, la baja completa, el checkout, el webhook y las
pantallas. Falta:

- **Los avisos del trial** por mail, en el día ~23 y el ~28, con el link de pago ya armado.
- **La conciliación a mano de `BillingProvider.MANUAL`**, que hoy no tiene por dónde entrar: el
  modelo lo contempla y ningún endpoint lo escribe.
- **Emitir las propias facturas de las suscripciones** con FactuMov, que es la mejor prueba de
  producto que el proyecto puede darse.
