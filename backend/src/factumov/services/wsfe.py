"""Cliente de WSFEv1: verificación de la delegación y emisión con CAE.

`FECAESolicitar` es un port adaptado del de Balance360, con tres diferencias que vienen de
que acá el certificado es de FactuMov y representa a terceros:

- **El `Auth.Cuit` es el CUIT representado**, no el del certificado. En Balance360 coinciden.
- **No hay comprobantes asociados ni tributos.** FactuMov no emite notas de crédito —ver
  CLAUDE.md → *La letra del comprobante se deduce*— y no maneja percepciones. Los dos bloques
  del request de Balance360 se fueron; volverán con la unidad que los necesite, no antes.
- **Los importes los calcula `services/invoice_totals.py`** y llegan ya redondeados. Acá no
  se hace ninguna cuenta: este módulo traduce a SOAP y lee la respuesta, nada más.
"""

import datetime
from dataclasses import dataclass
from typing import Any

from requests.exceptions import RequestException
from zeep.exceptions import Fault

from factumov.enums import Concepto, DocType, VoucherType
from factumov.exceptions import ArcaError, InvalidEmissionDateError, WsfeError
from factumov.services import arca
from factumov.services.invoice_totals import InvoiceTotals

WSDL_URL = {
    "homo": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL",
    "prod": "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL",
}

# El servicio para el que WSAA emite el ticket. No es el nombre del WSDL: es el identificador
# que ARCA tiene registrado contra el certificado.
SERVICE = "wsfe"

# 600 es "ValidacionDeToken: No apareció CUIT en lista de relaciones". Es literalmente la
# respuesta a la pregunta de esta unidad: el certificado de FactuMov no está autorizado a
# actuar por ese CUIT. No es un error nuestro sino un "todavía no", así que es valor de
# retorno y no excepción.
NOT_DELEGATED_CODES = {600}

# 602 es "no hay datos". Un contribuyente delegado que todavía no dio de alta ningún punto de
# venta cae acá, y tratarlo como falla sería un falso negativo: la delegación *sí* está — la
# prueba es que ARCA aceptó el Auth y contestó sobre sus datos en vez de rechazar el token.
EMPTY_RESULT_CODES = {602}


@dataclass(frozen=True)
class PointOfSale:
    """Un punto de venta dado de alta en ARCA para el CUIT representado.

    El número es el dato que el usuario no tiene forma de adivinar: lo da de alta en ARCA y
    después la app se lo pide escrito. Traerlo de acá es la diferencia entre elegir de una
    lista y acertar un número.

    `emission_type` viaja para mostrarlo al lado del número —ARCA distingue CAE de CAEA, y un
    CUIT puede tener puntos de venta de los dos tipos— pero **no se filtra por él**: el
    vocabulario exacto de ese campo depende del régimen con el que se dio de alta el punto, y
    descartar por un valor que no conocemos escondería un punto de venta que sí sirve. Mejor
    ofrecerlo y que ARCA rechace al emitir, que es un error claro, antes que no ofrecerlo y
    que el usuario no entienda por qué falta.
    """

    number: int
    emission_type: str


@dataclass(frozen=True)
class DelegationCheck:
    """El resultado de preguntarle a ARCA si la delegación está otorgada.

    `granted=False` no es un error: es una de las dos respuestas esperadas, y la que recibe
    todo usuario que todavía no entró a ARCA a autorizarnos. Los errores de verdad —ARCA
    caído, certificado mal configurado— suben como `ArcaError` y terminan en un 502.

    Trae además los puntos de venta porque **la sonda ya los devuelve**: `FEParamGetPtosVenta`
    contesta la lista completa, y hasta ahora solo se miraba si había venido un error. Es la
    misma llamada, el mismo ticket y la misma cuota contra ARCA: parsear el payload sale gratis
    y evita una segunda ida a la red para preguntar algo que ya nos dijeron.
    """

    granted: bool
    message: str | None = None
    # Vacío cuando la delegación no está —ARCA no contesta datos de un CUIT que no nos
    # autorizó— y también cuando el contribuyente todavía no dio de alta ninguno (código 602).
    # Los dos casos son "no hay lista para ofrecer", que es lo que la pantalla necesita saber.
    points_of_sale: tuple[PointOfSale, ...] = ()


def _errors(response: Any) -> list[Any]:
    errors = getattr(response, "Errors", None)
    if errors is None:
        return []
    return list(errors.Err or [])


