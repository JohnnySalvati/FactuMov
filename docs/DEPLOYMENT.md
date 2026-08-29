# FactuMov — Deploy a producción

Producción corre en la **misma VM Ubuntu 24.04 que Balance360** (`192.168.100.16`), detrás
de **srv-nginx** (`192.168.100.9`), que termina el HTTPS y proxea por HTTP a la VM. Son dos
máquinas distintas y es fácil confundirlas: el certificado y el server block van en la `.9`;
el compose, el `.env` y los certificados de ARCA van en la `.16`. Todo vive en
`docker-compose.prod.yml`, que levanta tres servicios. **Está en el aire desde el
2026-08-28**, así que el procedimiento habitual es la § 5 y no la § 2:

| Servicio | Qué es | Puerto |
|---|---|---|
| `db` | Postgres 16, datos en el volumen `postgres_data` | ninguno publicado |
| `app` | El backend: uvicorn + FastAPI, imagen de `backend/Dockerfile` | ninguno publicado |
| `web` | nginx: sirve la SPA y proxea `/api` al `app`, imagen de `frontend/Dockerfile` | **8001** |

La cadena completa es:

```
navegador → srv-nginx .9 :443 → VM .16 :8001 → web (nginx) → app :8000 → db
                                               └─ / → el dist de la SPA
```

**Por qué hay un nginx propio y no dos `location` en srv-nginx.** El prefijo `/api` lo
inventa el proxy del dev server (`vite.config.ts`); el backend no sabe nada de él. Alguien
tiene que sacarlo y servir además el `dist` estático. Poniéndolo en srv-nginx habría que
subir el `dist` a `.9` en cada deploy, o sea un segundo camino de publicación al lado del de
la VM. Con el contenedor, el deploy sigue siendo un `git pull` + `up -d --build` y srv-nginx
no necesita saber de FactuMov más que "proxeá todo a la VM". De paso es donde viven el
`client_max_body_size` y el `limit_req`, que son los dos techos que la app no puede poner.

**El `app` no publica ningún puerto**, a diferencia de Balance360. Solo le habla el `web` por
la red del compose, y eso es lo que hace honesto el `--forwarded-allow-ips="*"` del
entrypoint: el único que puede mandarle un `X-Forwarded-For` es un contenedor nuestro.

---

## 1. Antes de empezar

- **DNS**: `factumov.insoft.net.ar` tiene que apuntar a donde apunta `insoft.net.ar`, o sea
  a srv-nginx.
- **Espacio y memoria en la VM.** Con FactuMov son dos Postgres y dos apps Python con
  WeasyPrint conviviendo. Compose aísla la red, la base y los volúmenes, pero el disco y la
  RAM son de los dos: llenar el disco se lleva puesta la contabilidad de Balance360.
  ```bash
  df -h /              # espacio
  free -h              # memoria
  docker system df     # cuánto de eso es basura de builds viejos
  ```
  Medido el 2026-08-27, antes del primer deploy: **17,3 GB de disco con 11 GB libres**, **4 GB
  de RAM** (3,0 GiB disponibles) y **2 vCPU**. Alcanza: lo más pesado del deploy es el `npm run
  build`, que en esta SPA pica por los 500-700 MB.
  - **No hay espacio para reclamar por el lado de LVM**: `vgs` da `VFree 0`, o sea que el LV ya
    ocupa el volume group entero. Agrandarlo es agrandar el VHDX, y como el disco está colgado
    del controlador SCSI, Hyper-V lo hace **con la VM prendida** — o sea sin bajar Balance360.
    Después, adentro: `growpart /dev/sda 3`, `pvresize /dev/sda3`, `lvextend -l +100%FREE` y
    `resize2fs`. No es urgente; lo que lo va a volver urgente es el cache de BuildKit de `uv` y
    `npm`, que crece con cada deploy.
  - **La VM no tenía swap** (`Swap: 0B`), y se le agregó un swapfile de 2 GB. No es que la
    cuenta no cierre: es que sin swap el kernel no tiene margen, y cuando un build pica alto el
    OOM killer elige a quién matar entre todo lo que hay prendido — que incluye al Postgres de
    Balance360.
- **El 8000 es de Balance360.** FactuMov publica el 8001. Si alguna vez hay que cambiarlo, se
  cambia en `docker-compose.prod.yml` y en el `proxy_pass` de srv-nginx.
