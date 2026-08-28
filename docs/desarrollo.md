# FactuMov — Cómo se corre en desarrollo

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

## Cómo se corre — y cómo llegar desde el celular
Son tres procesos, cada uno en su terminal. Los comandos son de PowerShell, que no tiene `&&`.

```powershell
# terminal 1 — la base
docker compose up -d

# terminal 2 — el backend
cd E:\Capacitacion\InSoft\FactuMovackend
uv run alembic upgrade head          # solo si hay migraciones nuevas
uv run uvicorn factumov.main:app --reload --port 8000

# terminal 3 — el frontend
cd E:\Capacitacion\InSoft\FactuMovrontend
npm run dev
```

**Al backend no se le pasa `--host`, y no es un olvido.** El celular nunca le pega al 8000: le
pega a Vite, y Vite reenvía `/api` a `127.0.0.1:8000` desde la misma máquina (ver *El proxy de
Vite en vez de CORS*). Exponer uvicorn en la LAN abriría un puerto que nadie usa.

El que sí escucha en todas las interfaces es Vite, por el `host: true` de `vite.config.ts`.
Al arrancar imprime la URL *Network*; desde el celular, en la misma Wi-Fi, hay que abrir **esa**
y aceptar la advertencia del certificado autofirmado:

```
https://192.168.1.37:5173      # ejemplo — la IP la da el router y puede cambiar
```

Conviene leer siempre la línea *Network* que imprime Vite en vez de fiarse de la IP anotada
acá: la asigna el DHCP del router y cambia sola.

**Con `https://`, no con `http://`.** Por http la cookie de sesión no se guarda y todo contesta
401 — ver el punto siguiente, que es el error más caro de esta pantalla.

### Lo que falta si el celular no engancha
- **El firewall de Windows.** Vite escucha, pero el perfil de red (Privado, en la máquina de
  Miguel) bloquea la conexión entrante si nadie la permitió. Normalmente Windows lo pregunta con
  un cartel la primera vez que node abre el puerto y alcanza con darle *Permitir* en redes
  privadas. Si el cartel no aparece, la regla se crea una vez, en PowerShell **como
  administrador**:
  ```powershell
  New-NetFirewallRule -DisplayName "Vite dev 5173" -Direction Inbound -Protocol TCP `
    -LocalPort 5173 -Profile Private -Action Allow
  ```
- **`APP_BASE_URL`, solo para probar el registro.** Ver el detalle al final de *HTTPS en
  desarrollo*.

## HTTPS en desarrollo, y por qué no es opcional
El dev server usa `@vitejs/plugin-basic-ssl`, que genera un certificado autofirmado solo, y
escucha en todas las interfaces (`host: true`).

**La cookie de sesión es `Secure`, y el navegador solo la guarda en un contexto seguro.**
`localhost` cuenta como seguro aunque sea http —por eso en la computadora anda sin
certificado—, pero `http://192.168.0.x:5173` **no**. Probando desde el celular por http la
cookie se setea, nunca vuelve, y todo contesta 401 por un motivo que no se parece en nada a
la causa. Es el mismo problema que resuelve el `base_url="https://testserver"` del TestClient
de la suite del backend, y conviene tenerlos juntos en la cabeza: son el mismo error con dos
disfraces.

La alternativa era hacer configurable el `secure=True` de la cookie y apagarlo en desarrollo.
Se descartó: sería un flag capaz de viajar a producción y dejar la sesión viajando en claro,
a cambio de ahorrarse una advertencia del navegador que se acepta una vez.

Verificado el 2026-08-26: login por `https://192.168.1.37:5173`, cookie guardada, y el
request siguiente autenticado.

**`APP_BASE_URL` va con `https://`, y eso no es un detalle.** De esa variable cuelga el link
de confirmación que sale en el mail, y el 5173 habla TLS. Con `http://localhost:5173` el
navegador manda una request en texto plano a un puerto que espera un handshake, el server
cierra sin contestar, y Chrome muestra **`ERR_EMPTY_RESPONSE`** — que no nombra la causa por
ningún lado y se lee como "la app está caída". Pasó el 2026-08-26: el mail llegó bien y el
link estaba muerto desde el repo, no desde la instalación. Por eso el default de
`EmailSettings` también es `https`.

Para probar el registro **desde el celular** hace falta además cambiar `localhost` por la IP
de LAN, porque el link se abre en el teléfono y ahí `localhost` es el teléfono.

## El proxy de Vite en vez de CORS
`/api` se reenvía a `127.0.0.1:8000` y se le saca el prefijo. El navegador ve **un solo
origen**, así que no hace falta CORS.

La alternativa era pegarle directo al 8000 y agregarle `CORSMiddleware` al backend, con
`allow_credentials=True` y una lista de orígenes. Es una superficie real: la cookie de sesión
es `httpOnly` justamente para que ningún JS la toque, y abrir CORS con credenciales es la
forma más común de aflojar esa decisión sin darse cuenta. En producción la SPA y la API van
detrás del mismo nginx, que es exactamente lo que el proxy imita — o sea que esto no es un
apaño de desarrollo, es la topología final.

Consecuencias: el cliente pega siempre a rutas relativas y **no hay ninguna variable de
entorno con la URL del backend**. Y el puerto es `strictPort: true`: `APP_BASE_URL` del
backend apunta al 5173, y si Vite se corriera al 5174 por estar ocupado el puerto, el link de
confirmación de los mails llegaría roto.

