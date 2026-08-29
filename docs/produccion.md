# FactuMov — Producción

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

**La app está corriendo en producción** desde el 2026-08-28, en `factumov.insoft.net.ar`.
[`DEPLOYMENT.md`](DEPLOYMENT.md) es el procedimiento completo — acá abajo van solo las
decisiones, que es lo que no se deduce leyendo los archivos.

| Archivo | Rol |
|---|---|
| `docker-compose.prod.yml` | Los tres servicios: `db`, `app` y `web` |
| `backend/Dockerfile` + `docker-entrypoint.sh` | La imagen del backend; migraciones y después uvicorn |
| `frontend/Dockerfile` + `nginx.conf` | Build de la SPA en una etapa `node`, y el nginx que junta las dos mitades |
| `.env.example` (raíz) | Plantilla del `.env` de producción |
| `.gitattributes` | Que el entrypoint y el `.conf` lleguen a Linux con LF |

Sigue valiendo lo decidido antes de escribir nada: va en la **misma VM que Balance360** —
Compose ya aísla red, Postgres y volúmenes, así que una VM aparte solo compraría que un deploy
no pueda tumbar al otro, a cambio de otro host que parchear, otra copia de los certificados y
otra rutina de backup. Balance360 se queda con el 8000 y FactuMov publica el **8001**. Y antes
de empezar hay que mirar `df -h` y `free -h`: el disco es el único modo de falla que quedó
compartido, y llenarlo se lleva puesta la contabilidad de Balance360.

## Son tres servicios y solo uno publica puerto
El `app` **no publica el 8000**, a diferencia de Balance360, donde srv-nginx le habla directo.
Acá el único que le habla es el `web` por la red del compose, y eso no es prolijidad: es lo
que hace honesto el `--forwarded-allow-ips="*"` de uvicorn. Ese `*` significa "confío en el
X-Forwarded-For del que se conectó", y solo se puede decir cuando el que se conecta no puede
ser cualquiera.

- **Dos Dockerfiles con su propio contexto** (`backend/` y `frontend/`), no uno en la raíz.
  Un cambio de CSS no tiene por qué invalidar la capa de dependencias de Python.
- **El `dist` se construye adentro de la imagen**, en una etapa `node`. El deploy no depende de
  que alguien se acuerde de correr `npm run build`, y como esa etapa corre `tsc -b`, los tipos
  que no cierran cortan el build en vez de publicar una SPA rota.
- **`fonts-dejavu-core` no es opcional en la imagen del backend.** `templates/invoice.html`
  pide "DejaVu Sans" por nombre; sin la fuente el PDF sale igual, con la sustituta que elija
  fontconfig y las columnas corridas.
- **Un solo worker de uvicorn.** El rate limiter guarda su estado en memoria del proceso, así
  que con N workers el límite efectivo es N veces el configurado. Con uno, los números del
  código son los números reales, y la carga esperada es un puñado de facturas por mes.
- **El healthcheck del `app` lo hace `urllib` y no `curl`**, que no está en la imagen slim de
  uv. Va a `/health/` con la barra: sin ella FastAPI contesta un 307.

## El nginx del compose, que es donde están casi todas las decisiones
- **Sabe quién es el cliente, y no le cree al cliente.** `set_real_ip_from` (srv-nginx y la red
  del compose) + `real_ip_recursive`, y después `proxy_set_header X-Forwarded-For $remote_addr`
  — un solo valor, sobrescrito, no `$proxy_add_x_forwarded_for`. Sin la primera mitad,
  `request.client` es srv-nginx y **todos los usuarios comparten un solo cubo** del rate
  limiter; sin la segunda, cualquiera puede mandarse un `X-Forwarded-For` y correrle la cuenta
  a otro. **Verificado**: un request con `X-Forwarded-For: 6.6.6.6` llega al backend con la IP
  real y no con la inventada.
- **La IP del `app` se resuelve por request, con `resolver 127.0.0.11` y la URL detrás de una
  variable.** Con `proxy_pass http://app:8000` a secas, nginx la resuelve una vez al arrancar y
  se la guarda: el primer deploy que recree solo el backend —o sea el caso normal— deja esto
  contestando 502 hasta que alguien reinicie el `web` a mano. El precio es que la barra final
  de `proxy_pass` ya no puede comer el prefijo, así que `/api` lo saca un `rewrite`.
