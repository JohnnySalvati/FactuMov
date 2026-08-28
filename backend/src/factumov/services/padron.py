"""Consulta al padrón de ARCA para completar un cliente o una identidad fiscal desde el CUIT.

Port del `services/padron.py` de Balance360. Trae razón social, domicilio fiscal y condición
frente al IVA, para no tipearlos a mano ni equivocarse. La firma y la forma de la respuesta
salen del WSDL:

    getPersona_v2(token, sign, cuitRepresentada, idPersona) -> personaReturn
    personaReturn(datosGenerales, datosRegimenGeneral, datosMonotributo, error*)

`cuitRepresentada` es el dueño del certificado (`arca.get_certificate_tax_id`) y `idPersona`
el CUIT que se consulta. Ojo con la asimetría respecto de WSFE: en WSFE el `Auth.Cuit` es el
CUIT **representado** y por eso hace falta la delegación de cada contribuyente; acá el CUIT
representado somos nosotros mismos, así que el padrón funciona sin que el usuario delegue
nada. Es una consulta pública que ARCA hace en nombre de quien tiene el certificado.

El ticket se pide para `ws_sr_constancia_inscripcion` y no para `ws_sr_padron_a5`: ARCA sacó
el A5 del Administrador de Relaciones, y "Consulta de constancia de inscripción" es el que lo
reemplaza. Comparten el endpoint `personaServiceA5` y la forma de la respuesta.

Se eligió este y no el A13 —que también figura en el listado— porque el A13 devuelve razón
social y domicilio pero **no** los impuestos ni el monotributo, o sea que no permite deducir
la condición frente al IVA, que es justo el dato que el editor no puede adivinar.

El servicio necesita estar delegado al certificado de FactuMov en el portal de ARCA; sin eso
WSAA responde "Computador no autorizado a acceder al servicio" y no se llega ni a la
consulta. En producción se delega por Administrador de Relaciones; en homologación por WSASS,
donde figura como `ws_sr_constancia_inscripcion` (la lista se ordena por código, no por
descripción).

El padrón de homologación tiene contribuyentes de prueba, no los reales, pero alcanza para
probar la cadena entera. Estos tres existen y cubren una condición IVA cada uno:

    30500010912 -> INSCRIPTO
    20000000001 -> MONOTRIBUTO
    33693450239 -> FINAL

Un CUIT sin datos se manifiesta de dos formas distintas y las dos terminan en `PadronError`:
un Fault ("No existe persona con ese Id") o una respuesta con `datosGenerales` vacío.
"""

from dataclasses import dataclass
from typing import Any

from requests.exceptions import RequestException
from zeep.exceptions import Fault

from factumov.enums import CondicionIva
from factumov.exceptions import ArcaError, PadronError
from factumov.services import arca
from factumov.services.rate_limit import RateLimiter

SERVICE = "ws_sr_constancia_inscripcion"

# La cuota del padrón la fija ARCA contra **el certificado**, que es uno solo para toda la
# app: un usuario tecleando CUITs en un loop se la gasta a todos los demás. Por eso el límite
# va por usuario y no por IP —los endpoints están autenticados, así que hay una clave mejor
# que la dirección— y por eso existe aunque acá no haya nada que enumerar.
#
# **Vive acá y no en un router porque el presupuesto es uno solo.** Lo consultan el alta de un
# cliente y la de una identidad fiscal, y son la misma llamada al mismo servicio contra el
# mismo certificado: con un limitador por router, alternar entre las dos pantallas daría el
# doble de llamadas, que es el mismo argumento por el que `verify-delegation` y
# `claim-delegation` comparten el suyo. Ponerlo en uno de los dos routers obligaría al otro a
# importar de un router hermano, que es lo que el proyecto evita desde que `get_current_user`
# se mudó a `dependencies.py`.
#
# Treinta por hora es holgado para cargar a mano y corto para un script.
LIMITER = RateLimiter(limit=30, window_seconds=60 * 60)

WSDL_URL = {
    "homo": "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5?wsdl",
    "prod": "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5?wsdl",
}

# idImpuesto del padrón. El monotributo no figura como impuesto: viene en su propio bloque
# `datosMonotributo`, así que se pregunta por ese antes que por estos.
IVA_INSCRIPTO = 30
IVA_EXENTO = 32