- **En el gateway no hay que abrir el 8001.** Ese puerto no sale nunca de la LAN: es el salto
  de srv-nginx a la VM. La puerta desde internet es el 443 de la `.9`, que ya está reenviado
  desde antes. Y abrirlo apuntando a la `.16` sería peor que inútil: pondría la app sin TLS, y
  con la cookie de sesión `Secure` el síntoma es que el login parece andar y después todo
  contesta 401 — el mismo error con disfraz que ya costó una tarde probando desde el celular.

---

## 2. Primer arranque en la VM

> **Ya está hecho** (2026-08-28): la app corre en `factumov.insoft.net.ar`. Esta sección y la
> § 3 quedan como referencia, para cuando haya que rearmar la VM desde cero. **El camino
> normal de todos los días es la § 5**: `git pull` + `up -d --build`. No vuelvas a clonar
> sobre una instalación que anda.

```bash
ssh johnny@192.168.100.16
git clone https://github.com/JohnnySalvati/FactuMov.git
cd FactuMov
```

### 2.1 El `.env`

Se copia de `.env.example` — el de la raíz, **no** el de `backend/`, que es el de
desarrollo — y se completa:

```bash
cp .env.example .env
nano .env
```

Lo que no puede quedar como está:

- `POSTGRES_PASSWORD`, y la misma contraseña adentro de `DATABASE_URL`. Se elige una vez:
  cambiarla después del primer arranque no cambia la del Postgres ya inicializado, solo rompe
  la conexión.
- `SMTP_USER` / `SMTP_PASSWORD`. Con Gmail la contraseña es una *app password*, no la de la
  cuenta. Van las dos o ninguna: con una sola, la config se rechaza al leerla y lo dice en el
  log. El puerto es **587**, no 465: el transporte abre texto plano + STARTTLS, y el 465
  también se rechaza al leer la config.
- `APP_BASE_URL=https://factumov.insoft.net.ar`. De acá cuelgan el link de confirmación y el
  de reset que salen por mail. Con `https://` y con el dominio real; un valor viejo manda
  mails con links muertos y no tiene ningún síntoma en el arranque.
- `OPERATOR_EMAIL`. Los dos avisos que no le van a ningún usuario: que alguien se registró, y
  que un usuario está esperando que aceptemos su designación en ARCA — ese click no lo expone
  ningún web service. Vacío es válido y los dos quedan en el log.
- `ARCA_ENV` va en **`prod`**, y con eso el certificado propio pasa a ser un prerrequisito
  y no una prolijidad. Ver la sección 7.
- `BALANCE360_BASE_URL=https://balance360.insoft.net.ar` y `SECRET_ENCRYPTION_KEY`, que son la
  integración con Balance360. Las dos vacías es válido —la app arranca igual y todo lo demás
  anda—, y lo único que pasa es que la pantalla de Ajustes dice cuál de las dos falta. La
  dirección la pone acá el que deploya y no el usuario: es config, no una pregunta de la app.
  La clave se genera una vez con
  `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`;
  perderla no borra nada, pero obliga a cada usuario a volver a conectar.

### 2.2 Los certificados de ARCA

Nunca viajan por git ni entran a la imagen: llegan por scp y el compose los monta de solo
lectura en `/app/certs`.

```powershell
# desde la máquina de desarrollo
ssh johnny@192.168.100.16 "mkdir -p ~/FactuMov/certs"
scp E:\Capacitacion\InSoft\FactuMov\certs\factumov.crt `
    E:\Capacitacion\InSoft\FactuMov\certs\factumov.key `
    johnny@192.168.100.16:~/FactuMov/certs/
```

Son el certificado y la clave **propios de FactuMov**, del CUIT `20182810674`, y desde el
2026-08-28 los dos existen (sección 7). Que sean los propios y no los de Balance360 es un
prerrequisito y no un detalle: compartirlos es lo que deja a una de las dos apps sin ARCA por
doce horas. Las rutas del `.env` son **las del contenedor**, y los nombres que trae el
`.env.example` son los de estos dos archivos; si los subís con otro nombre hay que ajustar
`ARCA_CERT_PATH` y `ARCA_PRIVATE_KEY_PATH`.

**Ojo con cuál de los dos subís**: `factumov.crt` es el de producción y `factumov-homo.crt` el
de homologación, y se parecen. Subir el de homo con `ARCA_ENV=prod` da 502; subir el de prod a
un entorno de prueba **emite facturas de verdad**. Se distinguen por el emisor
(`openssl x509 -noout -issuer`): `CN=Computadores` es producción, `CN=Computadores Test` no.