- **Dos zonas de `limit_req`, y `/auth/me` queda afuera de la apretada.** Los cinco endpoints
  que mandan mail o queman argon2 tienen su propio cubo; `/auth/me` lo llama el `AuthProvider`
  en cada carga de página, así que meterlo ahí castigaría al que recarga. Los dos límites están
  muy por encima de los de la app a propósito: el que tiene que contestar 429 con un mensaje
  entendible —y sabiendo limitar por dirección de email— es el backend. Esto solo corta la
  inundación. Con `limit_req_status 429`, que es el mismo status que usa la app.
- **`client_max_body_size 12m`, un poco arriba de los 10 MiB de `MAX_UPLOAD_BYTES`.** Cierra el
  pendiente que dejó anotado el endpoint de importación —el guard de la app acota lo que el
  proceso copia y parsea, no lo que el server ingiere— pero deliberadamente no lo pisa: el que
  contesta el caso normal sigue siendo la app, que es la única de las tres capas que trae un
  mensaje en castellano.
- **`proxy_read_timeout 180s`.** Emitir es WSAA + `FECompUltimoAutorizado` + `FECAESolicitar`.
  Con los 60 s de default, un pedido de CAE lento se corta **después** de que ARCA autorizó: la
  factura existe para el fisco y el usuario ve un 504. Va también en srv-nginx, que tiene el
  suyo.
- **`proxy_connect_timeout 3s`, y no es lo mismo que el anterior (2026-08-28).** Uno es cuánto
  se espera la *respuesta*; este es cuánto se espera para *abrir el socket*. `app` está en la
  misma red de Docker: conectar sale en milisegundos o no sale, porque el contenedor no está
  escuchando. Con los 60 s de default, cada `up -d --build` deja una ventana en la que nginx no
  puede conectarse y **cada pedido se cuelga un minuto** antes de rendirse. Pasó de verdad el
  2026-08-28, en el deploy del spike de voz: la app venía andando —el build corre con el
  contenedor viejo todavía arriba—, y cuando Compose recreó `app` todas las pantallas quedaron
  en "Cargando…" cerca de un minuto y después volvieron solas. Bajarlo **no acorta la ventana**;
  la vuelve honesta, con un 502 inmediato que la SPA ya sabe mostrar como error en vez de un
  minuto de spinner sin ninguna pista de la causa.
  - La ventana en sí es el precio del `up -d --build`: `docker-entrypoint.sh` corre
    `alembic upgrade head` y recién después uvicorn. Sacarla del todo pediría dos contenedores
    de `app` y un cambio de upstream, que para esta app es maquinaria de sobra.
- **`try_files ... /index.html` para la SPA**, y el `index.html` con `no-cache` mientras
  `/assets/` va con `immutable` a un año. Los nombres de los assets traen el hash del
  contenido; el que los nombra no puede cachearse ni un minuto, o el navegador pide los assets
  de la versión anterior y el deploy no llega nunca.

## El `.env` de producción vive en la raíz, no en `backend/`
Es un archivo distinto del `backend/.env` de desarrollo, y no por comodidad: incluye además
las credenciales del contenedor Postgres, que en desarrollo están escritas adentro de
`docker-compose.yml`. Va en la raíz porque es donde está el compose que lo consume, que es
también quien interpola `${POSTGRES_USER}` en el healthcheck. El de desarrollo se queda donde
está: son dos contextos, dos archivos, y `.env.example` de cada lado lo aclara en la primera
línea.

- **`ARCA_WSDL_CACHE_PATH` apunta al volumen `wsdl_cache`.** Sin volumen, cada deploy vuelve a
  bajar los WSDL de ARCA y el primer request después de un redeploy paga esa demora.
- **`ARCA_ENV` está en `prod` desde el 2026-08-28** — ver *El pasaje a `prod`*. Es este
  archivo y no el de `backend/`, que es el de desarrollo y se quedó en `homo`. Hasta ese día
  salía en `homo`, con el argumento de que estar en producción y estar emitiendo de verdad son
  dos hitos distintos. Lo que reemplaza a esa separación es el certificado: la puerta la abre
  sacar el certificado propio y no acordarse de cambiar una variable. **Desde el 2026-08-28 a
  la tarde ese certificado existe** — ver *Los certificados, emitidos*.