# El domicilio va a `Customer.address` o a `FiscalIdentity.address`, las dos String(200).
ADDRESS_MAX_LENGTH = 200

# Y la razón social a `.name`, String(150) en las dos tablas. El padrón no promete un techo.
NAME_MAX_LENGTH = 150


@dataclass(frozen=True)
class Taxpayer:
    """Lo que el padrón sabe de un CUIT, ya traducido al vocabulario de FactuMov."""

    tax_id: str
    name: str
    address: str | None
    condicion_iva: CondicionIva
    active: bool


def get_taxpayer(tax_id: str) -> Taxpayer:
    """Los datos de un contribuyente, por CUIT. Solo lee: no escribe nada en la base.

    Igual que el endpoint de importación, esto devuelve una *propuesta*. Dar de alta el
    cliente sin que el usuario confirme convertiría una consulta en un efecto secundario.
    """
    cuit = "".join(c for c in tax_id if c.isdigit())
    if len(cuit) != 11:
        raise PadronError("El CUIT tiene que tener 11 dígitos")

    ticket = arca.get_access_ticket(SERVICE)
    settings = arca.get_arca_settings()

    try:
        client = arca.build_client(WSDL_URL[settings.arca_env])
        response = client.service.getPersona_v2(
            token=ticket.token,
            sign=ticket.sign,
            cuitRepresentada=int(arca.get_certificate_tax_id()),
            idPersona=int(cuit),
        )
    except Fault as exc:
        # "No existe persona con ese Id" llega por acá. Es PadronError y no ArcaError: la
        # consulta funcionó, la respuesta es que ese CUIT no está.
        raise PadronError(f"ARCA: {exc}") from exc
    except RequestException as exc:
        raise ArcaError("No se pudo conectar con ARCA, reintentá en unos minutos") from exc

    return to_taxpayer(cuit, response)


def to_taxpayer(cuit: str, response: Any) -> Taxpayer:
    """Traduce la respuesta de zeep. Separada de la consulta para poder testearla sin red."""
    general = getattr(response, "datosGenerales", None)
    if general is None:
        raise PadronError(f"ARCA no tiene datos para el CUIT {cuit}")

    return Taxpayer(
        tax_id=cuit,
        name=_name(general),
        address=_address(getattr(general, "domicilioFiscal", None)),
        condicion_iva=_condicion_iva(response),
        active=str(getattr(general, "estadoClave", "") or "").upper() == "ACTIVO",
    )


def _name(general: Any) -> str:
    """Razón social para una persona jurídica; nombre y apellido para una física."""
    razon_social = (getattr(general, "razonSocial", None) or "").strip()
    if razon_social:
        return razon_social[:NAME_MAX_LENGTH]

    nombre = (getattr(general, "nombre", None) or "").strip()
    apellido = (getattr(general, "apellido", None) or "").strip()
    return " ".join(part for part in (nombre, apellido) if part)[:NAME_MAX_LENGTH]


def _address(domicilio: Any) -> str | None:
    """Una sola línea, que es como la guarda `Customer.address`.

    Se omite la provincia cuando repite la localidad (CABA la trae dos veces) y se recorta al
    largo de la columna: preferimos un domicilio incompleto a que el alta explote al guardar.
    """
    if domicilio is None:
        return None

    parts: list[str] = []
    for field in ("direccion", "localidad", "descripcionProvincia"):
        value = (getattr(domicilio, field, None) or "").strip()
        if value and value.lower() not in (part.lower() for part in parts):
            parts.append(value)

    cod_postal = (getattr(domicilio, "codPostal", None) or "").strip()
    if cod_postal:
        parts.append(f"CP {cod_postal}")

    return ", ".join(parts)[:ADDRESS_MAX_LENGTH] or None


def _condicion_iva(response: Any) -> CondicionIva:
    if getattr(response, "datosMonotributo", None) is not None:
        return CondicionIva.MONOTRIBUTO

    regimen_general = getattr(response, "datosRegimenGeneral", None)
    impuestos = {
        impuesto.idImpuesto for impuesto in (getattr(regimen_general, "impuesto", None) or [])
    }

    if IVA_INSCRIPTO in impuestos:
        return CondicionIva.INSCRIPTO
    if IVA_EXENTO in impuestos:
        return CondicionIva.EXENTO
    # Ni inscripto, ni exento, ni monotributista: para el que emite, consumidor final.
    return CondicionIva.FINAL
