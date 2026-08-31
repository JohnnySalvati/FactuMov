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

## Precios y cobro — decidido, todavía no implementado

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

### Lo que falta

Esta unidad dejó el modelo, la política y los dos gates. Falta:

- **El checkout y el webhook de Mercado Pago**, que es lo único que hoy puede escribir un
  `ACTIVE`. El webhook tiene que ser **idempotente**: MP reintenta y manda el mismo evento más
  de una vez. Ahí aparece la tabla `subscription_payments`, que es a la vez el historial y el
  registro de idempotencia — no se creó ahora justamente porque no existe todavía nada que la
  escriba.
- **El endpoint de baja**, sin body: el único cambio de plan que el usuario pide desde la app.
  Por eso `schemas/subscription.py` no tiene schema de entrada — un PATCH del plan sería un
  endpoint para hacerse Pro gratis.
- **Las pantallas**: el estado del plan, el aviso de cupo y el checkout. Hoy `GET
  /subscription` devuelve todo lo que necesitan, incluidos `can_emit` y `can_add_fiscal_identity`
  ya resueltos, para que la pantalla y el endpoint que corta la acción no puedan discrepar.
- **Los avisos del trial** por mail, en el día ~23 y el ~28, con el link de pago ya armado.
- **Emitir las propias facturas de las suscripciones** con FactuMov, que es la mejor prueba de
  producto que el proyecto puede darse.
