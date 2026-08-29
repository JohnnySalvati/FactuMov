"""El cliente de Balance360: arma el comprobante, lo manda y anota cómo salió.

**Nada de lo que pasa acá puede romper una emisión.** Cuando este módulo corre, ARCA ya
autorizó el comprobante y el CAE ya está guardado: el registro es una copia contable de un
hecho consumado. Por eso `register` no propaga excepciones —las convierte en un estado de la
factura— y por eso el disparo automático va en un `BackgroundTask`, que corre después de que
la respuesta salió. Un Balance360 caído tiene que dejar facturas en `FAILED`, no emisiones
sin contestar.

**El payload habla el idioma de FactuMov.** Los precios viajan tal como están guardados acá
—neto en la A, con IVA adentro en la B y en la C— y la traducción a la convención de
Balance360 ocurre allá. Es al revés de lo que parece natural, y es a propósito: si tradujera
el que llama, cambiar algo del modelo de datos de Balance360 obligaría a redeployar FactuMov.

Los enums viajan **por nombre**. `CondicionIva.FINAL` vale 5 acá y 6 allá, y el valor de
`IvaAliquot` es directamente el código de ARCA de este lado: por valor, un consumidor final
entraría del otro lado como monotributista sin que nada falle. Por nombre, un nombre que no
existe explota en la validación en vez de guardar otra cosa.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import requests
from requests.exceptions import RequestException
from sqlalchemy.orm import Session

from factumov.crud import balance360_connection as connection_crud
from factumov.crud import invoice as invoice_crud
from factumov.exceptions import Balance360Error, SecretDecryptionError, SecretsNotConfiguredError
from factumov.models.balance360_connection import Balance360Connection
from factumov.models.invoice import Invoice
from factumov.services import secrets

logger = logging.getLogger(__name__)

# Balance360 es una app propia, no un tercero: cuando anda contesta rápido, y cuando no anda
# no contesta nunca. Veinte segundos alcanzan de sobra y acotan lo que puede tardar "conectar",
# que es lo único que espera a esto con un usuario adelante.
TIMEOUT_SECONDS = 20

# Los últimos caracteres del token que se guardan en claro para que la pantalla los muestre.
TOKEN_HINT_LENGTH = 4

# Con qué nombre queda el token del otro lado. Es lo que se ve al listar credenciales en
# Balance360 y lo que decide cuál se revoca cuando se emite otra: emitir apaga al anterior con
# el mismo nombre, así que este string fijo es lo que hace que reconectar reemplace en vez de
# acumular. Cambiarlo dejaría vivo el token anterior sin que nadie lo use.
INTEGRATION_NAME = "FactuMov"


@dataclass(frozen=True)
class RegistrationResult:
    """Dónde quedó el comprobante del otro lado."""

    remote_invoice_id: uuid.UUID
    entity_name: str
    # `True` cuando el reintento encontró el registro anterior en vez de crear uno nuevo. Los
    # dos son éxito; la diferencia va al log.
    already_registered: bool


def token_hint(token: str) -> str:
    return token[-TOKEN_HINT_LENGTH:]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _detail(response: requests.Response) -> str:
    """El mensaje de Balance360, o uno propio si contestó cualquier cosa.

    El `detail` de la otra app está escrito para que lo lea un usuario —"el CUIT no está
    cargado", "elegí una entidad"— así que se propaga tal cual: es lo único que le dice qué
    tiene que arreglar, y reescribirlo acá sería perder la única información accionable.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    return f"Balance360 contestó {response.status_code}."


