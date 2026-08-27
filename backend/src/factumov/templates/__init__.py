"""Los templates que se renderizan del lado del servidor.

Es un paquete y no una carpeta suelta para que `importlib.resources.files` lo encuentre desde
un wheel, donde el paquete puede no estar desplegado en el disco.

**Esto no es la capa web de Balance360.** El backend habla solo JSON: acá adentro hay un solo
archivo, la representación impresa del comprobante, que existe porque un PDF es HTML antes de
ser PDF. Las pantallas las hace la SPA.
"""
