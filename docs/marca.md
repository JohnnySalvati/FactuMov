# FactuMov — Marca y landing

> Parte de la documentación de FactuMov. El mapa completo está en
> [`docs/README.md`](README.md); las reglas de trabajo, en
> [`CLAUDE.md`](../CLAUDE.md).

Tres pedidos de Miguel del 2026-08-27 que no son funcionalidad de la app: ponerle la marca de
InSoft, publicarla en la landing y sacarla a producción. Van en ese orden porque cada una es
insumo de la siguiente: sin ícono no hay tarjeta ni favicon, y sin URL de producción la
tarjeta no tiene a dónde linkear.

**Las tres están escritas.** La marca, ver *La marca, hecha*; **producción** se mudó a su
propio archivo ([`produccion.md`](produccion.md), con el procedimiento en
[`DEPLOYMENT.md`](DEPLOYMENT.md)); **la landing** se escribió el 2026-08-28 y está lista para
subir — ver *La landing, escrita*. Lo que sigue abajo es el relevamiento con el que se hizo,
que se deja porque la landing es la única pieza del proyecto que vive fuera de este repo.

## Lo que ya existe y hay que reusar
La landing vive en `E:\Capacitacion\InSoft\LandingPage`, **fuera de este repo y sin git**: un
solo `insoft-v3-seo.html` (~620 líneas, CSS y JS inline), las imágenes sueltas al lado y
`scp.ps1`, que lo publica.

| Cosa | Dónde |
|---|---|
| Logo horizontal, vertical y tagline, en claro y oscuro | `LandingPage/insoft-logo-pack/*.svg` |
| Ícono suelto (la pastilla verde con el círculo blanco) | `LandingPage/insoft-icono.svg` |
| Favicons y `icon-512` ya generados | `LandingPage/insoft-logo-pack/` |
| Paleta | `--green:#2EBD59`, `--deep:#1B9E4B`, `--night:#0E1626`, tinta `#1E293B` |
| Tipografía de la landing | Manrope |

**El logo de InSoft es un interruptor**: una pastilla con gradiente vertical `#2EBD59 →
#1B9E4B` y un círculo blanco a la derecha, o sea encendido. Eso es la idea de toda la marca
("el software puede ser intuitivo"), y es lo que un ícono de producto tiene que citar sin
copiar.

## El ícono en la línea de Gastin
El de Gastin está inline en la landing (`<button class="mini">`, cerca de la línea 470) y su
construcción es la receta a seguir:

- `viewBox="0 0 120 120"`, fondo `<rect rx="23">` — o sea el radio de un ícono de app.
- **Un solo trazo** de 14 px con `stroke-linecap="round"`, que dibuja la inicial: una `G` que
  es un arco abierto.
- **El trazo termina en un punto** (`<circle r="6">`), que es la cita al círculo blanco del
  interruptor de InSoft.
- Dos estados: apagado en grises (`#E4EAE5` / `#BDC9C0`) y encendido con fondo `#0F172A` y el
  trazo en `var(--green)`. La landing los usa para su truquito de "encender" la tarjeta.

O sea que el de FactuMov es: fondo redondeado, un trazo verde que dibuje la `F`, y el punto al
final del trazo. La familia es la construcción, no el dibujo. Es lo que se construyó — ver
*La marca, hecha*.

**Cuidado con no inventar una tercera marca.** El acento de la SPA era `#1f6feb`, el azul del
default del scaffold, que no tenía nada que ver con InSoft. Ya es verde.

## La marca, hecha (2026-08-27)
`frontend/public/factumov-icon.svg` y su variante maskable, los PNG que salen de ellos, el
`manifest.webmanifest`, el acento verde de la SPA y el logo de InSoft en las pantallas sin
sesión. Se fueron el `favicon.svg` y el `icons.svg` del scaffold —una flecha violeta y un
juego de íconos de redes sociales que nadie importaba—.

### El ícono: una F de dos trazos, con el punto al final
La receta es la del de Gastin: `viewBox="0 0 120 120"`, fondo `#0F172A` con `rx="23"`, un trazo
de 14 con puntas redondas que dibuja la inicial, y un `<circle r="6">` donde ese trazo termina.
El punto es la cita al círculo blanco del interruptor de InSoft, que es la idea de toda la
marca.

