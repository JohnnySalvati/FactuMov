"""Deriva los PNG de la marca a partir de los SVG de `public/`.

Los PNG se versionan —el navegador y las stores no aceptan otra cosa para el
apple-touch-icon ni para el OG image— pero **el SVG es la fuente**: retocarlo y volver a
correr esto es lo que mantiene a los dos en sincronía. Dibujar los PNG aparte sería una
segunda fuente de verdad capaz de contradecir al ícono que la app muestra en la pantalla.

No hay rasterizador de SVG instalado en la máquina (ni ImageMagick, ni Inkscape, ni
cairosvg). Lo que sí hay es el venv del backend, que trae **WeasyPrint** —para el PDF del
comprobante— y **pypdfium2**, que viene de arrastre con él. WeasyPrint sabe dibujar SVG y
pypdfium2 sabe rasterizar PDF, así que el camino SVG → PDF → PNG usa dos dependencias que ya
estaban en vez de agregar una tercera solo para esto.

    cd backend && .venv/Scripts/python.exe ../frontend/scripts/render_icons.py

La página del PDF se arma del mismo tamaño que el `viewBox` en **puntos**, y el escalado se
hace al rasterizar. Así el PNG grande no es un PNG chico agrandado: cada tamaño se dibuja de
nuevo desde las curvas.
"""

from __future__ import annotations

import io
from pathlib import Path

import pypdfium2
from weasyprint import HTML

PUBLIC = Path(__file__).resolve().parent.parent / "public"

# (svg, png, lado en px). El maskable va aparte porque su SVG es otro: Android le recorta las
# esquinas él mismo, así que el fondo tiene que llegar hasta el borde.
TARGETS = [
    ("factumov-icon.svg", "icon-192.png", 192),
    ("factumov-icon.svg", "icon-512.png", 512),
    # iOS no lee el manifest ni acepta SVG acá, y además le pone las esquinas redondeadas por
    # su cuenta — pero sobre el ícono tal cual, sin recortar contenido, así que va el normal.
    ("factumov-icon.svg", "apple-touch-icon.png", 180),
    ("factumov-icon-maskable.svg", "icon-maskable-512.png", 512),
]

# El lado del `viewBox` de los SVG de la marca.
VIEWBOX = 120


def render(svg: Path, png: Path, size: int) -> None:
    # `margin: 0` y una página exactamente del tamaño del dibujo: cualquier margen desplazaría
    # el ícono y el PNG dejaría de coincidir con el SVG.
    document = HTML(
        string=(
            f"<style>@page {{ size: {VIEWBOX}pt {VIEWBOX}pt; margin: 0 }}"
            f"html, body {{ margin: 0 }}"
            f"img {{ display: block; width: {VIEWBOX}pt; height: {VIEWBOX}pt }}</style>"
            f'<img src="{svg.name}">'
        ),
        base_url=str(svg.parent),
    )
    pdf = document.write_pdf()
    page = pypdfium2.PdfDocument(io.BytesIO(pdf))[0]
    page.render(scale=size / VIEWBOX).to_pil().save(png)
    print(f"{png.name}  {size}x{size}")


def main() -> None:
    for svg_name, png_name, size in TARGETS:
        render(PUBLIC / svg_name, PUBLIC / png_name, size)


if __name__ == "__main__":
    main()