def check_delegation(
    tax_id: str, ticket_max_age: datetime.timedelta | None = None
) -> DelegationCheck:
    """¿ARCA acepta que FactuMov actúe por `tax_id` en WSFE?

    La sonda es `FEParamGetPtosVenta` y no `FECompUltimoAutorizado`, que es lo que Balance360
    usa para otra cosa. Dos razones: `FECompUltimoAutorizado` necesita un punto de venta, que
    acá habría que adivinar, y contesta error cuando ese punto de venta no existe — un falso
    negativo justo en el caso del usuario nuevo que sí nos delegó. `FEParamGetPtosVenta` no
    recibe parámetros, no escribe nada y necesita la misma delegación.

    El `Auth.Cuit` es el CUIT **representado**, no el del certificado. Esa brecha es toda la
    delegación: con el mismo ticket, ARCA acepta unos CUIT y rechaza otros.

    Devuelve además **los puntos de venta que la sonda trajo** — ver `DelegationCheck`.

    `ticket_max_age` existe porque el "no" de esta función caduca sin que nadie avise: el TA
    lleva la lista de relaciones congelada en el momento en que se emitió, así que preguntar
    con un ticket viejo es preguntar por el pasado. Quien llama sabe cuánta desactualización
    tolera —el barrido, una hora; alguien que acaba de apretar el botón, mucho menos— y por
    eso la política se pasa desde afuera en vez de fijarse acá. Ver
    `arca.get_access_ticket`.
    """
    ticket = arca.get_access_ticket(SERVICE, max_age=ticket_max_age)
    settings = arca.get_arca_settings()

    try:
        client = arca.build_client(WSDL_URL[settings.arca_env])
        response = client.service.FEParamGetPtosVenta(
            Auth={"Token": ticket.token, "Sign": ticket.sign, "Cuit": tax_id}
        )
    except Fault as exc:
        raise WsfeError(f"WSFE rechazó la consulta: {exc}") from exc
    except RequestException as exc:
        raise ArcaError("No se pudo conectar con ARCA, reintentá en unos minutos") from exc

    errors = _errors(response)
    if not errors:
        return DelegationCheck(granted=True, points_of_sale=_points_of_sale(response))

    codes = {int(error.Code) for error in errors}
    detail = " / ".join(f"{error.Code}: {error.Msg}" for error in errors)

    if codes <= EMPTY_RESULT_CODES:
        return DelegationCheck(granted=True)
    if codes & NOT_DELEGATED_CODES:
        return DelegationCheck(granted=False, message=detail)

    # Cualquier otro código es algo que no sabemos leer. Contestar `granted=False` haría que
    # el usuario reintentara para siempre una delegación que quizás ya otorgó.
    raise WsfeError(f"WSFE contestó un error inesperado: {detail}")


def _points_of_sale(response: Any) -> tuple[PointOfSale, ...]:
    """Lee `ResultGet.PtoVenta` y deja solo los puntos de venta que hoy pueden emitir.

    Se descartan dos cosas, y las dos por el mismo motivo —ofrecerlas sería ofrecer algo que
    va a fallar recién al pedir el CAE—:

    - **`Bloqueado = "S"`**: el punto de venta existe pero ARCA lo tiene inhabilitado.
    - **`FchBaja` con valor**: el punto de venta fue dado de baja. ARCA lo sigue listando con
      la fecha en que dejó de servir, y el campo llega como cadena vacía, `NULL` o `None`
      cuando el punto sigue vigente.

    Tolerante con lo que no sabe leer: un punto de venta cuyo número no es un entero se saltea
    en vez de romper la consulta entera. Esto alimenta un desplegable, no una validación — un
    dato ilegible tiene que costar un renglón de menos en la lista, no un 502.
    """
    result = getattr(response, "ResultGet", None)
    if result is None:
        return ()

    points = []
    for entry in getattr(result, "PtoVenta", None) or []:
        if str(getattr(entry, "Bloqueado", "") or "").upper() == "S":
            continue
        discharge = str(getattr(entry, "FchBaja", "") or "").strip()
        if discharge and discharge.upper() != "NULL":
            continue
        try:
            number = int(entry.Nro)
        except (AttributeError, TypeError, ValueError):
            continue
        points.append(PointOfSale(number=number, emission_type=str(entry.EmisionTipo or "")))

    return tuple(sorted(points, key=lambda point: point.number))


# --- Emisión ------------------------------------------------------------------------------


@dataclass(frozen=True)
class VoucherRequest:
    """Todo lo que WSFE necesita saber de un comprobante para autorizarlo.

    Plano y sin ORM a propósito, igual que `LineAmounts`: este módulo no tiene por qué
    conocer `Invoice` ni `Customer`, y con un dataclass los tests arman un caso en tres
    líneas en vez de tres filas en la base.

    No lleva número: **el número lo decide ARCA**, o más bien lo decide el último autorizado,
    y `authorize_invoice` lo averigua justo antes de pedir el CAE.
    """

    issuer_tax_id: str
    pos: int
    voucher_type: VoucherType
    date: datetime.date
    concepto: Concepto
    customer_doc_type: DocType
    customer_doc_number: str
    customer_condicion_iva: int
    totals: InvoiceTotals
    from_date: datetime.date | None = None
    to_date: datetime.date | None = None
    due_date: datetime.date | None = None


