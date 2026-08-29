# FactuMov — Frontend

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

La SPA: autenticación, identidades fiscales con verificación de delegación, clientes con carga
desde el padrón, y la **grilla de modelos con su editor e importación de PDF** — que cierra la
funcionalidad #1 de punta a punta. Vite 8 + React 19 + TypeScript 6, `react-router` como única
dependencia agregada al scaffold.


## Las pantallas sin sesión
Seis, todas fuera de `RequireAuth`: `/login`, `/registro`, `/confirmar-email`,
`/olvide-password`, `/restablecer-password` y `/delegacion-aceptada`. Las cuatro últimas
aterrizan un link de mail o disparan uno, y **sus paths los fija el backend**
(`_CONFIRMATION_PATH`, `_PASSWORD_RESET_PATH`, `_REGISTER_PATH` y `_DELEGATION_ACCEPTED_PATH` de
`notifications.py`): cambiarles el nombre acá sin cambiarlo allá deja apuntando a la nada los
mails ya enviados.

`/delegacion-aceptada` es **la única pantalla de la app que no le habla a un usuario**: la abre
el operador desde el mail que le pide aceptar una designación en ARCA, y le contesta si con eso
alcanzó. Va sin sesión porque la identidad fiscal que mira no es suya y nunca podría serlo — lo
autoriza el token del link. Pregunta sola al montar, como `ConfirmEmailPage`, y deja un botón
para volver a preguntar: el "todavía no" es el caso normal, y quien lo recibe suele tener que
completar un paso en ARCA y reintentar. Ver *El link del mail al operador* en `docs/arca.md`.

## Sesión
- **No se guarda nada del lado del cliente.** La cookie es `httpOnly`, así que el JS no la
  puede leer; la única forma de saber si hay sesión es un `GET /auth/me` al montar el
  `AuthProvider`. Un flag en `localStorage` sería más rápido y mentiría en los dos casos que
  importan: la sesión revocada desde otra pestaña y la vencida.
- **`user` tiene tres estados, no dos:** `undefined` es "todavía no sé", `null` es "no hay
  sesión". Sin esa distinción, recargar en `/clientes` rebota al login antes de que conteste
  `/auth/me`, y el usuario logueado se ve pateado afuera en cada refresh.
- **`credentials: 'include'` en el cliente.** Sin eso el navegador no manda la cookie y
  *todo* contesta 401 — una falla que no se parece en nada a su causa.
- **`RequireAuth` no es seguridad, es navegación.** Quien quiera los datos le pega a la API
  igual; ahí decide `get_current_user`. Se aplica al grupo de rutas y no pantalla por
  pantalla, mismo criterio que el `APIRouter(dependencies=[...])` del backend: la regla
  escrita una vez no se puede olvidar en la pantalla que se agregue mañana.

## Mobile-first
El estilo base es el de pantalla angosta; `@media (min-width: 700px)` agrega lo de escritorio.
El corte está elegido por el contenido —el ancho a partir del cual dos campos conviven en un
renglón sin apretarse— y no por el tamaño de ningún dispositivo.

- **Ya no hay tablas.** Las tres pantallas de listado son la grilla de tarjetas — ver *La
  grilla de tarjetas*. Hasta el 2026-08-26 eran `<table>` que en angosto se volvían tarjetas con
  `data-label` en el `<td>` y el `<thead>` escondido con `clip-path` (no con `display: none`,
  que se lo esconde también al lector de pantalla y deja a las celdas sin nombre). El truco
  seguía siendo bueno; lo que dejó de haber es una tabla que pintar, así que el CSS se borró en
  vez de quedar decorando el archivo. **Queda anotado acá por si vuelve a hacer falta** — el día
  que aparezca una pantalla que sea de verdad tabular, como el listado de facturas emitidas.
- **Los inputs van a 16 px como mínimo.** Safari en iOS hace zoom automático al enfocar un
  campo con tipografía más chica y después no vuelve solo: el usuario queda con la página
  agrandada y la despincha a mano. No es estética.
- **Objetivo táctil de 44 px** (`--touch`) en botones, campos y pestañas. Es el piso común de
  las guías de Apple y de Material.
- **Los botones ocupan el ancho en angosto** y vuelven a su tamaño natural en ancho. En un
  celular el botón es el objetivo más grande que se puede dar, y evita el "apreté al lado".
- **La barra superior es `sticky`** y la navegación baja a su propio renglón, a lo ancho: en
  el celular la lista es larga y volver arriba para cambiar de sección es la mitad de la
  navegación. La dirección de mail aparece recién cuando hay lugar.
- **`overflow-x: hidden` en el `body`.** Sin eso, cualquier cosa ancha estira la página y todo
  se va de costado.

## La grilla de tarjetas (2026-08-26)
**Las tres pantallas de listado tienen la misma forma**: una tarjeta por elemento con el nombre,
una vacía con un `+` al final, se entra tocando y se elimina manteniendo apretado. Vale para
modelos (`/`), identidades fiscales (`/identidades`) y clientes (`/clientes`). Confirmado por
Miguel el 2026-08-26: la grilla de modelos es la forma que pidió, y pidió explícitamente que las
otras dos se comportaran igual.

Cada elemento tiene su pantalla: `/modelos/:id`, `/identidades/:id`, `/clientes/:id`; y el `+`
lleva a `/modelos/nuevo`, `/identidades/nueva`, `/clientes/nuevo`.

- **El markup y los gestos viven en `components/TileGrid.tsx`, una sola vez.** No es un patrón
  visual que se pueda copiar y pegar: adentro tiene el estado de cuál tarjeta está armada, el
  gesto y las tres precauciones de `useLongPress`. Copiado tres veces, la próxima corrección del
  gesto arregla una pantalla y deja dos rotas — y el síntoma sería "en clientes el borrar se
  comporta raro", que nadie va a atribuir a un `onClickCapture` que falta.
