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


class PlanLimitReachedError(Exception):
    """Lo que se pidió está fuera de lo que el plan del usuario permite.

    Una sola excepción para los dos límites del Free —los comprobantes del mes y la cantidad
    de identidades fiscales— porque el router hace exactamente lo mismo con las dos: contestar
    **402** con el texto que trae la excepción. Dos tipos distintos serían dos `except` que
    levantan la misma respuesta, y la diferencia que importa —qué límite se chocó y qué hacer—
    ya está en el mensaje, que es lo único que el usuario lee.

    **402 y no 403.** El 403 dice "no tenés permiso", que acá es falso: el usuario tiene todo
    el permiso del mundo sobre sus propios datos, lo que falta es el plan. El 402 existe
    exactamente para esto y le deja al frontend distinguir "necesitás Pro" —que se resuelve
    con una pantalla de suscripción— de cualquier otro rechazo sin tener que leer el texto.

    No es un error del request y no se arregla mandando otra cosa: es un estado de la cuenta,
    como `DelegationNotVerifiedError`. Por eso el mensaje siempre dice qué destraba el camino.
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


class SecretsNotConfiguredError(Exception):
    """El servidor no tiene `SECRET_ENCRYPTION_KEY`, así que no puede guardar secretos ajenos.

    Es una falta de configuración de la instalación y no un error del usuario, pero termina
    en un 503 con un texto que lo dice: el que aprieta "conectar" no puede hacer nada al
    respecto, y un 500 mudo lo dejaría reintentando para siempre.
    """


class SecretDecryptionError(Exception):
    """Hay un secreto guardado pero la clave actual no lo abre.

    Pasa cuando `SECRET_ENCRYPTION_KEY` cambió —se rotó, se perdió, se levantó otro entorno
    contra la misma base—. El dato no se recupera y no hace falta: el remedio es volver a
    pegar el token, que del otro lado se puede reemitir.
    """


class Balance360Error(Exception):
    """No se pudo registrar el comprobante en Balance360.

    Cubre las dos familias que para el usuario son lo mismo —la app no contestó, o contestó
    que no— porque en ninguna de las dos hay una factura registrada del otro lado. La
    diferencia entre "reintentá" y "arreglá esto en Balance360" viaja en `retryable`, no en
    el tipo: la decide el status HTTP y no hay una jerarquía que la refleje mejor.

    Nunca sube a la respuesta de `/emit`. La emisión ya ocurrió cuando esto puede fallar, y
    hacerla fallar por el registro convertiría un problema de la copia en un CAE huérfano.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class MercadoPagoError(Exception):
    """No se pudo hablar con Mercado Pago, o Mercado Pago contestó que no.

    Las dos familias juntas, igual que en `Balance360Error` y por el mismo motivo: para el que
    aprieta "Suscribirme" son lo mismo —no hay checkout— y la diferencia que importa viaja en
    `retryable`, que la decide el status HTTP.

    Dónde termina depende de quién la levantó, y son dos caminos muy distintos:

    - En el **checkout** y en la **baja** hay alguien esperando: sube como 502 con este texto.
      La baja es el caso delicado — si Mercado Pago no confirma la cancelación del
      `preapproval`, la fila local **no** se marca, porque una baja que solo existe de este
      lado deja al proveedor cobrando todos los meses una suscripción que la app da por
      terminada.
    - En el **webhook** no hay nadie esperando: sube como 502 a propósito, que es lo que hace
      que Mercado Pago reintente la notificación más tarde. Contestar 200 sobre un evento que
      no se pudo procesar lo pierde para siempre, y ese evento puede ser el cobro que activa
      una cuenta.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class WebhookSignatureError(Exception):
    """La notificación no viene firmada por Mercado Pago, o la firma no cierra.

    Es un 401 y no un 400: lo que falta es la prueba de quién manda. El endpoint del webhook
    no tiene sesión —lo llama un servidor ajeno— así que esta firma es **toda** su
    autenticación, y del otro lado hay un endpoint que escribe `ACTIVE`. Sin este chequeo,
    cualquiera con la URL se hace Pro con un `curl`.
    """