**El primer arranque no los necesita.** Sin ellos la app levanta igual y solo contesta 502 lo
que sale a ARCA, así que se puede verificar todo el resto —la SPA, el login, el registro, los
mails— y sumar los certificados después: el mount es de la carpeta entera, así que un archivo
nuevo aparece adentro del contenedor sin reiniciar nada.

Lo que sí necesita un `up -d` es tocar el `.env`.

**Si el archivo falta o el nombre no coincide, el síntoma no lo dice.** `_load_certificate`
levanta `ArcaError` y el endpoint contesta **502**, que en la pantalla se ve igual que un ARCA
caído — el cartel de "no se pudo preguntar", no uno que hable del certificado. Por eso conviene
comparar `exec app ls -la /app/certs` contra `grep ARCA_ .env` antes de apretar el botón de
verificar la delegación.

### 2.3 Levantar

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f app
```

El primer build baja Node, Python y las librerías de Pango, así que tarda unos minutos. Al
arrancar, `docker-entrypoint.sh` corre `alembic upgrade head` y recién después uvicorn: con
`set -e`, una migración que falle deja la app sin levantar en vez de servirla contra un
esquema viejo.

La base arranca vacía y el esquema lo crean las migraciones. **No hay nada que restaurar**: a
diferencia de Balance360, acá no existe una base de desarrollo que sea la fuente de verdad.

---

## 3. El server block de srv-nginx

Va en `192.168.100.9` (`administrator@192.168.100.9`, el mismo server de la landing). La
convención de ese server es un archivo por dominio en `sites-available/` con su symlink en
`sites-enabled/`, así que el de FactuMov es `/etc/nginx/sites-available/factumov.insoft.net.ar`.

**Se escribe con `listen 80` y no con `listen 443`**, aunque el objetivo sea el HTTPS. Un
bloque con `listen 443 ssl` y sin `ssl_certificate` no pasa el `nginx -t`, y el certificado
todavía no existe. El orden es: bloque en el 80, `certbot` valida el dominio por HTTP-01 —para
lo cual necesita justamente ese bloque respondiendo en el 80— y después reescribe el archivo
él mismo, agregando el `listen 443 ssl`, las rutas del certificado y el redirect del 80.

```nginx
server {
    listen 80;
    server_name factumov.insoft.net.ar;

    location / {
        proxy_pass http://192.168.100.16:8001;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Emitir es WSAA + FECompUltimoAutorizado + FECAESolicitar, y ARCA tarda. Con los
        # 60 s de default, un pedido de CAE lento se corta acá *después* de que ARCA
        # autorizó: la factura existe para el fisco y el usuario ve un 504.
        proxy_read_timeout 180s;
        client_max_body_size 12m;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/factumov.insoft.net.ar /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d factumov.insoft.net.ar
sudo nginx -t && sudo systemctl reload nginx
```

**Los `X-Forwarded-*` no son decorativos.** Sin `X-Forwarded-For`, el nginx de la VM no puede
saber quién es el cliente y **todos los usuarios comparten un solo cubo** del rate limiter.
`client_max_body_size` hay que ponerlo también acá: el default de nginx es 1 MB y cortaría la
importación de un PDF antes de que llegue a la VM.

---

## 4. Verificación después de un deploy

Ninguna de estas cosas avisa sola si está mal.

```bash
# 1. Los tres contenedores arriba y el app "healthy"
docker compose -f docker-compose.prod.yml ps

# 2. El mail: si la config no sirve, hay un ERROR acá y ningún otro síntoma
docker compose -f docker-compose.prod.yml logs app | grep -i "mail\|ERROR"

# 3. La API contesta a través del nginx de la VM
curl -s localhost:8001/api/health/          # {"status":"on-line"}

# 4. La SPA se sirve y las rutas internas caen en el index
curl -s -o /dev/null -w '%{http_code}\n' localhost:8001/
curl -s -o /dev/null -w '%{http_code}\n' localhost:8001/modelos/loquesea   # 200, no 404

# 5. La IP del cliente llega de verdad. Si acá aparece 192.168.100.9 o una 172.x en lugar
#    de una IP de internet, el rate limiter está contando a todo el mundo junto: revisar el
#    X-Forwarded-For de srv-nginx y el `set_real_ip_from` de frontend/nginx.conf.
docker compose -f docker-compose.prod.yml logs web | tail -5
```

Y desde afuera, con el dominio: entrar, registrarse con una dirección real, y confirmar que
el mail llega **y que el link abre**. Es lo único que ejercita `APP_BASE_URL`.

---

## 5. Deploys siguientes

En dev, antes de pushear:

```powershell
cd E:\Capacitacion\InSoft\FactuMov\backend
uv run pytest
uv run ruff check .
uv run mypy src
cd ..\frontend
npm run lint
npm run build
```

Y en la VM:

```bash
cd ~/FactuMov
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f app
```

- Reconstruye las dos imágenes. Si `uv.lock` y `package-lock.json` no cambiaron, las capas de
  dependencias salen de cache.
- Recrea `app` y `web`; `db` y su volumen **no se tocan**. Un redeploy nunca borra datos.
- El `dist` de la SPA se construye adentro de la imagen, en una etapa `node`, así que el
  deploy no depende de que alguien se haya acordado de correr `npm run build` antes de
  pushear. Y como esa etapa corre `tsc -b`, si los tipos no cierran el build se corta ahí en
  vez de publicar una SPA rota.

> **En la máquina de desarrollo este compose se corre siempre con `-p`.** El nombre de
> proyecto sale del nombre de la carpeta, así que `docker-compose.prod.yml` y
> `docker-compose.yml` comparten proyecto y volúmenes: levantar el de producción sin `-p` le
> pisa el contenedor `db` al de desarrollo. En la VM no pasa porque el otro no existe. Para
> probarlo localmente:
> `docker compose -p factumov-prod -f docker-compose.prod.yml up -d --build`.

---

## 6. Alembic en producción

**Caso normal: no hacés nada.** Las migraciones se generan en dev, viajan por git y el
entrypoint las aplica en cada deploy. Nunca se corre `alembic revision --autogenerate` en
producción.

```bash
docker compose -f docker-compose.prod.yml exec app alembic current
docker compose -f docker-compose.prod.yml exec app alembic history
```

Si la app no bootea, `exec` no sirve —necesita el contenedor corriendo—, así que va `run`,
que levanta uno temporal solo para el comando:

```bash
docker compose -f docker-compose.prod.yml run --rm app alembic current
docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head
```

**Cuidado con `downgrade`.** Varias migraciones de este proyecto restituyen la forma y no los
datos, y lo dicen en su docstring: `cf79c4f7610c` (los clientes que eran FINAL) y
`b2d5f80c3e17` (el mail copiado en las facturas). Antes de cualquier migración destructiva,
backup.

---

## 7. ARCA está en `prod`, y el certificado propio es el prerrequisito

Desde el 2026-08-28 el `.env.example` de la raíz —el de producción— trae `ARCA_ENV=prod`; el
de `backend/`, que es el de desarrollo, se queda en `homo` — una máquina de desarrollo no
tiene por qué poder emitir de verdad. Con `prod`, cuando el endpoint de emisión contesta 201
hay un comprobante con **validez legal a nombre de un CUIT real** y no hay camino de vuelta: se
deja sin efecto con una nota de crédito, que FactuMov no emite. Es lo único irreversible hacia
afuera que hace la app.

**Y `prod` exige un certificado propio de FactuMov, no el de Balance360.** WSAA se niega a
emitir un TA nuevo mientras el anterior siga vigente, y cada app cachea el suyo en **su
propia** tabla `arca_tickets`, en **su propia** base. Dos apps pidiendo un TA de `wsfe` con el
mismo certificado se lo arrebatan, y la que pierde queda afuera de ARCA hasta doce horas — o
sea que compartirlo pone en riesgo la facturación de Balance360, que ya está en producción.
Mientras FactuMov apuntaba a homologación no pasaba, porque eran certificados distintos; el
cambio de esta variable es exactamente lo que lo destapa.

Por eso `ARCA_CERT_PATH` y `ARCA_PRIVATE_KEY_PATH` apuntan a `factumov.crt` / `factumov.key`.
Si esos archivos no están, todo lo que salga a ARCA —verificar la delegación, consultar el
padrón, emitir— contesta **502** con un `ArcaError` que nombra al certificado, y el resto de la
app anda igual. Eso es deliberado: es lo que impide que el pasaje a `prod` empiece a emitir con
el certificado de Balance360 sin que nadie lo note. Y sigue haciendo de freno aunque los
certificados ya existan, porque `certs/` no viaja por git: en la VM hay que copiarlos a mano
(§ 7.2).

**Que dos certificados del mismo CUIT obtienen cada uno su propio TA está verificado**
(2026-08-28), que era la premisa entera de todo esto: con FactuMov teniendo su TA de `wsfe` de
homologación vigente, WSAA le emitió otro distinto y simultáneo a Balance360 con su `homo.crt`.
El TA es por certificado, no por CUIT.

### 7.1 Sacar el certificado propio

Es del **mismo CUIT `20182810674`**. La delegación es al CUIT, así que las que ya nos
otorgaron siguen valiendo: lo que hay que hacer es habilitarle los servicios al certificado
nuevo.

**Este trámite ya está hecho** (2026-08-28) — lo que sigue es la receta, por si hay que
rehacerlo o renovarlo. En `certs/` —que está en `.gitignore`, así que estas claves no viajan
por git— hay **dos pares completos**, uno por entorno:

| Entorno | Clave | Pedido | Certificado | Emisor | Vence |
|---|---|---|---|---|---|
| Producción | `factumov.key` | `factumov.csr` | `factumov.crt` | `CN=Computadores` | 2028-08-27 |
| Homologación | `factumov-homo.key` | `factumov-homo.csr` | `factumov-homo.crt` | `CN=Computadores Test` | 2028-08-27 |

**Los dos archivos se parecen y solo uno emite de verdad.** Se distinguen por el emisor, no por
el nombre —que lo elegimos nosotros—, así que antes de copiar uno a la VM conviene mirarlo:

```bash
openssl x509 -in certs/factumov.crt -noout -subject -issuer -dates
```

Son **dos claves distintas y no la misma en los dos entornos**, por el mismo motivo por el
que no se comparte con Balance360: el certificado es lo que WSAA mira para decidir si ya
emitió un TA. Y el de homologación existe porque es lo único que deja ensayar el trámite
completo —y la verificación de más abajo— sin tocar producción.

La receta, por si hay que rehacerlo. `MSYS_NO_PATHCONV=1` es solo para Git Bash, que si no
convierte el `-subj` a una ruta de Windows y el CSR sale con el subject equivocado; en
PowerShell no hace falta:

```bash
# 1. Clave privada propia. Que no sea la de Balance360 es la mitad del punto.
openssl genrsa -out factumov.key 2048

# 2. El pedido (CSR). El serialNumber lleva el CUIT y el CN es el alias del certificado.
MSYS_NO_PATHCONV=1 openssl req -new -key factumov.key -out factumov.csr \
  -subj "/C=AR/O=Miguel Salvati/CN=factumov/serialNumber=CUIT 20182810674"
```

**Lo que falta son los dos pasos del portal**, que necesitan Clave Fiscal y no se pueden
automatizar. Son siempre los mismos dos, en los dos entornos, y conviene tenerlos separados en
la cabeza porque el segundo es el que se olvida:

- **Emitir el certificado**: se sube el `.csr` y ARCA devuelve el `.crt`.
- **Habilitarle los servicios a ese certificado**: `wsfe` y `ws_sr_constancia_inscripcion`.
  Un certificado emitido y no habilitado **no falla al leerse**: falla en WSAA, con
  "Computador no autorizado a acceder al servicio", que no nombra al servicio que falta.

**Primero homologación y después producción**, y no por prolijidad: es el único orden en el
que la verificación de convivencia —la de más abajo— se puede hacer antes de depender de ella. En
homo el trámite es gratis, instantáneo y se puede rehacer; en prod hay que pedir el servicio
por Clave Fiscal y esperar.

#### A. Homologación — WSASS

WSASS es el portal de autogestión de homologación: emite el certificado en el momento y
también habilita los servicios, así que los dos pasos se hacen en el mismo lugar.

1. Entrar con Clave Fiscal del `20182810674` a **WSASS**
   (`https://wsass-homo.afip.gob.ar/wsass/portal/main.aspx`). Si el servicio no aparece en la
   lista de la Clave Fiscal, se agrega desde **Administrador de Relaciones** → *Adherir
   servicio* → AFIP → *WSASS - Autogestión Certificados Homologación*.
2. **Crear DN y solicitar nuevo certificado**: pegar el contenido de `certs/factumov-homo.csr`
   —el bloque `BEGIN/END CERTIFICATE REQUEST` entero, incluidas esas dos líneas— y confirmar.
   Devuelve el certificado en pantalla.
3. Copiarlo a `certs/factumov-homo.crt`, en PEM. El `.env` de desarrollo ya lo nombra, así que
   no hay nada más que configurar.
4. **Adherir Certificado a WSN**, una vez por servicio: el DN recién creado con `wsfe`, y otra
   vez con `ws_sr_constancia_inscripcion`.

#### B. Producción — Administración de Certificados Digitales

1. Entrar con Clave Fiscal del `20182810674` al portal de ARCA, servicio **Administración de
   Certificados Digitales**. Si no está en la lista, se adhiere desde **Administrador de
   Relaciones** → *Adherir servicio* → AFIP → *Servicios Interactivos*.
2. **Agregar alias**: nombre `factumov`, y subir el archivo `certs/factumov.csr`.
3. Descargar el `.crt` que queda asociado a ese alias y guardarlo como `certs/factumov.crt`.
4. En **Administrador de Relaciones** → **Nueva Relación**, dos veces, una por servicio:
   - *Servicio* → **Buscar** → AFIP → **WebServices** → *Facturación Electrónica* (`wsfe`).
   - *Representante* → **Buscar** → elegir el **computador** `factumov`, que aparece en la
     lista recién después del paso 2.
   - Confirmar, y repetir todo con el servicio de **constancia de inscripción**
     (`ws_sr_constancia_inscripcion`).

**Las delegaciones que ya nos otorgaron siguen valiendo.** Son de CUIT a CUIT, no al
certificado: lo que hay que rehacer por certificado nuevo es solo el paso 4, que es la relación
entre *nuestro* CUIT y los dos servicios.

**Los nombres de los menús se mueven** —ARCA los renombró varias veces— pero las dos cosas que
hay que conseguir no: un `.crt` a partir del `.csr`, y ese certificado habilitado para los dos
servicios.

#### C. Probar que quedó bien

Con `factumov-homo.crt` en `certs/`, desde `backend/` y con este equipo en `homo`:

```powershell
uv run python -c @'
from factumov.services import arca, padron
print(arca.get_delegate_tax_id())            # 20182810674, leido del certificado
print(padron.get_taxpayer("30500010912"))    # INSCRIPTO — ejercita WSAA + el padron
'@
```

El primero solo lee el archivo: si contesta, el `.crt` y la `.key` son un par válido. El
segundo sale a ARCA de verdad, así que es el que prueba los dos servicios del paso 4 — si
falla con "Computador no autorizado", lo que falta es la habilitación y no el certificado.
Después, el circuito completo se prueba desde la app, verificando la delegación de una
identidad fiscal.

**Hecho el 2026-08-28**: devolvió `20182810674` y el padrón contestó INSCRIPTO.

##### La convivencia con Balance360, verificada

Era la premisa entera de esta salida y se hizo el 2026-08-28, con el par de homologación: con
FactuMov teniendo su TA de `wsfe` vigente —obtenido con `factumov-homo.crt`— se le pidió otro a
WSAA con el `homo.crt` de Balance360, y **lo emitió: distinto y simultáneo**. O sea que el TA es
por certificado y no por CUIT, que es lo que deja a las dos apps convivir bajo el mismo
`20182810674` sin arrebatarse el ticket.

Vale la pena rehacerlo si algún día se cambia de certificado. Se hace en homologación, donde no
hay nada que romper, comparando los dos tokens:

```powershell
uv run python -c @'
import os
from factumov.services import arca
a = arca.request_ticket("wsfe")                          # con el cert que tenga el .env
os.environ["ARCA_CERT_PATH"] = "E:/Capacitacion/InSoft/Balance360/Balance360/certs/homo.crt"
os.environ["ARCA_PRIVATE_KEY_PATH"] = "E:/Capacitacion/InSoft/Balance360/Balance360/certs/balance360.key"
arca.get_arca_settings.cache_clear()
b = arca.request_ticket("wsfe")                          # con el de Balance360
print("dos TA distintos y simultaneos" if a.token != b.token else "MISMO TA: se pisan")
'@
```

Si diera "MISMO TA", las opciones son compartir el cache de tickets entre las dos apps
—acoplarlas, feo— o que FactuMov emita bajo un CUIT propio.

### 7.2 Ponerlo en la VM

```powershell
scp E:\Capacitacion\InSoft\FactuMov\certs\factumov.crt `
    E:\Capacitacion\InSoft\FactuMov\certs\factumov.key `
    johnny@192.168.100.16:~/FactuMov/certs/
```

El mount es de la carpeta entera, así que los archivos aparecen adentro del contenedor sin
reiniciar nada. Si además hubiera que tocar el `.env`, ahí sí va un `up -d` — sin `--build`,
porque no cambió ninguna imagen.

Después, la prueba: verificar la delegación de una identidad fiscal desde la app. Si contesta
502, comparar `docker compose -f docker-compose.prod.yml exec app ls -la /app/certs` contra
`grep ARCA_ .env` antes de buscar por otro lado.

**La primera emisión real conviene hacerla a conciencia**, con un comprobante que de todos
modos había que emitir: es la primera vez que el botón produce algo que no se puede deshacer.

---

## 8. Backups

Hoy no hay ninguno. El comando, en la VM (bash redirige binarios sin problema, a diferencia
de PowerShell):

```bash
cd ~/FactuMov
docker compose -f docker-compose.prod.yml exec db sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backup_$(date +%Y%m%d).dump
```

Bajarlo:

```powershell
scp johnny@192.168.100.16:~/FactuMov/backup_20260827.dump .\prod.dump
```

Restaurar, con la app apagada para que nadie escriba en el medio:

```bash
docker compose -f docker-compose.prod.yml stop app
docker compose -f docker-compose.prod.yml cp backup_20260827.dump db:/tmp/
docker compose -f docker-compose.prod.yml exec db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges /tmp/backup_20260827.dump'
docker compose -f docker-compose.prod.yml start app
```

---

## 9. Cosas que muerden

- **502 en `/api` y la SPA carga bien.** El `app` no está arriba o se está reiniciando:
  `docker compose -f docker-compose.prod.yml logs app`. El caso clásico es una migración que
  falló. El nginx de la VM resuelve la IP del `app` por request contra el DNS de Docker
  (`resolver 127.0.0.11`), así que un contenedor recreado **no** es la causa — eso es lo que
  pasaba resolviéndola una sola vez al arrancar.
- **Deployaste y en la app no cambió nada** —ni error, ni 502, ni nada raro en los logs—.
  Casi siempre es un `up -d` **sin `--build`**. El `git pull` trae el código, pero el `dist` de
  la SPA se construye adentro de la imagen: sin `--build`, Docker reusa la que ya tenía y sirve
  el build anterior. La pista está en la salida del `up`: si los contenedores dicen `Running` en
  lugar de `Recreated`, no se reconstruyó nada. Pasó el 2026-08-28 con el efecto de luz de las
  tarjetas. La § 5 es `up -d --build`, y el `--build` es la mitad del comando, no un opcional.

- **404 al recargar adentro de la app** (`/modelos/algo`): se rompió el `try_files` del
  fallback en `frontend/nginx.conf`.
- **413 al importar un PDF grande.** Hay tres techos y corta el más bajo: el
  `client_max_body_size` de srv-nginx, el de `frontend/nginx.conf` (12m) y el
  `MAX_UPLOAD_BYTES` de la app (10 MiB). El que tiene que contestar el caso normal es el
  último, que es el único que trae un mensaje en castellano.
- **Todos los usuarios comparten el mismo límite.** Es el punto 5 de la sección 4: la IP del
  cliente no está llegando.
- **Los mails no salen y no hay error.** Los que solo acompañan —las instrucciones de
  delegación, el aviso de contraseña cambiada— son best effort y únicamente loguean. Los que
  son el producto del request (registro, reenvío, reset, mandar una factura) contestan 503.
  Si el registro anda y el aviso de delegación no llega, mirar el log del `app`.
- **"El CEE ya posee un TA válido".** Hay un ticket vivo emitido con el mismo certificado
  desde otro lado: típicamente la máquina de desarrollo apuntando al mismo `ARCA_ENV`, o
  Balance360 si alguien puso acá su certificado de producción en lugar del propio de
  FactuMov (sección 7). Hay que esperar a que venza, y son hasta doce horas.
- **502 en todo lo que toca ARCA, y en nada más.** Es el estado esperado mientras
  `factumov.crt` y `factumov.key` no existan: la app quedó en `prod` antes que el certificado
  propio, a propósito. El log del `app` trae el `ArcaError` con el path que no pudo leer.