- **Identidades y clientes dejaron de ser una tabla con el formulario de alta arriba.** Esa
  forma no estaba mal en la computadora, pero en 360 px una tabla de cinco columnas es una pila
  de tarjetas improvisadas con dos íconos de 44 px apretados al final de cada una — y el celular
  es el caso principal. De paso desaparece la pregunta de "en esta pantalla cuál era el gesto".
- **La raíz sigue siendo la grilla de modelos y no las identidades fiscales.** Identidades y
  clientes son configuración: se tocan al empezar y después casi nunca. Dejar una de ellas de
  portada le cobra un toque a la pantalla que se abre cien veces por semana.
- **La tarjeta muestra solo el nombre.** Lo que hace falta ahí es reconocer el elemento de un
  vistazo y llegar con un dedo; el CUIT, el cliente y los importes están adentro, que es donde
  se los mira. Una lista con cuatro columnas diría más y se leería peor.
- **La única excepción es "Sin verificar" en la identidad fiscal**, y está acotada a ese caso a
  propósito: una identidad sin delegación verificada **no puede emitir**, así que sin el aviso el
  usuario tendría que entrar tarjeta por tarjeta a buscar cuál lo está frenando. Aparece solo
  cuando falta, o sea que el estado normal sigue siendo una grilla de nombres. La regla que fija
  el `warning` de `TileItem` es esa: un estado que bloquea, no un dato más que mostrar.
- **Y ese aviso se refresca contra ARCA al abrir la grilla** (2026-08-29). Antes salía de la
  columna guardada y nada más, así que decía la verdad recién después de entrar a la identidad:
  una que ya estaba habilitada seguía marcada como sin verificar hasta que alguien la abriera.
  Era la única pantalla donde el dato tenía que estar fresco —existe justamente para no entrar
  tarjeta por tarjeta— y la única que no lo refrescaba. El criterio y los frenos son los mismos
  que usa la pantalla de detalle y viven en `api/delegation.ts`; el porqué de cada uno, en
  *El rechequeo, en tres lugares* de [`arca.md`](arca.md).
- **Se fue `DeleteButton` con las tablas.** El tacho de dos pasos ("¿Eliminar? Sí / No") existía
  para las filas; en la grilla, sostener el dedo medio segundo ya *es* el paso deliberado, y lo
  que hace falta después es un objetivo grande y sin ambigüedad. Lo que se conserva de él es la
  decisión que importaba: nada de `window.confirm` —bloquea el hilo, no se puede estilar, y en
  algunos navegadores queda suprimido si el usuario marcó "no mostrar más", o sea que la
  confirmación desaparece sin que nadie se entere—, y el error del 409 se muestra **adentro de
  la tarjeta**, porque "tiene modelos asociados" es sobre ese elemento y mostrarlo arriba obliga
  a adivinar cuál se quejó.
- **Se entra tocando y se borra manteniendo apretado.** Que eliminar quede detrás de un gesto
  y no de un tacho siempre visible es a propósito: en una grilla de objetivos de 150 px, un
  ícono de borrar pegado al área que se toca cien veces por semana se aprieta solo. La tarjeta
  armada muestra dos botones con su nombre escrito —"Eliminar" y "Cancelar"— y no el tacho de
  dos pasos de las listas: sostener el dedo medio segundo ya fue el paso deliberado, y lo que
  falta es un objetivo grande.
- **El gesto no puede ser la única puerta.** Sostener el dedo es invisible con un mouse y no
  existe con un teclado, así que `useLongPress` engancha además `contextmenu`, que es el mismo
  evento para el botón derecho, la tecla Menú y Shift+F10. Una sola acción, tres entradas.
- **`useLongPress` usa eventos de puntero**, no `touchstart`/`mousedown`: cubre dedo, mouse y
  lápiz con un juego de handlers y evita que un toque dispare las dos ramas (los navegadores
  emiten eventos de mouse sintéticos después de un toque). Tres detalles que costaron pensarlos
  y sin los cuales el gesto se siente roto: una tolerancia de 10 px para que arrastrar la lista
  no abra el menú de la tarjeta de abajo; un `onClickCapture` que se come el `click` que el
  navegador manda igual al soltar —si no, mantener apretado abre el menú **y** entra a la
  tarjeta—; y `user-select: none` + `-webkit-touch-callout: none` en el CSS, porque si no iOS
  abre su menú de copiar justo encima del gesto.
- **La identidad fiscal y el cliente son un `PickerField`, no un `<select>`.** Tocar abre la
  lista; mantener apretado entra a editar el elegido. El `<select>` nativo abre el picker del
  sistema —que en el celular está muy bien— pero no deja colgarle un gesto propio ni mostrar
  dos renglones por opción, y el CUIT abajo del nombre es lo que distingue dos clientes que se
  llaman parecido.
- **El id a editar viaja en el path** (`/identidades/<id>`), no en un estado compartido. Es lo
  que hace que el gesto sea un link común: sin eso haría falta un canal aparte para decirle a la
  pantalla de identidades con qué fila arrancar. Fue `?editar=<id>` sobre la lista mientras la
  edición era un formulario arriba de una tabla; con una pantalla por elemento el path dice lo
  mismo sin que haya que explicar la URL. El alta y la edición comparten componente, con un `key`
  que lo remonta al cambiar de id — copiar la prop al estado con un efecto es el mismo resultado
  con un render de más y una forma conocida de pisar lo que el usuario ya tipeó.
- **El alta vuelve a la grilla; la edición se queda y dice "Guardado".** La tarjeta nueva en la
  grilla es la confirmación de que se creó, y es además donde el usuario iba a ir igual. En la
  edición no hay tarjeta nueva que mirar, así que hace falta decirlo — y el cartel se apaga al
  primer cambio, que es la forma más barata de que nadie salga creyendo que guardó lo que acaba
  de tipear.
- **El formulario es controlado desde afuera.** Que el editor se guarde el estado adentro no
  serviría para la pantalla de importación, que después de dar de alta un cliente tiene que
  meterle el id al formulario que el usuario ya empezó a tocar.
- **`forms/templateForm.ts` está separado de `TemplateEditor.tsx` por Fast Refresh**, que solo
  recarga en caliente un módulo que exporta componentes y nada más — el mismo motivo por el que
  el contexto de sesión vive en tres archivos.