@dataclass(frozen=True)
class AuthorizationResult:
    """Lo que ARCA devolvió y que no se puede reconstruir: el CAE, su vencimiento y el número.

    Que el número esté acá y no lo haya elegido el que llamó es el punto: hasta que ARCA no
    contesta, la factura no tiene número.
    """

    cae: str
    cae_expiry: datetime.date
    number: int


@dataclass(frozen=True)
class LastVoucher:
    """El último comprobante autorizado de una serie: su número y su fecha.

    La fecha viene con el número porque de ella depende una validación que ARCA hace y que
    conviene hacer antes: **la numeración de un punto de venta no puede retroceder en el
    tiempo**. Emitir con fecha anterior a la del último autorizado da el código 10016, que no
    dice cuál era esa fecha y llega después de haber salido a la red.
    """

    number: int
    date: datetime.date | None


def get_last_voucher(tax_id: str, pos: int, voucher_type: VoucherType) -> LastVoucher:
    """El último comprobante autorizado para ese punto de venta y esa letra.

    ARCA contesta `CbteNro = 0` para un punto de venta recién dado de alta, así que el
    `or 0` no es un parche defensivo: es el caso normal de la primera factura. En ese caso la
    fecha viene vacía, y `None` es la respuesta correcta: no hay ningún piso que respetar.
    """
    ticket = arca.get_access_ticket(SERVICE)
    settings = arca.get_arca_settings()

    try:
        client = arca.build_client(WSDL_URL[settings.arca_env])
        response = client.service.FECompUltimoAutorizado(
            Auth={"Token": ticket.token, "Sign": ticket.sign, "Cuit": tax_id},
            PtoVta=pos,
            CbteTipo=voucher_type.arca_code,
        )
    except Fault as exc:
        raise WsfeError(f"WSFE rechazó la consulta del último comprobante: {exc}") from exc
    except RequestException as exc:
        raise ArcaError("No se pudo conectar con ARCA, reintentá en unos minutos") from exc

    errors = _errors(response)
    if errors:
        raise WsfeError(
            "WSFE no pudo dar el último comprobante: "
            + " / ".join(f"{error.Code}: {error.Msg}" for error in errors)
        )
    number: int = response.CbteNro or 0
    return LastVoucher(number=number, date=_parse_arca_date(getattr(response, "CbteFch", None)))


def _parse_arca_date(value: Any) -> datetime.date | None:
    """`"20260827"` → `date(2026, 8, 27)`. `None` para el punto de venta sin comprobantes.

    Tolerante a propósito con lo que no sabe leer: esta fecha alimenta una validación que
    ARCA repite de su lado, así que no entenderla significa perderse un mensaje mejor, no
    dejar pasar un comprobante mal.
    """
    if not value:
        return None
    try:
        return datetime.datetime.strptime(str(value), "%Y%m%d").date()
    except ValueError:
        return None


def _detail_request(request: VoucherRequest, number: int) -> dict[str, Any]:
    """El `FECAEDetRequest`, que es donde está todo lo que ARCA valida.

    `CbteDesde` y `CbteHasta` son el mismo número: ARCA permite autorizar un rango de
    comprobantes idénticos de una vez, y FactuMov emite de a uno.

    Los campos en cero —`ImpTotConc`, `ImpOpEx`, `ImpTrib`— van explícitos y no omitidos: son
    obligatorios en el esquema, y ARCA valida que `ImpTotal` sea exactamente la suma de los
    cinco. Mandarlos escritos deja esa cuenta a la vista de quien lea esto.
    """
    detail: dict[str, Any] = {
        "Concepto": request.concepto.arca_code,
        "CondicionIVAReceptorId": request.customer_condicion_iva,
        "DocTipo": request.customer_doc_type.value,
        "DocNro": int(request.customer_doc_number),
        "CbteDesde": number,
        "CbteHasta": number,
        "CbteFch": request.date.strftime("%Y%m%d"),
        "ImpTotal": request.totals.total,
        "ImpTotConc": 0,
        "ImpNeto": request.totals.net,
        "ImpOpEx": 0,
        "ImpIVA": request.totals.iva,
        "ImpTrib": 0,
        # Solo pesos. Facturar en dólares necesita además la cotización del día y una
        # decisión de producto sobre de dónde sale; no está en el alcance.
        "MonId": "PES",
        "MonCotiz": 1,
    }

    # El array `Iva` va solo cuando la letra aplica IVA. En una C, mandarlo —aunque sea con
    # alícuota 0— es un rechazo de ARCA, y omitirlo en una A o una B es otro.
    if request.totals.breakdown:
        detail["Iva"] = {
            "AlicIva": [
                {
                    "Id": item.aliquot.value,
                    "BaseImp": item.net,
                    "Importe": item.iva,
                }
                for item in request.totals.breakdown
            ]
        }

    if request.concepto.needs_service_dates:
        # Los tres van juntos o no va ninguno: ARCA los exige como conjunto cuando el
        # concepto no es "productos". Que sean obligatorios lo garantiza el schema del
        # endpoint, así que llegar acá con alguno en None sería un bug nuestro.
        if request.from_date is None or request.to_date is None or request.due_date is None:
            raise WsfeError(
                "Un comprobante de servicios necesita período desde, hasta y vencimiento"
            )
        detail["FchServDesde"] = request.from_date.strftime("%Y%m%d")
        detail["FchServHasta"] = request.to_date.strftime("%Y%m%d")
        detail["FchVtoPago"] = request.due_date.strftime("%Y%m%d")

    return detail


