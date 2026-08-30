"""Dibuja los señaladores sobre las capturas de ARCA para el instructivo de delegación.

Las capturas crudas viven en `scripts/guia-delegacion/` (1.png … 6.png, tal como las sacó
Miguel del portal de ARCA a 1920×1032) y **son la fuente**: retocar el recorte o mover una
flecha se hace acá y se vuelve a correr, igual que `render_icons.py`. Dibujar los PNG
anotados a mano sería una segunda versión que nadie se va a acordar de rehacer cuando ARCA
cambie una pantalla.

    cd backend && .venv/Scripts/python.exe ../frontend/scripts/annotate_delegation_guide.py

Sale un PNG por figura en `public/guia-delegacion/`, ya recortado a la zona que importa y
con un círculo numerado + flecha en cada lugar donde hay que hacer clic. El texto que
explica cada número va en el `<figcaption>` de la página, no quemado en la imagen: así se
corrige sin volver a rasterizar y lo lee un lector de pantalla.

La numeración de los círculos es la de los pasos de la página. Las tres pantallas que el
contribuyente y el operador recorren igual —«Nueva Relación», la lista de organismos y la
lista de servicios— comparten figura y comparten número, así que se generan una sola vez y
las usan las dos páginas.

Pillow entra de arrastre con WeasyPrint (el PDF del comprobante), misma razón por la que
`render_icons.py` usa pypdfium2: no se agrega una dependencia para esto.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path(__file__).resolve().parent / "guia-delegacion"
OUT = Path(__file__).resolve().parent.parent / "public" / "guia-delegacion"

RED = (229, 40, 34)
HALO = (229, 40, 34, 70)
WHITE = (255, 255, 255)

# Arial Bold para los números del círculo. Es la que hay en Windows, que es donde se corre
# esto; si falta, Pillow cae en su tipografía de mapa de bits, que también sirve.
try:
    _BADGE_FONT = ImageFont.truetype("arialbd.ttf", 30)
except OSError:  # pragma: no cover - depende de la máquina
    _BADGE_FONT = ImageFont.load_default()

Box = tuple[int, int, int, int]


class Marker:
    """Un lugar de la captura donde hay que hacer clic: el recuadro, el número y de qué lado
    sale la flecha ('left' | 'right' | 'above' | 'below')."""

    def __init__(self, box: Box, number: int, side: str) -> None:
        self.box = box
        self.number = number
        self.side = side


class Figure:
    def __init__(self, src: str, name: str, crop: Box, markers: list[Marker]) -> None:
        self.src = src
        self.name = name
        self.crop = crop
        self.markers = markers


# Coordenadas en píxeles de la captura cruda (1920×1032). El recorte deja fuera la barra del
# navegador, la navegación lateral de ARCA y el espacio en blanco: lo que queda es la zona
# donde está el botón del paso.
FIGURES = [
    Figure(
        "1.png",
        "portal-contribuyente",
        crop=(348, 165, 1560, 420),
        markers=[Marker((1074, 205, 1284, 300), 1, "below")],
    ),
    Figure(
        "1.png",
        "portal-operador",
        crop=(360, 470, 1320, 730),
        markers=[Marker((610, 543, 840, 634), 1, "below")],
    ),
    Figure(
        "2.png",
        "nueva-relacion",
        crop=(745, 150, 1445, 362),
        markers=[Marker((1283, 266, 1401, 301), 2, "left")],
    ),
    Figure(
        "3.png",
        "representado-y-servicio",
        crop=(780, 118, 1418, 386),
        markers=[
            Marker((955, 250, 1313, 273), 3, "left"),
            Marker((1290, 283, 1375, 307), 4, "below"),
        ],
    ),
    Figure(
        "4.png",
        "organismo-arca",
        crop=(352, 700, 785, 843),
        markers=[
            Marker((369, 736, 607, 783), 5, "right"),
            Marker((402, 814, 508, 836), 6, "right"),
        ],
    ),
    Figure(
        "5.png",
        "servicio-facturacion-electronica",
        crop=(352, 862, 1240, 1032),
        markers=[Marker((404, 958, 664, 1016), 7, "right")],
    ),
    Figure(
        "6.png",
        "representante-y-confirmar",
        crop=(780, 120, 1415, 410),
        markers=[
            Marker((1290, 321, 1376, 346), 8, "left"),
            Marker((1037, 356, 1135, 388), 9, "left"),
        ],
    ),
]


def _rounded(draw: ImageDraw.ImageDraw, box: Box, radius: int, width: int, color) -> None:
    draw.rounded_rectangle(box, radius=radius, outline=color, width=width)


def _badge(draw: ImageDraw.ImageDraw, center: tuple[int, int], number: int) -> None:
    cx, cy = center
    r = 26
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED, outline=WHITE, width=4)
    text = str(number)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=_BADGE_FONT)
    draw.text(
        (cx - (right - left) / 2 - left, cy - (bottom - top) / 2 - top),
        text,
        font=_BADGE_FONT,
        fill=WHITE,
    )


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int]) -> None:
    draw.line((start, end), fill=RED, width=6)
    # Punta: un triángulo apoyado en `end`, apuntando en la dirección start -> end.
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 22
    left = (
        end[0] - size * math.cos(angle - math.pi / 7),
        end[1] - size * math.sin(angle - math.pi / 7),
    )
    right = (
        end[0] - size * math.cos(angle + math.pi / 7),
        end[1] - size * math.sin(angle + math.pi / 7),
    )
    draw.polygon((end, left, right), fill=RED)


def _place(marker: Marker, crop: Box) -> tuple[tuple[int, int], tuple[int, int]]:
    """Centro del círculo y punta de la flecha, en coordenadas ya recortadas."""
    cl, ct = crop[0], crop[1]
    mx0, my0, mx1, my1 = marker.box
    x0, y0, x1, y1 = mx0 - cl, my0 - ct, mx1 - cl, my1 - ct
    gap = 58
    if marker.side == "left":
        return (x0 - gap, (y0 + y1) // 2), (x0 - 6, (y0 + y1) // 2)
    if marker.side == "right":
        return (x1 + gap, (y0 + y1) // 2), (x1 + 6, (y0 + y1) // 2)
    if marker.side == "above":
        return ((x0 + x1) // 2, y0 - gap), ((x0 + x1) // 2, y0 - 6)
    return ((x0 + x1) // 2, y1 + gap), ((x0 + x1) // 2, y1 + 6)


def render(figure: Figure) -> None:
    base = Image.open(SRC / figure.src).convert("RGBA")
    cropped = base.crop(figure.crop)

    halo = Image.new("RGBA", cropped.size, (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(halo)
    cl, ct, _, _ = figure.crop
    for marker in figure.markers:
        box = (
            marker.box[0] - cl - 7,
            marker.box[1] - ct - 7,
            marker.box[2] - cl + 7,
            marker.box[3] - ct + 7,
        )
        _rounded(hdraw, box, radius=14, width=16, color=HALO)
    cropped = Image.alpha_composite(cropped, halo)

    draw = ImageDraw.Draw(cropped)
    for marker in figure.markers:
        box = (
            marker.box[0] - cl,
            marker.box[1] - ct,
            marker.box[2] - cl,
            marker.box[3] - ct,
        )
        _rounded(draw, box, radius=10, width=5, color=RED)
        badge_center, arrow_tip = _place(marker, figure.crop)
        _arrow(draw, badge_center, arrow_tip)
        _badge(draw, badge_center, marker.number)

    OUT.mkdir(parents=True, exist_ok=True)
    cropped.convert("RGB").save(OUT / f"{figure.name}.png")
    print(f"{figure.name}.png  {cropped.size[0]}x{cropped.size[1]}")


def main() -> None:
    for figure in FIGURES:
        render(figure)


if __name__ == "__main__":
    main()