- **La F no se puede dibujar de un trazo continuo, y la G sí.** A la F le sobra una rama: no
  hay recorrido que pase por el travesaño del medio, el asta y el travesaño de arriba sin
  levantar el lápiz. Son dos subpaths de un mismo `path` —`M82 33 H38 V87 M38 60 H68`— y el
  del medio arranca **sobre** el asta, así que su punta redonda queda escondida adentro y la
  unión no se ve. Lo que sí se conserva es dónde cae el punto: el travesaño corto de la F es
  el análogo exacto de la barra interna de la G.
- **El trazo lleva el gradiente vertical de la pastilla** (`#2EBD59` → `#1B9E4B`) y no el
  verde plano del de Gastin. Es el rasgo más reconocible de la marca de la casa y sale gratis.
  Va con `gradientUnits="userSpaceOnUse"` sobre la altura real del trazo con sus puntas (26 a
  94) y no sobre el bounding box, que en un path con stroke no incluye el ancho del trazo y
  dejaría el gradiente corrido.
- **Hay una variante maskable** (`factumov-icon-maskable.svg`): el mismo dibujo con el fondo
  llegando hasta el borde, sin las esquinas redondeadas. Android recorta el ícono con la forma
  que elija el launcher, así que uno que ya viene redondeado queda con un halo del fondo del
  sistema en las esquinas. La condición que hay que cumplir es que el contenido entre en el
  círculo seguro del 80% central: la punta más lejana de la F está a 45 del centro, contra los
  48 que mide ese radio.

### Los PNG salen del SVG, con las dependencias del backend
`frontend/scripts/render_icons.py` genera `icon-192`, `icon-512`, `icon-maskable-512` y
`apple-touch-icon`. Los PNG se versionan —ni el `apple-touch-icon` ni el manifest aceptan otra
cosa— pero **el SVG es la fuente**, y dibujarlos aparte sería una segunda versión del ícono
que nadie se va a acordar de actualizar.

En la máquina no hay ningún rasterizador de SVG: ni ImageMagick, ni Inkscape, ni cairosvg. Lo
que sí hay es el venv del backend, con **WeasyPrint** —que vino con el PDF del comprobante— y
**pypdfium2**, que viene de arrastre con él. WeasyPrint dibuja SVG y pypdfium2 rasteriza PDF,
así que el camino SVG → PDF → PNG usa dos dependencias que ya estaban en vez de sumar una
tercera solo para esto. Se corre desde `backend/` con su propio Python:

```powershell
cd E:\Capacitacion\InSoft\FactuMov\backend
.venv\Scripts\python.exe ..\frontend\scripts\render_icons.py
```

La página del PDF se arma del tamaño del `viewBox` en puntos y el escalado se hace al
rasterizar, así que cada tamaño se dibuja de nuevo desde las curvas y no es el chico agrandado.

### El acento de la SPA es verde, pero no *el* verde
`--accent` pasó de `#1f6feb` —el default del scaffold— a `#15803d`, y que no sea ninguno de
los dos verdes de la marca es a propósito. `--accent` es el color de **todos los links** y el
fondo de los botones primarios con texto blanco encima, o sea texto: necesita 4,5:1. El
`#2EBD59` de la marca da 2,5:1 contra el blanco y el `#1B9E4B` da 3,5:1 — los dos reprueban.
`#15803d` es el mismo tono bajado hasta 5,0:1 contra el blanco y 4,7:1 contra el fondo de la
página. El verde de la marca sigue vivo tal cual adentro de los SVG, que es donde es un dibujo
y no un texto.

`--ok` (`#1e7f4f`) quedó como estaba. Ahora es casi el mismo verde que el acento, y no molesta:
el aviso de "Guardado" es una caja de fondo pálido con texto oscuro y el botón primario es un
rectángulo lleno — se distinguen por la forma y no por el color, y que los dos verdes sean de
la misma familia es mejor que el verde contra azul de antes.