- **Los importes se tipean con coma o con punto.** `parseAmount` acepta `1.234,56` y `1234.56`;
  sin eso el que escribe como se escribe acá manda `NaN`. Y viajan como **string** al backend,
  no como `number`: `Decimal` se serializa con su escala, y pasar por el binario de coma
  flotante en el camino de ida es pedirle centavos al azar.
- **El total de la pantalla aplica la convención del proyecto**: en A el precio va neto y en B
  y C ya viene con el IVA adentro. No es una regla nueva, es la misma que usa el parser al leer
  un PDF. La letra que decide cuál de las dos aplica es la **deducida** —ver *La letra del
  comprobante se deduce*—, así que el total se recalcula solo al cambiar de cliente. Mientras
  falte elegir emisor o cliente no hay letra y se asume IVA incluido, que es lo que vale en tres
  de las cuatro combinaciones. Está escrito abajo del total que es una cuenta nuestra y que el
  importe que vale es el que autorice ARCA.
- **La importación resuelve las dos partes que le faltan contra el padrón, sola y sin salir de
  la pantalla.** El draft trae al emisor y al receptor por CUIT pero sin id cuando no están
  cargados, y el editor pide ids: sin una salida ahí, importar la factura de un cliente nuevo es
  un callejón. Las dos tarjetas viven en `components/MissingParty.tsx` y **consultan ARCA al
  montarse**, sin botón "Buscar": hacerle apretar un botón al usuario para averiguar algo que la
  app puede averiguar sola es ponerlo de intermediario. Lo que difiere es qué se hace con la
  respuesta —el cliente se da de alta solo y se avisa; la identidad fiscal espera un toque— y el
  porqué de esa asimetría está en el archivo. Sigue valiendo que `/import` no escribe nada: el
  alta es un `POST` aparte que manda el cliente.
- **"Empezar en blanco" no es un extra.** Hay un segundo layout de factura que el parser
  todavía no sabe leer, y un PDF escaneado contesta 200 con el modelo vacío a propósito. Con
  una sola puerta, cualquiera de esos dos casos queda sin salida.
