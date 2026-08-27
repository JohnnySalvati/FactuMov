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


class DuplicateInvoiceNumberError(DuplicateError):
    """Ya existe una factura con ese número para ese CUIT, punto de venta y letra.

    Solo se llega acá por una carrera que el advisory lock de `crud/invoice.py` no atajó —o
    porque alguien lo sacó—. Es el backstop de la base: convierte una factura duplicada en un
    error en vez de en una fila, que es lo único que se puede hacer una vez que ARCA ya
    autorizó las dos.
    """


class InvoicePrintError(Exception):
    """No se pudo generar el PDF del comprobante.

    Hoy solo puede pasar porque falten weasyprint o las librerías GTK del sistema, que es un
    problema de la instalación y no del comprobante. Termina en un 500 y no en un 4xx: no hay
    nada que el usuario pueda hacer distinto.
    """


class DelegationNotVerifiedError(Exception):
    """Se quiso emitir con una identidad fiscal cuya delegación nunca se verificó.

    Es un estado del recurso y no un error del request: la respuesta es un 409, y el remedio
    es entrar a ARCA, otorgar la delegación y apretar "verificar". Sin este chequeo el
    intento igual fallaría, pero contra WSFE y con un mensaje de ARCA que no dice qué hacer.
    """


class InvalidEmissionDateError(Exception):
    """La fecha elegida para el comprobante está fuera de lo que ARCA acepta.

    Dos motivos distintos, y los dos terminan en un 422 con el texto puesto en el mensaje:
    la fecha se fue de la ventana alrededor de hoy (±5 días para productos, ±10 para
    servicios), o es anterior a la del último comprobante autorizado de esa serie — ARCA no
    admite que la numeración de un punto de venta retroceda en el tiempo.

    Es 422 y no 502 a propósito. Sin esto el intento igual fallaría, pero contra WSFE, con un
    código de ARCA que el usuario no puede leer y después de haberle pedido un CAE: un error
    del request tiene que morir antes de salir a la red, y el mensaje tiene que decir qué
    fechas sí se pueden.
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


class UndecidableVoucherTypeError(Exception):
    """No hay una letra de comprobante posible entre esas dos condiciones frente al IVA.

    Hoy solo puede pasar con un emisor consumidor final, que `FiscalIdentityCreate` ya rechaza
    con un 422 — o sea que por la API no se llega. Existe para que el invariante de
    `services/voucher.py` se rompa ruidosamente si mañana alguien afloja aquel validador, en
    vez de que la deducción devuelva una letra plausible y equivocada.
    """
