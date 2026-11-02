"""Las facturas de `tests/samples/`, que no viajan al repo.

El directorio está en el `.gitignore` a propósito: son facturas reales, con CUIT, nombres y
domicilios. Así que un test que lee una de ellas solo corre donde están —la máquina de Miguel—
y en cualquier otra copia (una sesión en la nube, la VM, un clon nuevo) **se saltea diciendo
qué archivo falta**, en vez de fallar con un `FileNotFoundError`.

Hasta 2026-11-02 fallaban: catorce rojos en cada copia sin las muestras, que no se distinguían
de una regresión hasta leer el traceback. Saltearlos no esconde nada: el resumen de pytest los
cuenta como "skipped" con el motivo, y donde las facturas están corren como siempre.

Un test que usa una factura solo de relleno no tiene por qué pasar por acá: puede mandar bytes
inventados, como el del límite de tamaño de la importación.
"""

from pathlib import Path

import pytest

SAMPLES = Path(__file__).parent / "samples"


def read_sample(name: str) -> bytes:
    """Los bytes de la factura de muestra, o el test salteado si no está en esta copia."""
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"Falta la factura de muestra {name}: tests/samples/ no viaja al repo.")
    return path.read_bytes()
