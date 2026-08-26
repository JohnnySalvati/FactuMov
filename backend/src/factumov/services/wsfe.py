"""Cliente de WSFEv1. Por ahora solo lo que necesita verificar la delegación.

La emisión con CAE (`FECAESolicitar`) es otra unidad; el port de esa parte de Balance360 se
hace cuando haga falta, no antes.
"""

from dataclasses import dataclass
from typing import Any

from requests.exceptions import RequestException
from zeep.exceptions import Fault

from factumov.exceptions import ArcaError, WsfeError
from factumov.services import arca

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
class DelegationCheck:
    """El resultado de preguntarle a ARCA si la delegación está otorgada.

    `granted=False` no es un error: es una de las dos respuestas esperadas, y la que recibe
    todo usuario que todavía no entró a ARCA a autorizarnos. Los errores de verdad —ARCA
    caído, certificado mal configurado— suben como `ArcaError` y terminan en un 502.
    """

    granted: bool
    message: str | None = None


def _errors(response: Any) -> list[Any]:
    errors = getattr(response, "Errors", None)
    if errors is None:
        return []
    return list(errors.Err or [])


def check_delegation(tax_id: str) -> DelegationCheck:
    """¿ARCA acepta que FactuMov actúe por `tax_id` en WSFE?

    La sonda es `FEParamGetPtosVenta` y no `FECompUltimoAutorizado`, que es lo que Balance360
    usa para otra cosa. Dos razones: `FECompUltimoAutorizado` necesita un punto de venta, que
    acá habría que adivinar, y contesta error cuando ese punto de venta no existe — un falso
    negativo justo en el caso del usuario nuevo que sí nos delegó. `FEParamGetPtosVenta` no
    recibe parámetros, no escribe nada y necesita la misma delegación.

    El `Auth.Cuit` es el CUIT **representado**, no el del certificado. Esa brecha es toda la
    delegación: con el mismo ticket, ARCA acepta unos CUIT y rechaza otros.
    """
    ticket = arca.get_access_ticket(SERVICE)
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
        return DelegationCheck(granted=True)

    codes = {int(error.Code) for error in errors}
    detail = " / ".join(f"{error.Code}: {error.Msg}" for error in errors)

    if codes <= EMPTY_RESULT_CODES:
        return DelegationCheck(granted=True)
    if codes & NOT_DELEGATED_CODES:
        return DelegationCheck(granted=False, message=detail)

    # Cualquier otro código es algo que no sabemos leer. Contestar `granted=False` haría que
    # el usuario reintentara para siempre una delegación que quizás ya otorgó.
    raise WsfeError(f"WSFE contestó un error inesperado: {detail}")