def authorize_invoice(request: VoucherRequest) -> AuthorizationResult:
    """Pide el CAE. **Esto emite una factura de verdad y no se puede deshacer.**

    Contra `ARCA_ENV=prod` el comprobante queda registrado en ARCA con validez legal, y la
    única forma de dejarlo sin efecto es una nota de crédito — que FactuMov no emite. El
    llamador tiene que estar seguro antes de llegar acá.

    El número sale de `get_last_voucher` + 1, o sea de una segunda llamada a ARCA
    inmediatamente anterior. Entre las dos hay una ventana en la que otro proceso podría
    tomar el mismo número; quien serializa eso es el candado de `crud/invoice.py`, y el
    backstop final es el propio ARCA, que rechaza un número ya usado.

    Esa misma respuesta trae la fecha del último autorizado, y con ella se corta acá el caso
    que ARCA rechazaría con el código 10016: **la numeración no puede retroceder en el
    tiempo**. Se levanta `InvalidEmissionDateError` —que no es un `ArcaError` y termina en un
    422— con la fecha mínima escrita en el mensaje, que es el dato que el usuario necesita y
    que el rechazo de ARCA no incluye.

    Dos formas de "no": `Errors` es un problema del request —mal armado, token vencido— y
    `Resultado != "A"` es un rechazo del comprobante en sí, con el motivo en
    `Observaciones`. Se leen las dos porque ARCA usa una u otra según qué le haya molestado,
    y quedarse con una sola deja la mitad de los rechazos como un `AttributeError`.
    """
    ticket = arca.get_access_ticket(SERVICE)
    settings = arca.get_arca_settings()
    last = get_last_voucher(request.issuer_tax_id, request.pos, request.voucher_type)
    number = last.number + 1

    if last.date is not None and request.date < last.date:
        raise InvalidEmissionDateError(
            f"El último comprobante {request.voucher_type.value} del punto de venta "
            f"{request.pos} es del {last.date.strftime('%d/%m/%Y')}, y ARCA no acepta que la "
            "numeración retroceda: elegí esa fecha o una posterior."
        )

    try:
        client = arca.build_client(WSDL_URL[settings.arca_env])
        response = client.service.FECAESolicitar(
            Auth={
                "Token": ticket.token,
                "Sign": ticket.sign,
                "Cuit": request.issuer_tax_id,
            },
            FeCAEReq={
                "FeCabReq": {
                    "CantReg": 1,
                    "PtoVta": request.pos,
                    "CbteTipo": request.voucher_type.arca_code,
                },
                "FeDetReq": {"FECAEDetRequest": [_detail_request(request, number)]},
            },
        )
    except Fault as exc:
        raise WsfeError(f"WSFE rechazó la solicitud de CAE: {exc}") from exc
    except RequestException as exc:
        raise ArcaError("No se pudo conectar con ARCA, reintentá en unos minutos") from exc

    errors = _errors(response)
    if errors:
        raise WsfeError(
            "WSFE rechazó la solicitud: "
            + " / ".join(f"{error.Code}: {error.Msg}" for error in errors)
        )

    detail = response.FeDetResp.FECAEDetResponse[0]
    if detail.Resultado != "A":
        observations = getattr(detail, "Observaciones", None)
        reason = (
            " / ".join(f"{obs.Code}: {obs.Msg}" for obs in observations.Obs)
            if observations is not None
            else "sin detalle"
        )
        raise WsfeError(f"ARCA no autorizó el comprobante: {reason}")

    return AuthorizationResult(
        cae=detail.CAE,
        cae_expiry=datetime.datetime.strptime(detail.CAEFchVto, "%Y%m%d").date(),
        number=number,
    )
