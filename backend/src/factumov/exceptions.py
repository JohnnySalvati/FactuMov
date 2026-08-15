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


class UnknownReferenceError(Exception):
    pass


class UnknownCustomerError(UnknownReferenceError):
    pass


class UnknownFiscalIdentityError(UnknownReferenceError):
    pass