### Dónde aparece la marca
- **`components/BrandMark.tsx`** tiene las dos piezas: `BrandMark` —el ícono con "FactuMov" al
  lado— e `InSoftCredit` —"Una app de" más el logo de la casa, linkeado a insoft.net.ar—. Es un
  `<img>` al SVG de `public/` y no un SVG inline, porque el mismo archivo lo usan el favicon,
  el manifest y el script de los PNG: copiar el dibujo adentro del componente crearía una
  cuarta versión.
- **`components/PublicLayout.tsx` es una ruta de layout** que envuelve a las cinco pantallas
  sin sesión, con la marca arriba y el crédito de InSoft abajo. Es layout y no un componente
  que cada pantalla incluya, por el mismo motivo por el que `RequireAuth` envuelve al grupo:
  la regla escrita una vez no se puede olvidar en la pantalla que se agregue mañana.
- **El logo de InSoft va en las pantallas sin sesión y no en la barra de arriba.** Adentro de
  la app la marca que importa es la de FactuMov —es la pantalla que se abre cien veces por
  semana— y al que ya entró no hace falta recordarle de quién es esto. El lugar donde esa
  pregunta sí existe es antes de entrar.
- **El `<img>` del logo de InSoft va a 40 px y no a los 22 del renglón**: el SVG de la casa
  trae su propio margen adentro del `viewBox` —el dibujo ocupa 70 de sus 160 de alto— así que
  se ve a poco menos de la mitad de lo que mide el `<img>`.
- **El `<h1>` del login dejó de decir "Entrar a FactuMov"** y dice "Entrar". Con el nombre
  arriba en la marca, la otra mitad era el mismo nombre dos veces en dos renglones seguidos.

### El manifest, sin service worker
`manifest.webmanifest` con nombre, descripción, `start_url`, `display: standalone`, el
`background_color` del fondo de la página y el `theme_color` **del blanco de la barra de
arriba**, que es lo que queda pegado a la barra del sistema cuando corre instalada.

**No hay service worker, y eso significa que la app todavía no anda offline.** Con el manifest
alcanza para que Android ofrezca "agregar a la pantalla de inicio" y para que el ícono sea el
correcto; el prompt de instalación de Chrome en escritorio sí pide un service worker. Sumarlo
es su propia unidad —hay que decidir qué se cachea y cómo se invalida— y no bloquea nada.

### El PDF del comprobante no lleva marca — decidido el 2026-08-27
Quedaba abierto y lo cerró Miguel: `templates/invoice.html` se queda como está, sin ícono, sin
nombre y sin pie. El papel lo ve el cliente del usuario y no el usuario, y el emisor es el
contribuyente y no FactuMov: una marca ahí sería publicidad nuestra en un comprobante fiscal
ajeno. No hay nada pendiente de este lado.


## La landing, escrita (2026-08-28)
El pedido original está más abajo, en *El pedido*. Se hicieron las dos entradas —la tarjeta en
`#productos` y el `app-tile` del lanzador— y, de yapa, el ícono de producto que a Balance360 le
faltaba. **Está escrito y verificado en el navegador, pero todavía no publicado**: falta correr
`scp.ps1`, que es lo único que toca el server.

### La tarjeta describe con una lista y no con capturas
Balance360 muestra un carrusel de capturas reales y Gastin un mock de teléfono. FactuMov usa
una `<ul class="feat">` con las cuatro funcionalidades core en una línea cada una.

- **`.feat` ya estaba en el CSS y no la usaba nadie** — quedó de una versión anterior de la
  página. Sus viñetas son la pastilla de InSoft con el circulito blanco, o sea el interruptor
  encendido en miniatura, cuatro veces. Es el elemento que mejor ata la tarjeta a la marca de
  la casa, y estaba ahí sin costo.
- **Las capturas hubieran sido PNG nuevos** que hay que nombrar uno por uno en el `scp.ps1`,
  mantener sincronizados con una app que sigue cambiando y sacar de una cuenta con datos
  presentables. La lista dice lo mismo y no envejece.
- Que las tres tarjetas se cuenten distinto no es incoherencia: son tres etapas distintas de
  producto y cada una muestra lo que tiene.

**El texto se acortó después de verlo renderizado.** Con las viñetas largas la tarjeta quedaba
un tercio más alta que la de Balance360, y como el `.go` va con `margin-top:auto`, esa
diferencia se convierte en un hueco vacío en la tarjeta de al lado. Las viñetas de una línea lo
cierran casi entero.

