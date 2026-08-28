# FactuMov — Deploy a producción

Producción corre en la **misma VM Ubuntu 24.04 que Balance360** (`192.168.100.16`), detrás
de **srv-nginx** (`192.168.100.9`), que termina el HTTPS y proxea por HTTP a la VM. Son dos
máquinas distintas y es fácil confundirlas: el certificado y el server block van en la `.9`;
el compose, el `.env` y los certificados de ARCA van en la `.16`. Todo vive en
`docker-compose.prod.yml`, que levanta tres servicios:

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
- `OPERATOR_EMAIL`. Hoy es lo único que avisa que un usuario está esperando que aceptemos su
  designación en ARCA — ese click no lo expone ningún web service.
- `ARCA_ENV` queda en **`homo`**. Ver la sección 7.

### 2.2 Los certificados de ARCA

Nunca viajan por git ni entran a la imagen: llegan por scp y el compose los monta de solo
lectura en `/app/certs`.

```powershell
# desde la máquina de desarrollo
ssh johnny@192.168.100.16 "mkdir -p ~/FactuMov/certs"
scp E:\Capacitacion\InSoft\Balance360\Balance360\certs\homo.crt `
    E:\Capacitacion\InSoft\Balance360\Balance360\certs\balance360.key `
    johnny@192.168.100.16:~/FactuMov/certs/
```

Los de homologación son los de Balance360, que son de este mismo CUIT (`20182810674`). Las
rutas del `.env` son **las del contenedor**, así que si los archivos se llaman distinto hay
que ajustar `ARCA_CERT_PATH` y `ARCA_PRIVATE_KEY_PATH`.

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

Va en `192.168.100.9` (`administrator@192.168.100.9`, el mismo server de la landing). Es el
bloque de Balance360 con otro dominio y otro puerto:

```nginx
server {
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

    listen 443 ssl;   # el resto —certificado, redirect del 80— lo escribe certbot
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d factumov.insoft.net.ar
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

## 7. ARCA: se sale con `homo`, y el pasaje a `prod` es otro día

Estar en producción y estar emitiendo de verdad son **dos hitos distintos**, y juntarlos haría
que la primera prueba contra el server sea también la primera factura irreversible. Con
`ARCA_ENV=prod`, cuando el endpoint de emisión contesta 201 hay un comprobante con validez
legal a nombre de un CUIT real y no hay camino de vuelta: se deja sin efecto con una nota de
crédito, que FactuMov no emite.

**Antes de tocar esa variable hay que resolver la colisión del certificado con Balance360.**
WSAA se niega a emitir un TA nuevo mientras el anterior siga vigente, y cada app cachea el
suyo en **su propia** tabla `arca_tickets`, en **su propia** base. Dos apps pidiendo un TA de
`wsfe` con el mismo certificado se lo arrebatan, y la que pierde queda afuera de ARCA hasta
doce horas. Hoy no pasa porque FactuMov apunta a homologación y Balance360 a producción: son
certificados distintos. La colisión aparece justo el día del cambio, que es lo que la vuelve
fácil de no ver venir.

La salida esperada es un **certificado propio de FactuMov**, del mismo CUIT `20182810674`. La
delegación es al CUIT, así que las que ya nos otorgaron siguen valiendo; lo que hay que hacer
es habilitarle a ese certificado nuevo los servicios (WSFE y `ws_sr_constancia_inscripcion`).
Falta verificar en homologación que un certificado distinto obtiene su propio TA — el error
nombra al CEE, o sea al certificado, así que todo apunta a que sí, pero es la premisa entera
de la salida.

El pasaje, cuando llegue, es: subir los certificados de producción, cambiar `ARCA_ENV`,
`ARCA_CERT_PATH` y `ARCA_PRIVATE_KEY_PATH` en el `.env`, y `up -d` — sin `--build`, porque no
cambió ninguna imagen.

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
  Balance360 el día que compartan el de producción. Hay que esperar a que venza.
