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