def fetch_token(base_url: str, email: str, password: str) -> str:
    """Cambia las credenciales del usuario por un token de Balance360.

    Es lo único que hace FactuMov con esa contraseña: la manda una vez y se queda con lo que
    vuelve. **No se guarda, no se loguea y no se le pasa a nadie más.** Guardarla sería el peor
    de los dos mundos —la base de FactuMov pasaría a tener acceso total a la contabilidad de
    cada usuario, y no solo el de escritura acotado del token— y además haría imposible cortar
    la integración sin cambiar la contraseña.

    Reemplaza a la pantalla que pedía pegar un token. Ese token había que emitirlo por ssh
    contra el servidor de Balance360, así que conectar la integración dependía de quien
    administra la VM; y lo que llegaba al portapapeles era un secreto de escritura pasando por
    un chat o un mail. Acá el secreto viaja una vez, entre las dos apps, y lo que queda
    guardado es una credencial que se revoca sola.

    Emitir uno nuevo **apaga el anterior del otro lado**, y es lo que hace que reconectar
    signifique reemplazar y no acumular. De la respuesta se lee solo el token: `replaced_previous`
    viene y se ignora porque acá no cambia nada —el que se apagó es el que esta misma fila está
    por pisar—, y mostrarlo sería contarle al usuario un detalle interno de la otra app.
    """
    try:
        response = requests.post(
            f"{base_url}/api/tokens",
            json={"email": email, "password": password, "name": INTEGRATION_NAME},
            headers={"Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
    except RequestException as error:
        raise Balance360Error(
            "No pudimos conectarnos con Balance360. Revisá la dirección y que esté prendido."
        ) from error

    if response.status_code == 401:
        # No es reintentable: mandar las mismas credenciales va a dar 401 para siempre. El
        # mensaje es el de Balance360 —dice si la cuenta está desactivada o si las credenciales
        # no son— y es lo único que le dice al usuario qué corregir.
        raise Balance360Error(_detail(response), retryable=False)
    if response.status_code == 404:
        # La dirección contesta pero no conoce el endpoint. Es un caso propio y no "Balance360
        # contestó 404" porque tiene una causa concreta y una salida concreta: del otro lado
        # hay una versión anterior a este circuito, y hasta que se actualice el token se emite
        # a mano con `create_api_token.py`.
        raise Balance360Error(
            "Esa dirección contesta, pero ese Balance360 todavía no sabe emitir tokens. "
            "Actualizalo, o pedile a quien administra el servidor que emita uno a mano.",
            retryable=False,
        )
    if not response.ok:
        # El 429 entra por acá con el mensaje de Balance360, que ya dice que hay que esperar.
        # Es reintentable a propósito: lo que hace falta es tiempo, no corregir nada.
        raise Balance360Error(_detail(response))

    try:
        body = response.json()
    except ValueError as error:
        raise Balance360Error("Balance360 contestó algo que no entendimos.") from error

    token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise Balance360Error("Balance360 contestó algo que no entendimos.")
    return token


def build_payload(invoice: Invoice) -> dict[str, Any]:
    """El comprobante en el contrato de `/api/invoices/issued`.

    Sale del emisor y el receptor **copiados en la factura** y no de las fichas actuales, por
    lo mismo por lo que están copiados: es lo que ARCA autorizó y lo que salió impreso. Un
    registro tardío no puede llevarse del otro lado un domicilio que ya cambió.

    El documento del receptor viaja siempre en `tax_id`, sea CUIT o DNI, porque del otro lado
    esa columna es "el número del documento" —convive con `doc_type`, que dice de cuál—. Y es
    además lo que evita que cada factura B a un consumidor final cree un contacto nuevo.
    """
    return {
        # El id de esta factura es la clave de idempotencia: reintentar no duplica.
        "external_id": str(invoice.id),
        "issuer_tax_id": invoice.issuer_tax_id,
        "customer": {
            "name": invoice.customer_name,
            "tax_id": invoice.customer_doc_number,
            "doc_type": invoice.customer_doc_type.name,
            "condicion_iva": invoice.customer_condicion_iva.name,
            "address": invoice.customer_address,
            "email": invoice.customer_email,
        },
        # `voucher_type` y `concepto` por valor y no por nombre: su valor **es** el nombre
        # legible ("A", "products") y coincide en las dos apps. Los otros tres enums no.
        "voucher_type": invoice.voucher_type.value,
        "pos": invoice.pos,
        "number": invoice.number,
        "date": invoice.date.isoformat(),
        "concepto": invoice.concepto.value,
        "from_date": invoice.from_date.isoformat() if invoice.from_date else None,
        "to_date": invoice.to_date.isoformat() if invoice.to_date else None,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "cae": invoice.cae,
        "cae_expiry": invoice.cae_expiry.isoformat(),
        "lines": [
            {
                "description": line.description,
                # Los Decimal van como string y no como número: `json` serializa un float y
                # 0.1 deja de ser 0,1. Del otro lado pydantic los lee como Decimal exacto, que
                # es lo que después tiene que cerrar contra el CAE al centavo.
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "iva_aliquot": line.iva_aliquot.name,
            }
            for line in invoice.lines
        ],
        # Los importes que autorizó ARCA. No se guardan del otro lado —Balance360 los deriva
        # de las líneas— y viajan para que allá se comparen contra lo que dio la traducción de
        # precios. Si no cierran, no se registra nada.
        "totals": {
            "net": str(invoice.net_total),
            "iva": str(invoice.iva_total),
            "total": str(invoice.total),
        },
    }


def _post(
    connection: Balance360Connection, token: str, payload: dict[str, Any]
) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{connection.base_url}/api/invoices/issued",
            json=payload,
            headers=_headers(token),
            timeout=TIMEOUT_SECONDS,
        )
    except RequestException as error:
        raise Balance360Error(
            "No pudimos conectarnos con Balance360. La factura está emitida igual; "
            "el registro se puede reintentar."
        ) from error

    if response.status_code == 401:
        raise Balance360Error(
            "Balance360 no aceptó el token. Volvé a conectar la cuenta desde Ajustes.",
            retryable=False,
        )
    if response.status_code in (400, 404, 409, 422):
        # Errores del comprobante o de lo que falta cargar allá: el CUIT que no está, la
        # entidad ambigua, un número ya tomado. Reintentar sin cambiar nada da lo mismo, así
        # que se marcan como no reintentables y el mensaje dice qué arreglar.
        raise Balance360Error(_detail(response), retryable=False)
    if not response.ok:
        raise Balance360Error(_detail(response))

    body = response.json()
    if not isinstance(body, dict) or "id" not in body:
        raise Balance360Error("Balance360 contestó algo que no entendimos.")
    return body


def register(db: Session, invoice: Invoice) -> RegistrationResult | None:
    """Copia la factura a Balance360 y deja anotado cómo salió. **No levanta nunca.**

    Devuelve el resultado si quedó registrada y `None` si no, pero el valor de retorno casi no
    se usa: lo que importa es el estado que queda escrito en la factura, que es lo que después
    leen la pantalla y el reintento. La política de tragarse los errores es la misma decisión
    que la de `send_email_best_effort` y por el mismo motivo — esto acompaña a una operación
    que ya terminó, no es el producto de ningún request.

    **Hace `commit` él mismo.** El disparo automático corre en un `BackgroundTask` con su
    propia sesión, después de que la respuesta salió, así que no hay ningún request que vaya a
    commitear por él; el reintento manual llama igual y se encuentra la transacción cerrada.
    """
    connection = connection_crud.get_for_user(db, invoice.fiscal_identity.user_id)
    if connection is None:
        # Se desconectó entre la emisión y el registro. No es un fallo de nada: la factura
        # vuelve a quedar fuera del circuito, que es lo que significa el estado `NULL`.
        invoice.balance360_status = None
        db.commit()
        return None

    try:
        token = secrets.decrypt(connection.encrypted_token)
    except (SecretsNotConfiguredError, SecretDecryptionError) as error:
        invoice_crud.mark_balance360_failed(
            db,
            invoice,
            "El servidor no puede leer el token guardado. Volvé a conectar la cuenta.",
        )
        db.commit()
        logger.error("No se pudo descifrar el token de Balance360: %s", error)
        return None

    try:
        body = _post(connection, token, build_payload(invoice))
    except Balance360Error as error:
        invoice_crud.mark_balance360_failed(db, invoice, str(error))
        db.commit()
        logger.warning("No se registró la factura %s en Balance360: %s", invoice.label, error)
        return None

    result = RegistrationResult(
        remote_invoice_id=uuid.UUID(body["id"]),
        entity_name=str(body.get("entity_name", "")),
        already_registered=bool(body.get("already_registered")),
    )
    invoice_crud.mark_balance360_registered(db, invoice, result.remote_invoice_id)
    # El token anduvo: la pantalla puede decir "verificada hace un rato" sin que nadie haya
    # apretado "probar". Un registro exitoso es la mejor prueba que hay de que sirve.
    connection_crud.mark_verified(db, connection)
    db.commit()
    logger.info(
        "Factura %s registrada en Balance360 como %s%s.",
        invoice.label,
        result.remote_invoice_id,
        " (ya estaba)" if result.already_registered else "",
    )
    return result


def register_in_background(invoice_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """El disparo de después de emitir, con su propia sesión.

    Recibe ids y no objetos: cuando esto corre, la sesión del request ya se cerró y las
    instancias que colgaban de ella quedaron desprendidas. Traerlas de nuevo es una query
    contra una base que ya está caliente, y es lo único que garantiza que se escriba sobre la
    fila y no sobre una copia vieja.

    Se traga cualquier excepción y la loguea. Corre fuera del ciclo del request: una que suba
    acá no la ve nadie, no le llega a ningún usuario y —según cómo la maneje el servidor—
    puede terminar tirando el worker abajo por una copia contable que se reintenta con un
    botón.
    """
    from factumov import database

    try:
        with database.SessionLocal() as db:
            invoice = invoice_crud.get_by_id(db, invoice_id, user_id)
            if invoice is None:
                return
            register(db, invoice)
    except Exception:
        logger.exception("Falló el registro en Balance360 de la factura %s", invoice_id)
