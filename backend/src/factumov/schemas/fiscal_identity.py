import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from factumov.enums import CondicionIva


class FiscalIdentityCreate(BaseModel):
    name: str = Field(max_length=150)
    condicion_iva: CondicionIva
    tax_id: str = Field(max_length=11)
    address: str | None = Field(default=None, max_length=200)
    iibb: str | None = Field(default=None, max_length=50)
    start_date: date | None = None

    @field_validator("tax_id")
    @classmethod
    def check_tax_id(cls, value: str) -> str:
        if not (value.isdigit() and len(value) == 11):
            raise ValueError("El CUIT debe tener 11 digitos")
        return value

    @field_validator("condicion_iva")
    @classmethod
    def check_condicion_iva(cls, value: CondicionIva) -> CondicionIva:
        if value == CondicionIva.FINAL:
            raise ValueError("Condicion IVA final no puede emitir comprobantes")
        return value


class FiscalIdentityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    condicion_iva: CondicionIva
    tax_id: str
    address: str | None
    iibb: str | None
    start_date: date | None
    # Sale en el Read porque la UI tiene que poder decidir si muestra el botón "emitir" o el
    # cartel de "todavía falta delegar". No entra por ningún schema de escritura: lo escribe
    # la verificación contra ARCA, no el cliente.
    delegation_verified_at: datetime | None
    # Cuándo el usuario dijo "ya delegué" con ARCA todavía diciendo que no. Es lo que le
    # permite a la pantalla tener tres estados en vez de dos, que es la diferencia entre
    # decirle "andá a delegar" a alguien que ya delegó y decirle que espere.
    delegation_claimed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FiscalIdentityLookup(BaseModel):
    """Lo que el padrón de ARCA sabe de un CUIT, para prellenar el alta de una identidad fiscal.

    Es una **propuesta**, no un recurso: el endpoint que la devuelve no escribe nada. Mismo
    criterio que `TaxpayerLookup` y que el `InvoiceTemplateDraft` de la importación de PDF.

    Los campos coinciden con `FiscalIdentityCreate` a propósito —la pantalla usa esto para
    sembrar el formulario— con dos ausencias que no son olvidos:

    - **`iibb` no está porque ARCA no lo tiene.** Ingresos Brutos es provincial: lo administran
      Rentas de cada provincia y ARBA/AGIP, no el padrón nacional. Inventarlo acá sería poner
      un número plausible en un campo que se imprime en el comprobante.
    - **`start_date` tampoco.** La fecha de inicio de actividades no viene como tal en la
      respuesta del A5; lo más parecido son los períodos de cada actividad, que dicen desde
      cuándo está registrada *esa* actividad y no desde cuándo el contribuyente opera.
      Deducirla de ahí daría una fecha creíble y equivocada, impresa en un comprobante fiscal.
    """

    tax_id: str
    name: str
    # `None` cuando el padrón no muestra al CUIT ni inscripto en IVA, ni exento, ni
    # monotributista — o sea, cuando `padron` lo deduce como consumidor final.
    #
    # Consumidor final **no es una condición que un emisor pueda tener**: `FiscalIdentityCreate`
    # la rechaza con 422 y el desplegable de la pantalla ni la ofrece. Devolverla igual sería
    # proponer un valor que el guardado va a rechazar, y la pantalla tendría que aprender a
    # descartarlo. Vuelve vacío y el usuario elige, que es lo único honesto que se puede hacer
    # con un CUIT que el padrón no muestra como emisor.
    condicion_iva: CondicionIva | None = None
    address: str | None = None
    # "ACTIVO" en el padrón. Un CUIT con la clave inactiva se puede cargar igual —no es motivo
    # para negarse— pero la pantalla lo avisa: no va a poder emitir.
    active: bool


class FiscalIdentityUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    condicion_iva: CondicionIva | None = None
    tax_id: str | None = Field(default=None, max_length=11)
    address: str | None = Field(default=None, max_length=200)
    iibb: str | None = Field(default=None, max_length=50)
    start_date: date | None = None

    @field_validator("tax_id")
    @classmethod
    def check_tax_id(cls, value: str | None) -> str | None:
        if value is not None:
            if not (value.isdigit() and len(value) == 11):
                raise ValueError("El CUIT debe tener 11 digitos")
        return value

    @field_validator("condicion_iva")
    @classmethod
    def check_condicion_iva(cls, value: CondicionIva | None) -> CondicionIva | None:
        if value is not None:
            if value == CondicionIva.FINAL:
                raise ValueError("Condicion IVA final no puede emitir comprobantes")
        return value


class DelegationStatus(BaseModel):
    """La respuesta de los dos endpoints de delegación: `verify-delegation` y `claim-delegation`.

    Sale con 200 tanto si la delegación está como si no: preguntar y que te contesten "no
    todavía" no es un error del cliente. El 4xx quedaría reservado para un pedido mal hecho,
    y esto está bien hecho — la respuesta simplemente es negativa.

    Los dos endpoints devuelven lo mismo porque los dos contestan la misma pregunta; lo que
    cambia es qué escriben cuando la respuesta es que no.
    """

    granted: bool
    # `None` cuando `granted`. Cuando no, es el texto con el que ARCA lo explicó, que sirve
    # de guía al usuario y de pista al soporte.
    message: str | None = None
    # Los dos valores que quedaron en la fila. Ahorran un GET para refrescar la pantalla.
    delegation_verified_at: datetime | None = None
    delegation_claimed_at: datetime | None = None
    # El CUIT al que hay que autorizar en ARCA — el del certificado de FactuMov. Va solo en la
    # respuesta negativa, que es la única donde hay una instrucción que dar: cuando la
    # delegación ya está, repetir a quién había que autorizar no le sirve a la pantalla.
    delegate_tax_id: str | None = None