## El pasaje a `prod` (2026-08-28)
Pedido por Miguel. `ARCA_ENV=prod` en el `.env.example` de la raíz —el de producción— con
[`DEPLOYMENT.md`](DEPLOYMENT.md) § 7 reescrito: dejó de decir "se sale con `homo`" y ahora
cuenta cómo se saca el certificado propio. **El código no cambió** — WSAA, WSFE y el padrón ya tenían sus dos
URLs por entorno, así que el pasaje es enteramente de configuración.

El mismo día, y a pedido de Miguel, la máquina de desarrollo **volvió a `homo`** y se
generaron las claves — ver *Las claves propias, y el desarrollo de vuelta en homo*.

- **El guardarraíl dejó de ser la variable y pasó a ser el certificado**, y esa es la decisión
  de fondo. `ARCA_CERT_PATH` apunta a `factumov.crt`: mientras ese archivo no estaba, todo lo
  que salía a ARCA contestaba 502 con un `ArcaError` que nombra el path, y el resto de la app
  andaba igual. Es un freno mejor que el anterior porque falla ruidoso y en el lugar correcto,
  en vez de depender de que alguien recuerde no tocar una línea del `.env`. **Sigue siendo el
  guardarraíl aunque el certificado ya exista**: el archivo está en `certs/`, que no viaja por
  git, así que una instalación nueva arranca frenada hasta que alguien lo copie a mano.
- **El certificado propio no es prolijidad: es lo que protege a Balance360.** Compartir el de
  producción hace que las dos apps se arrebaten el TA —WSAA no emite uno nuevo mientras el
  anterior siga vigente, y cada app lo cachea en su propia tabla— y la que pierde queda afuera
  de ARCA hasta doce horas. Del otro lado de esa falla está la facturación real de Balance360,
  que ya está en producción. Miguel eligió explícitamente sacar el certificado propio primero,
  y esta configuración es la que hace imposible saltearse ese paso.
- **Un certificado distinto obtiene su propio TA — confirmado el 2026-08-28.** Era la premisa
  entera de la salida y estuvo pendiente hasta que hubo dos certificados con los cuales
  probarla. Se pidieron los dos TA de `wsfe` de homologación a la vez: con FactuMov teniendo el
  suyo vigente (obtenido con `factumov-homo.crt`), WSAA le emitió **otro, distinto y
  simultáneo**, a Balance360 con su `homo.crt`. O sea que el TA es por certificado y no por
  CUIT, que es lo que hace que las dos apps puedan convivir bajo el mismo `20182810674` sin
  arrebatarse el ticket. Si hubiera dado al revés, las opciones eran compartir un cache de
  tickets entre las dos apps —acoplarlas, feo— o que FactuMov emitiera bajo un CUIT propio.
- **El `.env` de desarrollo quedó en `prod` por unas horas, y se revirtió el mismo día.** El
  argumento del pasaje era sobre la instalación de producción; arrastrar con él a la máquina de
  desarrollo le sacaba la red de contención a todas las pruebas locales sin que nadie ganara
  nada. Ver el punto que sigue.

## Las claves propias, y el desarrollo de vuelta en homo (2026-08-28)
`certs/` —que ya estaba en `.gitignore`— tiene ahora **dos pares** de clave y CSR:
`factumov.key`/`.csr` para producción y `factumov-homo.key`/`.csr` para homologación. Los
`.crt` los emitió el portal de ARCA el mismo día — ver *Los certificados, emitidos*. El
trámite completo, en [`DEPLOYMENT.md`](DEPLOYMENT.md) § 7.1.

- **Son dos claves y no una en dos entornos**, por el mismo motivo por el que no se comparte
  con Balance360: lo que WSAA mira para decidir si ya emitió un TA es el certificado. Con una
  sola clave para los dos entornos, probar en homo desde el escritorio podría dejar sin ticket
  a la instalación de producción.
- **El par de homologación fue además el instrumento de la verificación**: era el segundo
  certificado que hacía falta para comprobar que dos certificados del mismo CUIT obtienen cada
  uno su propio TA. Ya se hizo, y dio que sí — ver *El pasaje a `prod`*.
- **La máquina de desarrollo vuelve a `homo`**, y con ella el `backend/.env.example`, que es su
  plantilla. Que el template de desarrollo trajera `prod` significaba que un equipo nuevo
  montado desde ahí arrancaba pudiendo emitir de verdad — el `.env.example` de la raíz, que es
  el de producción, se queda en `prod`.
