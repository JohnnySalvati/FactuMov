# FactuMov — Producto y hoja de ruta

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

## Objetivo
Nueva app de facturación, independiente de Balance360 pero reutilizando su lógica de
backend ya probada. Debe funcionar en Android, iOS y Desktop.

**El celular es el caso principal** (confirmado el 2026-08-26); la computadora tiene que
andar, pero es el secundario. No es un matiz de diseño: define que el CSS se escribe
mobile-first —el estilo base es el de pantalla angosta y las media queries agregan con
`min-width`— y que cada pantalla nueva se piensa primero en 360 px de ancho. Escrito al
revés, cada pantalla nace ancha y hay que acordarse de angostarla, o sea que el caso
principal queda dependiendo de que nadie se olvide.

## Funcionalidades core
1. Crear un modelo a partir de la importación de una factura en PDF.
2. Permitir la edición de ese modelo.
3. Almacenar el modelo.
4. Emitir nuevas facturas haciendo pequeñas modificaciones sobre un modelo guardado.
5. (Eventual) Enviar la factura por email y/o WhatsApp.


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


## Unidades pendientes, en orden
Cerradas el 2026-08-26: la capa HTTP de autenticación (login, logout, `/me`,
`dependencies.py` y los tres routers protegidos), el *ownership scoping*, el registro con
confirmación por email con su rate limiting, la **integración con ARCA** (verificación de
delegación + consulta al padrón) y el **frontend**, incluida la grilla de modelos con su
editor e importación de PDF — ver *ARCA* y *Frontend*.

Cerradas el 2026-08-27: el **reset de contraseña**, la **visibilidad del fallo de SMTP**, la
**emisión con CAE** y el **envío de la factura por email** — ver las secciones respectivas.
**Con eso las cinco funcionalidades core están hechas** y el circuito cierra de punta a punta:
importar un PDF, editar el modelo, guardarlo, emitir con CAE y mandarlo.

Lo que sigue ya no es funcionalidad: es **salir a la cancha**. Las tres se pidieron el
2026-08-27 y van en ese orden por dependencia, no por importancia. Las dos primeras —la
**marca** (el ícono propio, el acento verde, los íconos de la PWA con su manifest y el logo de
InSoft en las pantallas sin sesión) y la **producción**— están cerradas, y la **landing** está
escrita y a la espera de que se corra su `scp.ps1`.

1. ~~**Producción**~~ — **hecha el 2026-08-28.** La app corre en
   `factumov.insoft.net.ar`, en la VM detrás de `srv-nginx`: DNS, server block con certbot y
   el primer deploy, los tres. Ver [`produccion.md`](produccion.md).
   - **Queda subir los certificados de ARCA a la VM**, que no viajan por git
     ([`DEPLOYMENT.md`](DEPLOYMENT.md) § 7.2). Hasta que estén, la app anda entera y solo
     contesta 502 lo que sale a ARCA.
   - **El certificado propio de ARCA ya no es un pendiente** (2026-08-28). Los dos `.crt`
     —prod y homo— están emitidos y en `certs/`, el de homologación probado contra ARCA de
     punta a punta, y quedó verificado que dos certificados del mismo CUIT obtienen cada uno
     su propio TA, o sea que FactuMov no puede dejar a Balance360 afuera de ARCA. Ver
     *Los certificados, emitidos* en [`produccion.md`](produccion.md).
   - **Lo único que separa a la app de emitir de verdad es ese scp.** `ARCA_ENV` ya está en
     `prod` en el `.env` de producción: en cuanto `factumov.crt` esté en la VM, el botón de
     emitir produce comprobantes con validez legal.
2. ~~**FactuMov en la landing de InSoft**~~ — **escrita el 2026-08-28.** Tarjeta en
   *Nuestros SaaS* con las cuatro funcionalidades core y el link a
   `factumov.insoft.net.ar`, entrada en el lanzador de apps, y de paso el ícono de producto
   que a Balance360 le faltaba. Ver *La landing, escrita* en [`marca.md`](marca.md).
   - **Falta publicarla**: correr `scp.ps1` desde `E:\Capacitacion\InSoft\LandingPage`, que
     es lo único que toca el server.
3. ~~**Integración con Balance360**~~ — **hecha el 2026-08-29.** Lo que se emite acá queda
   asentado allá como comprobante de venta impago, sin recargarlo a mano. Toca las dos apps:
   Balance360 sumó `POST /api/invoices/issued` —y de paso cerró su `/api`, que estaba
   abierto—, y FactuMov, la conexión por usuario con el token cifrado, el estado de registro
   por factura y los dos reintentos. Ver [`balance360.md`](balance360.md).
   - **Falta emitir el token en el servidor de Balance360** y pegarlo en Ajustes. Hasta que
     eso pase, todo lo demás de FactuMov anda igual y las facturas salen con el estado en
     `null`, que es "no entró al circuito".
4. **Segundo layout del parser** — ver *Parser → Pendiente: un segundo layout*. No bloquea
   nada: hoy el usuario puede cargar el modelo a mano.
5. **WhatsApp**, la otra mitad de la funcionalidad #5. Sin empezar y sin decisión tomada
   sobre qué proveedor.

Y dos cosas que la emisión dejó anotadas y no son unidades todavía:

- **Los valores de `CondicionIva` de Balance360 están mal** — ver *Emisión con CAE → Dos
  códigos heredados*. Acá se corrigieron; allá pueden estar declarando la condición
  equivocada del receptor en cada factura. Sin revisar. La integración **no lo arregla pero
  tampoco lo empeora**: los enums viajan por nombre justamente para que el error de allá no
  se propague a lo que registramos nosotros.
- **Ninguna pantalla usa `/invoices` para reemitir el mes siguiente.** Hoy se vuelve al
  modelo, que es correcto, pero "emitir igual que el mes pasado" es el gesto que más se va a
  repetir. **El comando hablado (2026-08-28) resuelve la mitad**: desde la grilla se dice
  "emitir alquiler mensual desde el 1 de agosto hasta el 31" y la app abre la confirmación con
  todo puesto, sin buscar la tarjeta ni cargar fechas a mano. Lo que sigue faltando es la otra
  mitad, la que no hace falta dictar: partir de lo que se emitió el mes pasado. Ver *Frontend →
  Dictado por voz*.
