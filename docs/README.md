# Documentación de FactuMov

El **porqué** de cada decisión del proyecto, un archivo por área. Lo que aplica a toda sesión
sin importar qué se toque —reglas de trabajo, stack, convenciones— está en
[`../CLAUDE.md`](../CLAUDE.md), que es el único archivo que se carga siempre.

La regla para escribir acá es la misma de siempre: **se anota la decisión, la alternativa que
se descartó y el motivo.** El diff ya dice qué cambió; lo que no se puede reconstruir después
es por qué.

## El mapa

| Archivo | Qué hay adentro |
|---|---|
| [`producto.md`](producto.md) | Objetivo, las cinco funcionalidades core, decisiones de producto y **las unidades pendientes en orden** |
| [`desarrollo.md`](desarrollo.md) | Los tres procesos que hay que levantar, cómo llegar desde el celular, por qué HTTPS en dev no es opcional, el proxy de Vite |
| [`modelo-de-datos.md`](modelo-de-datos.md) | El principio rector (`InvoiceTemplate` = `Invoice` menos lo que cambia), las tablas, las desviaciones respecto de Balance360 y **cómo se deduce la letra del comprobante** |
| [`parser-e-importacion.md`](parser-e-importacion.md) | El relevamiento de los servicios de Balance360, el parser de PDF y sus reglas por letra, el segundo layout pendiente, y `POST /invoice-templates/import` |
| [`autenticacion.md`](autenticacion.md) | Sesión opaca en cookie, registro self-serve con confirmación, reset de contraseña, los seis mails, rate limiting y por qué el fallo de SMTP se ve |
| [`arca.md`](arca.md) | WSAA y el ticket en tabla, el padrón, la delegación y sus **dos partes**, el rechequeo, y por qué no hay paquete compartido con Balance360 |
| [`emision-y-envio.md`](emision-y-envio.md) | Pedir el CAE, los importes y su redondeo, los dos códigos heredados que estaban mal, el PDF con el QR fiscal y el envío por email |
| [`frontend.md`](frontend.md) | La SPA: sesión, mobile-first, la grilla de tarjetas y su gesto, y los detalles que costaron una vuelta |
| [`ownership-y-tests.md`](ownership-y-tests.md) | `user_id` y el scoping de todas las queries, y las convenciones de la suite |
| [`marca.md`](marca.md) | El ícono, el acento verde, los PNG y el manifest — y **la landing de InSoft**: la tarjeta de FactuMov, el ícono que le faltaba a Balance360 y cómo se publica |
| [`produccion.md`](produccion.md) | Las **decisiones** del deploy: los tres servicios, el nginx del compose, el `.env` de producción, el pasaje a `prod` |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | El **procedimiento**: qué se corre, en qué máquina y en qué orden |

`produccion.md` y `DEPLOYMENT.md` son las dos mitades de lo mismo y conviene no mezclarlas: el
primero dice **por qué** está armado así, el segundo **qué tipear**. Una decisión nueva va al
primero; un paso que cambió, al segundo.

## Referencias cruzadas

El texto está lleno de referencias del estilo *ver **Sesiones*** o *ver **El fallo de SMTP se
ve***. Nombran una **sección**, no un archivo, porque hasta el 2026-08-28 todo vivía en un solo
documento. Siguen siendo válidas: la sección existe, y la tabla de arriba dice en qué archivo
buscarla. Cuando la referencia cruza de archivo y es de las que se siguen seguido, está puesto
el link.