### El ícono de la tarjeta es una copia del SVG, no un `<img>`
En la SPA la regla es al revés —`BrandMark` usa un `<img>` al SVG de `public/` justamente para
no tener dos versiones del dibujo—. Acá no se puede: la landing vive en otra carpeta, sin
repo, y se publica como un HTML suelto. El SVG está inline en la tarjeta, o sea que **hay una
segunda copia del ícono y su fuente sigue siendo
[`frontend/public/factumov-icon.svg`](../frontend/public/factumov-icon.svg)**: si el dibujo
cambia, hay que traerlo a mano.

### Balance360 tenía nombre pero no ícono (2026-08-28)
No existía en ningún lado —ni en su repo, que solo tiene el `favicon.ico` y el logo de
InSoft—, así que hubo que dibujarlo, con la misma receta que la G y la F: `viewBox 0 0 120
120`, fondo `#0F172A` con `rx="23"`, trazo de 14 con puntas redondas y el gradiente vertical de
la pastilla, y el punto blanco `r="6"`.

- **La B no tiene punta libre.** La G termina en su barra interna y la F en el travesaño del
  medio; la B es una letra cerrada — se dibuja como asta más dos panzas y el trazo vuelve
  siempre sobre sí mismo. Así que el punto no puede ir "al final del trazo".
- **Lo que se conserva es la coordenada.** En los tres íconos el punto cae en `(66, 60)`: a la
  altura de la cintura de la letra y a la derecha de su eje. Puestos uno al lado del otro, los
  tres puntos están alineados. La familia es dónde cae el punto, no la topología del trazo que
  lo trae hasta ahí.
- Son dos subpaths (`M38 87 V33 H66 A… H38` y `M38 60 H66 A… H38`) con el mismo truco que la F:
  el segundo arranca **sobre** el asta y su punta redonda queda escondida adentro.

### El panel del lanzador pasó de 430 a 520 px
`.apps-row` scrollea horizontal a propósito, con `scroll-snap`, para aguantar la app número
seis. Pero con tres `app-tile` de 150 px la tercera quedaba cortada al medio justo al abrir el
panel, que se lee como un bug y no como "hay más para el costado". A 520 px entran las tres
enteras y el scroll sigue estando para cuando haga falta. Abajo de 560 px no cambia nada: la
media query que ya estaba lo pisa con `position:fixed` y `width:auto`.

**El `app-tile` de FactuMov usa la pastilla genérica de `.app-ic`, igual que los otros dos.**
El ícono de producto va en la tarjeta, que es donde se lo presenta; en el lanzador lo que
importa es que las filas se lean como una lista pareja.

### Publicarla
`scp.ps1` **no necesitó archivos nuevos** —no se subieron capturas—, solo se le sumó el conteo
de menciones de FactuMov al paso 3, que es la única verificación de que nginx está sirviendo lo
que uno cree.

Antes de tocar el HTML se hizo una copia local `insoft-v3-seo.html.bak-<fecha>`, además del
`index.html.bak` que el propio `scp.ps1` deja **del lado del server**. La landing no tiene git:
esas dos copias son toda la red que hay.

## El pedido
Esto es lo que se relevó antes de escribirla, y quedó cumplido:

La tarjeta de FactuMov va en `#productos`, al lado de Balance360 y Gastin, y **la entrada en el
lanzador de apps del header** (`.apps-panel`), que es donde el usuario que ya la conoce va a
buscarla. Las dos con el mismo criterio que ya usa la página: un `chip` de estado ("En
producción" / "Beta") y un `.go` con el link.

- El texto tiene que decir qué hace en una línea, en el registro de las otras dos ("Tus
  finanzas completas en un solo lugar…"). Algo de la forma "Facturá desde el celular en dos
  toques: importás una factura, la guardás como modelo y emitís con CAE".
- Las capturas van como PNG al lado del HTML y **hay que sumarlas al `scp.ps1`**, que lista los
  archivos a subir uno por uno y no sube lo que no esté nombrado.
- La landing no tiene git. Antes de tocarla, copia de respaldo — el `scp.ps1` ya guarda un
  `index.html.bak` **del lado del server**, que es la única red que hay.