- **Apunta al `factumov-homo.crt` propio**, no a los certificados de homo de Balance360. Los de
  Balance360 quedan escritos como comentario al lado, a una línea de distancia, para el que
  necesite probar contra ARCA antes de tener el certificado — que fue exactamente la situación
  hasta el 2026-08-28 a la tarde.

## Los certificados, emitidos (2026-08-28)
Los dos `.crt` salieron del portal de ARCA y están en `certs/`, al lado de sus claves. Con eso
cae el último prerrequisito de la salida a producción: la app ya no está apuntando a un archivo
que no existe.

| Entorno | Archivos | Emisor del certificado | Vence |
|---|---|---|---|
| Producción | `factumov.crt` + `factumov.key` | `CN=Computadores, O=AFIP` | 2028-08-27 |
| Homologación | `factumov-homo.crt` + `factumov-homo.key` | `CN=Computadores Test, O=AFIP` | 2028-08-27 |

Los dos son del **mismo CUIT `20182810674`** (va en el `serialNumber` del subject), así que las
delegaciones que ya nos otorgaron siguen valiendo: son de CUIT a CUIT y no al certificado.

- **Se distinguen por el emisor y no por el nombre del archivo.** El de producción lo firma
  `CN=Computadores` y el de homologación `CN=Computadores Test`. Vale la pena mirarlo con
  `openssl x509 -noout -issuer` antes de copiar uno a la VM: los nombres de archivo los elegimos
  nosotros y un error ahí no falla, **emite**.
- **El de homologación quedó probado de punta a punta**, y no solo leído: `get_delegate_tax_id()`
  devuelve el CUIT del certificado —o sea que el `.crt` y la `.key` son un par válido— y
  `get_taxpayer("30500010912")` sale a ARCA y vuelve con INSCRIPTO, lo que ejercita WSAA más el
  padrón, o sea los dos servicios que hubo que habilitarle al certificado nuevo.
- **El de producción no se probó, y es a propósito.** La única llamada que lo ejercitaría sin
  emitir nada es la verificación de delegación, y conviene hacerla desde la VM, que es donde va
  a vivir: probarla acá dejaría un TA de producción emitido contra un certificado que todavía no
  está en su lugar definitivo. La prueba real es la de [`DEPLOYMENT.md`](DEPLOYMENT.md) § 7.2.
- **Vencen el 2028-08-27**, o sea a dos años. No hay ningún aviso automático: cuando venza, todo
  lo que sale a ARCA va a empezar a contestar 502 y el motivo no va a estar a la vista. Renovar
  es rehacer el § 7.1 con la misma clave.

## `.gitattributes`, que no estaba
`docker-entrypoint.sh` y `nginx.conf` se ejecutan adentro de un contenedor Linux, y en esta
máquina `core.autocrlf` está en `true`. Con CRLF, `sh` falla con un "not found" que nombra al
intérprete y no al archivo — un error que no se parece en nada a su causa. Hoy no muerde porque
el build corre sobre un `git clone` hecho en la VM, pero eso es una propiedad del procedimiento
y no del repo.

## Qué se verificó en esta máquina y qué no
El stack entero se levantó local con `-p factumov-prod` y contestó: las 16 migraciones
aplicadas, uvicorn arriba, `/api/health/` a través del nginx, la SPA servida, `/modelos/algo`
cayendo en el index, gzip, los headers de cache, el 401 de `/api/auth/me` sin cookie, el 429
del `limit_req` después del burst, y el `X-Forwarded-For` falso ignorado.

Lo único que **no** se pudo probar acá es el bind mount de `./certs`: Docker Desktop no tiene
compartido el disco `E:` y el mount se cuelga sin error. Es un límite de esta máquina —en la VM
el bind es nativo— pero significa que la primera vez que ese volumen se monta de verdad es en
producción, así que conviene mirar que `/app/certs` tenga los dos archivos antes de dar por
buena la verificación de delegación.

## La salida, hecha (2026-08-28)
Los tres pasos que durante semanas figuraron acá como pendientes —y que ninguna sesión de Code
podía dar, porque necesitan accesos que no tiene— están hechos:

1. **El registro DNS** de `factumov.insoft.net.ar`, que resuelve al mismo IP que
   `insoft.net.ar` (`190.111.232.77`, o sea srv-nginx).
