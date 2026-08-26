class DuplicateError(Exception):
    pass


class InUseError(Exception):
    pass


class DuplicateFiscalIdentityNameError(DuplicateError):
    pass


class DuplicateFiscalIdentityTaxIdError(DuplicateError):
    pass


class FiscalIdentityInUseError(InUseError):
    pass


class DuplicateCustomerError(DuplicateError):
    pass


class CustomerInUseError(InUseError):
    pass


class DuplicateInvoiceTemplateNameError(DuplicateError):
    pass


class DuplicateUserEmailError(DuplicateError):
    """Solo se llega acá por una carrera entre dos registros del mismo email.

    El camino normal del registro chequea antes con `get_by_email` y no llega a insertar.
    El router la atrapa y contesta lo mismo que en el caso feliz: dejarla salir como 409
    convertiría el registro en un oráculo de qué direcciones ya existen.
    """


class UnknownReferenceError(Exception):
    pass


class UnknownCustomerError(UnknownReferenceError):
    pass


class UnknownFiscalIdentityError(UnknownReferenceError):
    pass


class ArcaError(Exception):
    """No se pudo preguntarle a ARCA.

    Cubre el servicio caído, el timeout, el certificado mal configurado y cualquier
    respuesta que no se entienda. Es distinta de que ARCA conteste *que no*: eso es un
    valor de retorno (`DelegationCheck.granted`) y no una excepción, porque es la mitad
    esperada de las respuestas a "¿está la delegación?".
    """


class WsaaError(ArcaError):
    """Falló la autenticación contra WSAA: el certificado de FactuMov no sirve para
    ese servicio, o el TRA fue rechazado. Es un problema nuestro, no del usuario."""


class WsfeError(ArcaError):
    """WSFE contestó un error que no es "no estás delegado"."""


class PadronError(Exception):
    """El padrón no tiene datos para ese documento, o lo que se pidió no es un CUIT.

    Deliberadamente **no** baja de `ArcaError`: no es que ARCA falló, es que la pregunta no
    tiene respuesta. Termina en un 404 sobre el CUIT consultado, no en un 502 sobre nosotros.
    """