- **La palabra de la UI es "modelo".** Miguel dice indistintamente "modelo" y "plantilla"; se
  eligió "modelo" porque es lo que ya dicen los mensajes de error del backend ("Modelo no
  encontrado", "No se puede eliminar un cliente con modelos asociados") y tener la pantalla
  diciendo una cosa y el error otra es peor que cualquiera de las dos.

## La luz de las tarjetas (2026-08-28)
**Las tarjetas de la grilla dejaron de ser rectángulos planos.** En reposo están *levantadas*, y
al tocarlas *flotan*. Salió de un pedido de Miguel con una captura del instalador de Chrome: ese
panel blanco con manchas de color difusas apoyadas en las esquinas de abajo. Se le mostraron seis
variantes en el navegador antes de elegir; la elegida es la aurora con el verde de InSoft en
reposo, cambiando al halo desenfocado al tocar.

Todo vive en `index.css`, en dos pseudo-elementos de `.tile`. **No hay una sola línea de JS**, así
que `TileGrid.tsx` no se enteró del cambio y el gesto de mantener apretado siguió igual.

- **En reposo, dos cosas distintas que se confunden fácil.** La *aurora* (`::after`, tres
  `radial-gradient` apoyados en el borde de abajo) pone color; el *relieve* —la línea blanca
  `inset` arriba y la sombra proyectada del `box-shadow`— pone volumen. Probadas por separado,
  la aurora sola sigue leyéndose plana: la sensación de "levantada" la da la sombra, no el color.
- **Al tocar, la aurora se apaga y el halo se prende. No se suman.** Las dos luces al mismo
  tiempo se leen como una tarjeta sucia, no como una tarjeta encendida. Es un cambio de estado.
- **El halo va casi opaco (`alpha` cerca de 1) porque el `blur(17px)` lo diluye.** Al 40 % de
  alfa —que es lo que se ve razonable escrito— después del desenfoque no queda nada, y el efecto
  se lee como si la tarjeta *se apagara* al tocarla, que es lo contrario de lo que se busca.
- **`isolation: isolate` en `.tiles` no es decorativo.** El halo se pinta en `z-index: -1`, o sea
  detrás del fondo de su propia tarjeta. Sin un contexto de apilado que le ponga piso, ese `-1`
  lo manda detrás del fondo de la página y no se ve nada — que es exactamente lo que pasó en el
  primer intento.
- **La aurora se recorta con `border-radius: inherit`, no con `overflow: hidden`.** El
  `overflow` sería lo obvio, pero recorta también el halo, que justamente tiene que asomar por
  fuera de la tarjeta.
- **`:hover` va detrás de `@media (hover: hover)` y `:active` va suelto.** En una pantalla táctil
  el navegador simula un hover que **queda pegado** después de tocar, hasta que se toca otra
  cosa: sin la media query, volver a la grilla desde un modelo dejaría una tarjeta iluminada sin
  que nadie la esté tocando. `:active` es lo que efectivamente llega en el celular —el dedo
  apoyado—, y es el que hace que el efecto exista en el caso principal.
- **La tarjeta armada para borrar se queda sin luz y sin relieve** (`.tile.armed::before/::after
  { content: none }`). Ahí el color tiene que significar "peligro"; una tarjeta roja con un halo
  verde asomando por abajo dice las dos cosas a la vez.
- **Lo único que se mueve es el hundido de `:active`**, y se apaga con
  `prefers-reduced-motion`. El resto son transiciones de opacidad, que quedan igual.

## Cambiar de sección deslizando el dedo (2026-08-28)
**En el celular se pasa de una sección a otra deslizando horizontalmente**, en el orden de la
barra: Modelos → Facturas → Identidades → Clientes. Pedido de Miguel. Vive en
`hooks/useSwipeNav.ts` y se cuelga una sola vez, del contenedor del `<Outlet />` en `AppLayout`,
que es el único lugar por el que pasan las cuatro pantallas.

- **Solo con el dedo** (`pointerType === 'touch'`). Con un mouse, arrastrar sobre la página es
  seleccionar texto: el gesto rompería eso para resolver un problema que en una pantalla grande
  no existe, porque ahí las pestañas están siempre a la vista y a un click.
- **Es un atajo y no la única puerta.** La barra sigue arriba, visible y sticky. Es la misma
  regla que el `contextmenu` del "mantener apretado": un gesto invisible no puede ser el único
  camino a nada, porque el que no lo descubre se queda sin la función. Y de paso la barra es lo
  que dice en qué sección estás, que el gesto por sí solo no cuenta.
- **Los filtros del gesto son dos, no tres.** 60 px de recorrido y el trazo 1,5 veces más
  horizontal que vertical. El segundo es el que más trabaja: nadie desplaza una lista en una
  recta vertical perfecta, y sin esa proporción un scroll en diagonal cambia de sección a mitad
  de camino.
- **Había un tercero —700 ms de techo— y hubo que sacarlo.** Estaba para separar el swipe del
  "mantener apretado", pero medía el gesto **entero**, desde que el dedo se apoya. El síntoma que
  reportó Miguel fue exacto: *"si funciona, pero hay que hacerlo muy rápido; si apoyo y deslizo
  no se mueve"* — apoyar el dedo y recién después arrancar ya se comía el presupuesto. Y la
  separación con el long press nunca la dio el reloj sino la distancia: `useLongPress` se cancela
  solo a los 10 px de movimiento y acá recién a los 60 px hay swipe, así que el techo no estaba
  distinguiendo nada. Era un límite de velocidad para un gesto que la gente hace despacio.
- **`touch-action: pan-y` en el contenedor, o el gesto directamente no existe.** El navegador
  decide en los primeros píxeles si el desplazamiento es suyo, y con el `auto` de fábrica
  cualquier componente vertical del trazo le alcanza para quedarse con el puntero: dispara
  `pointercancel` y el `pointerup` que mide el swipe no llega nunca. `pan-y` reparte los ejes —el
  vertical sigue siendo del navegador y la lista se desplaza igual—. Vale también para las
  tarjetas, que declaran `manipulation`: el valor que cuenta es la intersección de toda la
  cadena, y `manipulation ∩ pan-y` es `pan-y`.
- **`.app-main` lleva `min-height`.** Con dos o tres tarjetas el contenido ocupa un cuarto de la
  pantalla y el resto es fondo: sin altura mínima, deslizar en la mitad de abajo no toca el
  elemento que escucha, justo en las pantallas más vacías que son las que más se recorren.
- **`pointercancel` no es un caso de borde: es el caso normal.** En cuanto el navegador decide
  que el gesto era un desplazamiento vertical, se queda con el puntero y el `pointerup` no llega
  nunca. Sin limpiar el origen ahí, el próximo toque en cualquier lado se mide contra un punto
  de partida viejo y dispara un swipe fantasma.
- **Un swipe que arranca arriba de una tarjeta terminaba entrando a la tarjeta.** Al soltar, el
  navegador manda igual el `click`. Se corta con un `onClickCapture` en el contenedor —captura,
  así baja antes de llegar al `onClick` de la tarjeta—, que es exactamente lo que ya hacía
  `useLongPress` para su propio caso.
- **El gesto no hace nada fuera de las cuatro grillas.** Adentro de un modelo, de un cliente o
  de la pantalla de emitir hay formularios a medio llenar, y salirse de uno con un dedo mal
  apoyado pierde lo escrito. Se resuelve solo: `paths.indexOf(pathname)` da -1 y no hay a dónde ir.
- **Sin vuelta al principio.** Desde Clientes, seguir deslizando no hace nada. Con `wrap`, un
  swipe de más te manda al otro extremo de la app y el borde deja de sentirse como un borde —
  que es lo mismo que decidieron las pestañas de Android.
- **La animación es un 6 % y no una pantalla entera.** Lo segundo pide las dos rutas montadas a
  la vez, o sea un carrusel de verdad; con una sola, un `translateX(100%)` deja medio segundo de
  página en blanco. El 6 % con el fundido alcanza para decir de qué lado vino.
- **El `key` del contenedor lleva un `nonce` y no el `pathname`.** Con el pathname, el
  contenedor se remontaría también en las navegaciones que salen de las pestañas, que no tienen
  por qué animar; y dos swipes seguidos en la misma dirección no volverían a animar, porque la
  clase no cambia y sin remontar la animación no se repite.

**Probado en el celular el 2026-08-28**, y de ahí salieron las dos correcciones de arriba: el
`touch-action` y el techo de tiempo. Ninguna de las dos se ve con un mouse ni con el emulador —
la primera porque el navegador de escritorio no compite por el puntero, la segunda porque con un
mouse el gesto sale siempre rápido. Es el ejemplo de por qué un gesto táctil no se da por
terminado hasta tocarlo con un dedo.

## El PDF que llega de la nube (2026-08-26)
Importar una factura elegida **desde Google Drive** en el selector de Android fallaba con «No se
pudo conectar con el servidor», que es el mensaje de `ApiError(0, …)` — el que el cliente HTTP
usa cuando `fetch` **rechaza**, o sea cuando no hubo respuesta: backend apagado, DNS, red
cortada. Nada de eso pasaba: la sesión andaba y el resto de las pantallas cargaban.

**Un `File` recién elegido no es memoria, es un puntero.** El navegador lo resuelve recién
cuando alguien lee sus bytes, y con un proveedor de la nube esa lectura sale a buscar el archivo
a Drive. Si falla —o si el proveedor entrega un archivo vacío— y el `File` se le pasó directo al
`fetch`, la falla revienta **adentro del `fetch`**, que rechaza igual que si el server no
estuviera. De ahí el mensaje: era verdadero sobre el `fetch` y falso sobre el mundo, y mandaba a
Miguel a mirar la red cuando el problema era el archivo.

Entonces `api.upload` pasó a recibir un `Blob` ya leído más el nombre, y la pantalla lee los
bytes con `file.arrayBuffer()` antes de armar el request. Con eso el error aparece donde ocurre y
con el texto que corresponde: «bajalo al teléfono primero y volvé a intentar», que es la acción
que lo resuelve. Un archivo de largo cero cae en la misma rama, porque para el usuario es el
mismo problema.

Dos detalles que van con esto:

- **El `<input type=file>` se limpia en el `finally`, no antes de subir.** Se limpia porque sin
  eso elegir el mismo archivo dos veces seguidas no dispara `change` y el botón parece roto; pero
  hacerlo antes de leer los bytes es soltar la referencia al archivo que todavía falta leer, que
  es una segunda forma de llegar al mismo bug.
- **No convierte a `ApiError` un problema local.** El 415 por magic bytes y el 200 con draft
  vacío siguen siendo del backend y siguen significando lo que significaban; esto es una tercera
  cosa —el archivo no se pudo leer— y se contesta antes de salir a la red.

## Dictado por voz: las fechas y el comando de emitir (2026-08-28)
Un micrófono al lado de cada campo de fecha de `/modelos/:id/emitir`, y un botón "Emitir por
voz" arriba de la grilla de modelos que entiende **"emitir alquiler mensual desde el 1 de
agosto hasta el 31, vence el 10 de septiembre"** y, más corto, **"emitir alquiler de agosto"**.
La app escucha y **contesta hablando**.
Son cinco archivos: `hooks/useSpeechInput.ts` (abrir el micrófono), `speech.ts` (de lo que se
escuchó a una fecha), `commands.ts` (de lo que se escuchó a un comando), `speak.ts` (la voz de
vuelta) y los tres componentes, `DictateDate`, `DictateCommand` y `SpeakToggle`.

**Nació como spike y el spike cerró el mismo día**: existía para averiguar si el
reconocimiento de voz del navegador anda en el celular —y sobre todo en iOS con la app
instalada desde la pantalla de inicio, que es el caso principal— antes de construirle nada
encima. Anda en iPad, en Android y en la computadora, así que el comando hablado, que era el
paso siguiente, se construyó encima. Con eso se fue también la traza de eventos que mostraba
la pantalla mientras duró la prueba (`.mic-trace`): era una herramienta para diagnosticar
desde un iPad sin consola, no algo que va abajo del botón de emitir una factura.

- **Web Speech API y no un servicio de transcripción propio.** La alternativa era grabar con
  `MediaRecorder`, subir el audio y transcribirlo en el backend: anda parejo en todos lados,
  pero cuesta por minuto, agrega un endpoint y suma latencia. El API del navegador es gratis,
  no toca el servidor y ya está instalado; lo que se paga es que el soporte no es parejo, y
  eso es lo que el spike midió. **El audio sale del dispositivo** —lo transcriben los
  servidores de Google y de Apple—, igual que dictándole al teclado del sistema, pero conviene
  tenerlo escrito antes de que alguien dicte el nombre de un cliente.
- **Una gramática cerrada y no un LLM.** El vocabulario entra en un archivo: "hoy", "ayer",
  "el 15", "quince de agosto", "fin de mes", "15/8/26", más los verbos y las cuatro palabras
  que abren una cláusula de fecha. Un modelo entendería que le hablen suelto, pero cuesta por
  request, agrega un segundo y puede devolver una fecha —o un modelo— que nadie dijo, sobre un
  comprobante fiscal.
- **Ni el micrófono ni el comando emiten.** Emitir le pide el CAE a ARCA y no se puede
  deshacer, así que lo que la voz hace es dejar el formulario listo con lo que entendió escrito
  en pantalla; el botón lo aprieta el dedo. El comando ahorra la parte reversible del camino
  —encontrar la tarjeta entre veinte, entrar, tocar "Emitir" y cargar tres fechas en el
  selector nativo del celular— y termina en la misma pantalla de confirmación de siempre, que
  muestra letra, destinatario e importe. Con eso, entender mal es una molestia y no una factura
  equivocada. De ahí también el `type="button"` de los micrófonos: el default de un `<button>`
  adentro de un `<form>` es `submit`, y ese `submit` emite.
- **Las fechas dictadas viajan en la query, no en el estado del router**
  (`?fecha=&desde=&hasta=&vence=`). El estado de `navigate` se pierde al recargar y la pantalla
  volvería a los defaults sin decir nada; en la URL sobreviven y se pueden corregir a mano. La
  pantalla de emisión valida la **forma** de lo que le llega —que el día exista ya lo verificó
  `parseSpokenDate`, y el rango lo verifica el backend— y **avisa que esas fechas las puso el
  dictado**: con hoy puesto por default se ve igual que con una fecha entendida de una frase, y
  son dos cosas distintas.
- **No entender es una respuesta, y se muestra.** `parseSpokenDate` devuelve `undefined` y el
  campo dice qué se escuchó y que no salió una fecha; el comando distingue cuatro finales —no
  es un comando, no hay un modelo con ese nombre, hay más de uno, y no se entendió la fecha de
  tal palabra— porque los cuatro se arreglan distinto. El peor final posible es que el botón no
  haga nada visible: el usuario no sabe si el micrófono no escuchó, si entendió otra cosa o si
  la app se colgó. Por el mismo motivo los códigos de error del navegador se traducen uno por
  uno — "no se escuchó nada" se arregla hablando de nuevo y "no diste permiso" se arregla en la
  configuración.
- **Empatar no es elegir.** Si lo que se dijo coincide con dos modelos se muestran los dos y el
  usuario repite con el nombre completo. Adivinar llevaría a la pantalla de confirmación del
  modelo equivocado, con el nombre correcto de otro cliente escrito arriba del botón. Por lo
  mismo el buscador tiene tres pasadas separadas —nombre exacto, nombre contenido, y todas las
  palabras en cualquier orden— y gana la primera que encuentre algo: así "alquiler" encuentra a
  "Alquiler" aunque exista también "Alquiler cochera".
- **Un modelo y un mes es la frase entera** (2026-08-28). "Emitir alquiler de agosto" deja
  cargadas las cuatro fechas: el comprobante fechado el **1**, el período del **1 al último
  día** del mes y el pago venciendo el **10**. Es como se pide de verdad una factura de
  servicios —un abono se factura por mes entero, nadie dicta tres fechas para decir "agosto"— y
  es justo el trabajo que el comando venía a sacar. El día 10 es una convención y no una
  cuenta, y por eso se elige en el cliente (`monthDates`) y no en el backend: es lo que el
  dictado *propone*, queda escrito en la pantalla de confirmación y se corrige con el selector
  el mes que venza otro día.
  - **El mes solo se aplica si el modelo lleva período**, o sea si su `concepto` no es solo
    productos — el mismo criterio que `needs_service_dates` en el backend. En un modelo de
    productos el comando **no navega**: contesta que está cargado como productos y que no lleva
    período. Ignorar el mes y seguir sería peor, porque esa pantalla no tiene dónde mostrarlo y
    no habría nada raro que ver antes de apretar el botón. Por eso la grilla le pasa al comando
    el `concepto` además del nombre, y por eso `matchTemplate` devuelve el modelo entero y no
    su `id`.
  - **El mes se corta del nombre antes de buscar el modelo**, o "alquiler de agosto" no
    encontraría a "Alquiler". Y se reconoce solo como **cola** de la frase, con un espacio
    delante obligatorio: sin eso, un modelo llamado "Enero" o "Agosto" dejaría de poder
    nombrarse. Así "emitir enero" sigue siendo el modelo Enero y "emitir cuota de enero" es la
    cuota de ese mes.
  - **O un mes, o fechas sueltas, pero no las dos en la misma frase.** Si se dijo alguna
    cláusula de fecha el mes se descarta: combinarlos daría un período mitad mes entero y mitad
    dictado —o dado vuelta, si el día que se dictó cae en otro mes—, que no es lo que dijo
    ninguna de las dos partes.
  - El año casi nunca se dice y sale del mismo criterio que el resto: el que deja el mes más
    cerca de hoy. Fechar el comprobante el día 1 puede caer fuera de la ventana de ARCA si el
    mes que se dictó pasó hace rato (±10 días para servicios); **no se recorta**, porque la
    pantalla muestra la ventana y el backend contesta un 422 con el límite escrito, y eso es
    mejor que emitir en silencio con una fecha que no es la que se pidió.
- **El período se lee junto: la punta que no nombra el mes lo toma de la otra.** "Desde el 1
  hasta el 31 de agosto" es como se habla, y cada punta resuelta por su cuenta no puede acertar
  — `parseSpokenDate` no ve más que "el 1" y le pone el mes más cercano a hoy, que el 28 de
  agosto es septiembre: el período saldría del 1 de septiembre al 31 de agosto, al revés y sin
  que nada lo dijera. Corre solo sobre `desde`/`hasta`, que son las únicas dos fechas que forman
  un par: "vence el 10" dicho el 28 de agosto es el 10 de septiembre aunque el período facturado
  sea agosto. Y si ninguna de las dos nombró el mes y el período igual queda invertido, **las
  dos vuelven a "no se entendió"**: un período dado vuelta que la app corrige sola es una
  factura de servicios declarada con otro período, y eso lo lee ARCA.
- **El vocabulario de las cláusulas es corto a propósito.** Cada palabra que abre una cláusula
  es una palabra que deja de poder estar en el nombre de un modelo, porque corta la frase. Por
  eso están "fecha", "desde", "hasta" y "vence" y no está "al", que aparece en "Servicio al
  cliente" — aunque "del 1 al 31" sea como se habla.
- **La última vez que se dijo una fecha gana.** Repetir una palabra clave es como se corrige
  hablando: "desde el 1, no, desde el 2".
- **`parseSpokenDate` y `parseSpokenCommand` son puros y reciben `today` por parámetro.** El
  micrófono solo se puede probar hablándole a un celular; si la interpretación viviera adentro
  del componente, también habría que hablarle al celular para saber si "treinta y uno de agosto"
  cae en el día correcto. Separadas, lo único que se prueba a mano es que el micrófono abra. El
  `today` inyectado es lo que hace que "ayer" no dependa del día en que se corra la prueba.
- **Rechaza el 31 de febrero.** `new Date(2026, 1, 31)` no falla: devuelve el 3 de marzo en
  silencio. Sin la verificación, dictar una fecha imposible cargaría una plausible y equivocada,
  que es peor que no entender nada.
- **El año que no se dijo es el que deja la fecha más cerca de hoy.** Se nota una vez por año y
  es justo cuando importa: "31 de diciembre" dictado el 2 de enero es del año pasado. Mismo
  criterio sobre el mes cuando solo se dijo el día.
- **Los números hablados se pasan a dígitos antes de buscar la fecha**, porque los motores no
  coinciden: Chrome en Android devuelve "15 de agosto" y Safari en iOS "quince de agosto".
  Normalizando primero hay una sola forma de fecha que reconocer en vez de dos. La misma
  normalización parte la frase del comando, así que el nombre del modelo se compara con el mismo
  criterio con el que se leyó.
- **El reloj que cierra el micrófono mide silencio, no duración total.** Safari en iPad abre el
  micrófono y no lo cierra nunca (visto el 2026-08-28 en producción), así que hay dos relojes: a
  los 8 segundos **sin resultados** se pide `stop()` —finalizar y entregar— y a los 30 absolutos
  se corta con `abort()`. El primero se rearma con cada parcial: era un plazo fijo desde el
  arranque mientras esto dictaba una fecha, pero un comando entero no entra en nueve segundos y
  el plazo fijo cortaba al usuario en la mitad de la frase. El segundo no se rearma nunca,
  porque es justamente la red contra el caso en que el motor no emite nada.
- **`stop()` y no `abort()` cuando el usuario dice que terminó.** En iOS el motor no entrega
  nada hasta que se le pide finalizar, así que `abort` garantizaba el síntoma reportado:
  micrófono abierto, cuadrado apretado, nada capturado.
- **La app contesta hablando lo que entendió** (`speak.ts`, `SpeakToggle`), además de
  escribirlo. Es la otra mitad del dictado: el que le habla al celular para no tipear tampoco
  quiere tener que leer la respuesta — con el teléfono en el bolsillo, manejando, o con el
  papel en la otra mano. Lo escrito no se va: es lo que queda para revisar antes de emitir, y
  es lo que el oído no puede releer. La voz lee el comprobante entero cuando la pantalla de
  emisión tiene qué mostrar, los cuatro finales que no salieron, y los errores del micrófono
  — "no se escuchó nada" es justo el caso en que el usuario está esperando algo que no va a
  llegar. `speechSynthesis` es el mismo Web Speech API
  del otro lado, y al revés que el reconocimiento **no sale del dispositivo**: la voz la
  sintetiza el sistema.
  - **Las fechas se dicen en palabras** ("15 de agosto"), y con el año solo cuando no es el
    corriente. `formatDate` no sirve para el oído: "15/08/2026" se lee "quince barra cero ocho
    barra dos mil veintiséis", que es lo último que uno quiere escuchar cuando lo que está
    confirmando es una fecha. Y el año, que casi siempre es el corriente, alargaría todas las
    respuestas para el caso raro — pero cuando cambia se dice, porque es cuando el dictado pudo
    haber entendido otra cosa.
  - **Se puede apagar, y se recuerda.** Contestar hablando es lo que uno quiere cuando dicta y
    lo último que quiere en una oficina con gente al lado, y son la misma persona en dos
    momentos del día. Prendido por default porque esto contesta **a un dictado**: el que apretó
    el micrófono ya habló en voz alta. El interruptor es uno solo y global, al lado del
    micrófono del comando y otra vez en la pantalla de emisión, que es la que más habla;
    repetirlo junto a **cada campo** serían cuatro botones de silencio para una preferencia
    sola.
  - **`armSpeech()` corre en el toque del usuario, no en la respuesta.** Hace dos cosas que
    después no se pueden hacer: corta lo que la app estuviera diciendo —si no, lo primero que
    escucha el micrófono que se está abriendo es a la app terminando la frase anterior, y lo
    transcribe— y paga la entrada de iOS, que exige que el primer `speak()` de la página salga
    de un gesto. El nuestro sale de un callback del reconocedor, que no lo es.
  - **Las frases se pisan, no se encolan** (`cancel()` antes de cada una). Dictar tres veces
    seguidas tiene que contestar lo último que se entendió, no una fila de tres respuestas de
    las cuales las dos primeras ya no son ciertas.
  - **No se enumeran las voces del sistema.** `getVoices()` devuelve vacío hasta que el
    navegador las carga —de forma asincrónica, y en Chrome la primera vez llega tarde—, así que
    elegir una a mano sería esperar un evento o hablar en inglés la primera vez. Pidiendo
    `lang = 'es-AR'` la elige el sistema y siempre hay una.
  - **El `localStorage` va adentro de un `try`**: en Safari con navegación privada **tira** en
    vez de devolver `null`, y sin el `try` la grilla de modelos no renderiza.
- **La lectura completa ocurre en la pantalla de emisión, no en la grilla** (2026-08-28).
  Cuando el comando encuentra el modelo, la grilla **no dice nada**: navega. Lo que se lee en
  voz alta es el comprobante entero y recién cuando el `preview` llegó — "Factura B, punto de
  venta 1. Emite Fulano. A Mengano. Total 42350 pesos. Fecha 28 de agosto. Período desde el 1
  de agosto. Hasta el 31 de agosto. Vence el 10 de septiembre." Un resumen dicho desde la
  grilla solo puede repetir **lo que se dictó**, y lo que hay que revisar antes de pedir un CAE
  incluye todo lo que nadie dijo: la letra que dedujo el backend, el emisor, el cliente, el
  importe que se va a declarar y las fechas que la app puso sola. Y encima se pisarían: `say`
  cancela lo anterior, así que dos respuestas seguidas son una respuesta cortada al medio.
  - **Se lee una vez, al aparecer la pantalla**, y no se relee cuando se corrige una fecha —
    esa corrección ya tiene su propia respuesta, la del micrófono del campo. Releer siete
    líneas en cada retoque termina con el usuario apagando la voz, y con eso perdiendo la
    lectura, que es lo que vale. La guarda es una ref y no una lista de dependencias recortada:
    así el linter ve todo lo que el efecto usa y "una sola vez" queda escrito en el código en
    vez de deducido de lo que falta.
  - **Se lee siempre que la voz esté prendida, aunque se haya llegado tocando.** Es la
    confirmación de un acto irreversible: quién emite, a quién, por cuánto y con qué fechas. El
    interruptor es el que decide si la app habla, no el camino por el que se llegó.
  - **El importe se dice sin separadores** ("42350 pesos", y los centavos solo si los hay): el
    "$ 42.350,00" de `money` el sintetizador lo lee por pedazos y con los puntos adentro. Es lo
    mismo que pasa con las fechas y las barras — lo que se muestra y lo que se dice no son el
    mismo texto porque no entran por el mismo lado.
  - **El CUIT y el documento no se dicen.** Once dígitos de corrido no los verifica nadie de
    oído y alargan la lectura justo antes de lo único que hay que decidir. Quedan en la
    pantalla, que es donde se comparan.
  - **`blocked_reason` va al final**, que es donde está el botón: si no se puede emitir, eso es
    lo que hay que hacer y tiene que ser lo último que quede sonando. Los dos fracasos
    —no poder cargar el preview y no poder emitir— también se dicen, por el mismo motivo que
    los errores del micrófono.
  - **El interruptor de la voz está también en esta pantalla**, que es la que más habla: tiene
    que haber dónde callarla sin volver a la grilla. Es el mismo botón y la misma preferencia.
- **Sin banco de pruebas en el frontend.** Los casos de `parseSpokenDate` y de `commands.ts` se
  corren con `esbuild` + `node` desde el scratchpad (38 casos, todos en verde) en vez de sumar
  `vitest`: es la misma decisión que TanStack Query y Tailwind. Revisar cuando esta gramática
  vuelva a crecer — es la candidata más clara a necesitarlo.
- **Rugosidad conocida:** en pantalla ancha, "Período desde" y "Hasta" comparten un `.row` con
  `align-items: flex-end`, así que si se dicta en uno de los dos el mensaje de estado lo
  desalinea del otro mientras está visible. En el celular no pasa, porque van uno abajo del
  otro.

## El punto de venta se elige, no se escribe (2026-08-29)
El campo era un `<input>` libre con `1` de default. El punto de venta lo da de alta el usuario
en ARCA, así que el default acertaba solo por casualidad — y un default plausible es peor que
ninguno: hace que el campo parezca resuelto y nadie lo mire. Ahora el editor le pregunta a
ARCA cuáles tiene ese CUIT (ver *`GET /fiscal-identities/{id}/points-of-sale`*) y muestra un
desplegable.

- **`usePointsOfSale` y no `useResource`.** Ese hook es para un recurso fijo por pantalla y no
  resetea su estado al cambiar de identidad, lo dice su propio docstring; acá el recurso *es*
  la identidad elegida, que cambia con el selector de arriba del formulario.
- **La respuesta se guarda en un mapa por identidad y el estado se deriva en el render.** Sale
  gratis lo que de la otra forma hay que programar: una respuesta que llega tarde se guarda
  bajo *su* id y no puede pisar lo que el campo muestra —no hace falta cancelar nada— y no
  queda ningún `setState` sincrónico adentro de un efecto.
- **El caché vive con la pantalla.** Cada consulta sale a WSFE, tarda segundos y gasta cuota
  contra el certificado, que es uno solo para todos los usuarios. En un módulo duraría toda la
  sesión y un punto de venta recién dado de alta no aparecería nunca; en el hook, aparece
  volviendo a entrar al editor. Se recuerda también el fallo: reintentar por haber cambiado de
  campo sería martillar a ARCA.
- **Sin lista no se bloquea nada.** Los cinco estados sin desplegable —todavía no hay
  identidad elegida, está cargando, el CUIT no tiene ninguno, falta la delegación, ARCA no
  contestó— caen en el mismo input libre de antes. Lo único que cambia entre ellos es el texto
  de abajo, que es lo que distingue "andá a darlo de alta en ARCA" de "esperá y probá de
  nuevo".
- **Se completa solo cuando hay uno, y nunca pisa lo guardado.** Con un único punto de venta no
  hay nada que elegir; con varios, elegir por el usuario sería adivinar. Y un modelo guardado
  con el 5 lo conserva aunque hoy ARCA ofrezca otros: se agrega como opción del desplegable
  —si no, el `<select>` mostraría otro número sin que nadie lo haya cambiado— con un aviso de
  que no figura en ARCA.
- **El default de `emptyForm` pasó de `'1'` a vacío**, que es lo que permite completarlo solo
  sin pisar nada y lo que obliga a elegir cuando hay varios.

## Sin TanStack Query y sin Tailwind
Las dos por el mismo motivo: resuelven problemas que esta app todavía no tiene.

TanStack Query da caché compartida entre pantallas, deduplicación y revalidación en foco —
y acá son cuatro pantallas, cada una con su propia lista. `useResource` son treinta líneas.
Revisar cuando dos pantallas necesiten los mismos datos y empiecen a discrepar.

Tailwind: son formularios y tablas, y lo que se ahorraría en clases se pagaría en una
dependencia con su propio build. Revisar cuando el editor de facturas traiga drag-and-drop.

## Detalles que costaron una vuelta
- **`types.ts` se escribe a mano y tiene que coincidir *exactamente*.** `UserRead` del backend
  son dos campos, `id` y `email`. Declarar acá un `created_at` que el JSON no trae lo tipa
  como presente y el error sale recién en runtime, como un `undefined` en la pantalla. Y
  `MessageResponse` es `{detail}`, no `{message}`.
- **`EmailStr` rechaza los TLD reservados**: `@algo.local` y `@algo.test` dan 422. Para un
  usuario de prueba hay que usar un dominio real (`@factumov.com.ar`).
- **El token de confirmación es de un solo uso y StrictMode monta dos veces.** Sin un `useRef`
  de guarda, la confirmación anda y la pantalla muestra igual "el link no es válido", porque
  el segundo POST da 400.
- **El contexto, el provider y el hook van en tres archivos.** Fast Refresh solo recarga en
  caliente un módulo que exporta componentes nada más; mezclarlos hace que cada cambio
  recargue la página entera y se pierda el formulario que uno estaba probando.
- **El linter es `oxlint`** (viene con el scaffold) y avisa de `setState` sincrónico adentro
  de un efecto. Tenía razón las dos veces: en `useResource` el `loading` se prende ahora
  desde `reload`, que es el evento que lo causa, y en `ConfirmEmailPage` el caso "link sin
  token" se resuelve en el estado inicial porque ya se sabe al primer render.
- **Los enums viajan como el código de ARCA** (`condicion_iva: 1`), igual que en el backend.
  El texto de pantalla sale de `CONDICION_IVA_LABELS`; traducirlos en el cliente agregaría
  una tabla que se puede desincronizar.
- **Consumidor final no está en el desplegable de identidad fiscal**, porque no puede emitir y
  el backend lo rechaza con 422. No se ofrece una opción que siempre falla.
- **El lookup del padrón prellena el formulario y no da de alta.** Que quede editable es el
  punto: el backend devuelve una propuesta. Si guardara directo, consultar dos veces el mismo
  CUIT dejaría dos clientes.
- **El 502 y el `granted: false` se muestran distinto.** "No se pudo preguntar" y "no estás
  delegado" son cosas distintas; mezclarlas haría que un ARCA caído se vea como una
  delegación faltante y el usuario iría a otorgar una que ya tiene. **Pasó de verdad el
  2026-08-26:** ARCA homologación no contestó, salió el 502, y el cartel rojo se leyó como un
  rechazo. Ver *ARCA → Los 502 son transitorios*.

