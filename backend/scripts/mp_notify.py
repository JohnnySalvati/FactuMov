"""Dispara contra el backend local una notificación de Mercado Pago **firmada de verdad**.

Existe porque el webhook lo llama un servidor de Mercado Pago desde internet y a `localhost`
no llega. La alternativa es un túnel, y este script la evita: lo único que reemplaza es el
**transporte**. El endpoint verifica el HMAC igual que siempre —de ahí que haya que armar el
manifiesto exacto que espera `verify_signature`— y `_apply_preapproval` sale a releer el
recurso a la API de Mercado Pago, así que lo que se acredita es lo que ellos informan y no lo
que diga este archivo. O sea que no es un atajo que saltea la seguridad: es la misma
notificación, entregada a mano.

No está en `tests/` a propósito. Un test no puede autorizar un `preapproval` —eso lo hace una
persona en el checkout de Mercado Pago— así que esto no verifica nada solo: es la herramienta
con la que se recorre el circuito a mano. Ver *Monetización → Cómo se prueba*.

Uso, después de pagar el checkout con el usuario de prueba comprador:

    uv run python scripts/mp_notify.py preapproval <preapproval_id>
    uv run python scripts/mp_notify.py payment <authorized_payment_id>
"""

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

# El `.env` del backend, que es de donde sale el secreto con el que el endpoint va a
# verificar. Se lee el archivo en vez de importar `MercadoPagoSettings` para que el script
# no necesite el paquete instalado ni levante una sesión de base al importar.
DEFAULT_ENV = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_URL = "http://localhost:8000/webhooks/mercado-pago"

# Los dos temas que a la app le mueven algo. Las claves son cortas porque las escribe una
# persona en la terminal; los valores son los que Mercado Pago manda de verdad.
TOPICS = {
    "preapproval": "subscription_preapproval",
    "payment": "subscription_authorized_payment",
}


def read_secret(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MERCADOPAGO_WEBHOOK_SECRET="):
            secret = line.split("=", 1)[1].strip()
            if secret:
                return secret
    raise SystemExit(
        f"No hay MERCADOPAGO_WEBHOOK_SECRET con valor en {env_path}. Sin él el endpoint "
        "contesta 503 y no procesa nada."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(TOPICS), help="qué avisa la notificación")
    parser.add_argument("data_id", help="el id del recurso, tal como lo devuelve Mercado Pago")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    args = parser.parse_args()

    # El manifiesto que firma Mercado Pago: el id en minúscula, el `x-request-id` y el
    # timestamp, cada tramo terminado en punto y coma. Un tramo de más o de menos da otro
    # HMAC, así que esto tiene que quedar igual que en `verify_signature`.
    timestamp = str(int(time.time()))
    request_id = f"local-{timestamp}"
    manifest = f"id:{args.data_id.lower()};request-id:{request_id};ts:{timestamp};"
    signature = hmac.new(
        read_secret(args.env).encode(), manifest.encode(), hashlib.sha256
    ).hexdigest()

    request = urllib.request.Request(
        args.url,
        data=json.dumps({"type": TOPICS[args.kind], "data": {"id": args.data_id}}).encode(),
        headers={
            "Content-Type": "application/json",
            "x-signature": f"ts={timestamp},v1={signature}",
            "x-request-id": request_id,
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            print(response.status, response.read().decode())
    except urllib.error.HTTPError as error:
        # El status es la mitad de lo que se está probando —del otro lado Mercado Pago decide
        # si reintenta según él— así que un error se imprime igual que un éxito y no se
        # levanta: 401, 502 y 503 son respuestas legítimas de este endpoint.
        print(error.code, error.read().decode())


if __name__ == "__main__":
    main()