2. **El server block en `srv-nginx`** (`administrator@192.168.100.9`) con su certificado de
   certbot. El bloque está escrito en [`DEPLOYMENT.md`](DEPLOYMENT.md) § 3.
3. **El primer deploy en la VM** (`192.168.100.16`), con la app levantada y sirviendo.

O sea que [`DEPLOYMENT.md`](DEPLOYMENT.md) § 2 y § 3 pasaron a ser referencia —lo que se hace
cuando hay que rearmar todo— y el camino normal ahora es § 5: `git pull`, `up -d --build`.

**Lo único que quedó afuera del primer deploy son los certificados de ARCA**, que no viajan por
git y hay que subir por scp (§ 7.2). Hasta que estén, la app anda entera y solo contesta 502 lo
que sale a ARCA — que es el guardarraíl funcionando, no un bug.

**Son dos máquinas y se confunden fácil.** srv-nginx es la `192.168.100.9` —ahí van el server
block y el certificado— y la VM es la `192.168.100.16`, donde viven el compose, el `.env` y los
certificados de ARCA. El `DEPLOYMENT.md` de Balance360 nombra a la segunda como `<vm>` y nunca
la escribe; el de FactuMov la tiene puesta.

Ninguna de las dos se alcanza desde la máquina de desarrollo sin la VPN levantada: están en
`192.168.100.x` y la LAN de casa es `192.168.1.x`.

## Que los logs se vean (2026-08-29)
`src/factumov/logging_config.py`, llamado desde el `lifespan`. Nace de una falla que costó una
sesión entera de diagnóstico sobre una delegación que no verificaba: **los `logger.info` de la
app no se imprimían en ninguna parte.**

Uvicorn configura **sus** loggers (`uvicorn`, `uvicorn.error`, `uvicorn.access`) y no toca el
root. Como el proyecto nunca configuró nada, todo lo que la app logueaba caía en
`logging.lastResort` —el handler de emergencia de la stdlib—, que imprime a stderr **de WARNING
para arriba**. O sea que la app solo sabía contar lo que salía mal.

Eso no era cosmético. El barrido de delegaciones anuncia su camino feliz con dos INFO
(`main.py` y `services/delegation_watch.py`) y saltea con un DEBUG, así que en un
`docker compose logs app` **el barrido funcionando, el barrido sin nada que hacer y el barrido
muerto se ven exactamente igual**: en silencio. Diagnosticar por qué una delegación no se
verificaba sola empezó, por eso, sin ninguna evidencia.

- **El nivel se pone en el logger `factumov`, no en el root.** Poner el root en INFO prendería
  también el de zeep, urllib3 y SQLAlchemy, y los dos renglones que importan quedarían
  enterrados — el mismo problema con la forma invertida. El root queda en WARNING, que es el
  piso razonable para las librerías, y hay un test de cada lado.
- **Que eso alcance depende de una sutileza que conviene tener escrita**: al propagar, un record
  ya admitido por el logger que lo emitió no vuelve a chequear el nivel de los loggers de
  arriba, solo el de los handlers. Por eso `factumov` en INFO alcanza con el root en WARNING.
- **`LOG_LEVEL`, default INFO.** El default tiene que ser el que hace visible el trabajo de
  fondo, que es justo lo que no se veía. Los niveles de la app están elegidos para eso: el
  camino feliz es INFO y lo raro es WARNING o ERROR, así que INFO es la bitácora y no ruido.
- **A stderr, que es donde escribe uvicorn**, para que el orden de los renglones entre las dos
  fuentes se conserve.
- **Se llama desde el `lifespan` y no en el import de `main`.** Tocar la config global de
  `logging` al importar se la impondría a cualquiera que importe el módulo — los tests, sin ir
  más lejos, que arman su `TestClient` sin levantar el lifespan. El lifespan es exactamente el
  momento en que esto pasa a ser un proceso servidor.
- **Idempotente**, con una marca sobre el handler propio: sin eso, una segunda llamada
  duplicaría cada línea.

## Lo que ya estaba decidido y sigue igual
- **Backups.** Hoy no hay ninguno de FactuMov. El comando está en
  [`DEPLOYMENT.md`](DEPLOYMENT.md) § 8.
- **El barrido de delegaciones no necesita nada especial**: vive en el `lifespan` y con N
  workers barre uno solo, por el `pg_try_advisory_xact_lock`.

