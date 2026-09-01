/**
 * La forma del formulario de un modelo, y las cuentas y conversiones que van con ella.
 *
 * Está separado de `TemplateEditor.tsx` por Fast Refresh: solo recarga en caliente un módulo
 * que exporta componentes y nada más, y con estas funciones adentro cada cambio en el editor
 * recargaba la página entera y se perdía el formulario que uno estaba probando. Es el mismo
 * motivo por el que el contexto de sesión vive en tres archivos.
 */

import {
  Concepto,
  IVA_ALIQUOT_RATES,
  IvaAliquot,
  VoucherType,
  voucherTypeFor,
  type Customer,
  type FiscalIdentity,
  type InvoiceTemplateCreate,
} from '../api/types'

/**
 * Una línea del formulario. `key` no es el id de la base: las líneas nuevas todavía no tienen
 * uno, y React necesita una clave estable igual. Usar el índice del array haría que borrar la
 * primera línea le pase su estado a la segunda.
 */
export interface LineForm {
  key: string
  description: string
  quantity: string
  /**
   * El precio unitario **tal como lo tipeó el usuario**, que puede ser el de la columna sin
   * IVA o el de la columna con IVA — lo dice `price_includes_iva`. El otro no vive en el
   * estado: se calcula al dibujar (`unitPriceFields`) y se recalcula solo cuando cambia la
   * alícuota o la letra.
   *
   * Guardar los dos sería guardar dos veces el mismo dato, con la garantía de que en algún
   * render van a discrepar: cada tecla en una de las cajas tendría que reescribir la otra, y
   * el redondeo a centavos del derivado haría que reabrir el modelo y no tocar nada moviera
   * el precio original. Guardando cuál es el que vale, el otro es siempre una cuenta.
   */
  unit_price: string
  /** En cuál de las dos columnas se cargó `unit_price`. La otra es la calculada. */
  price_includes_iva: boolean
  iva_aliquot: IvaAliquot
}

/**
 * El estado del formulario. Casi todo es `string` aunque la API espere números: un input
 * numérico vacío no es cero, y forzarlo a `number` mientras el usuario tipea le borra el campo
 * cuando escribe "1," o deja el precio a medio escribir. La conversión ocurre una sola vez, en
 * `toPayload`.
 */
export interface TemplateForm {
  name: string
  fiscal_identity_id: string | null
  customer_id: string | null
  pos: string
  concepto: Concepto
  lines: LineForm[]
}

let keySeed = 0

export function newLine(partial: Partial<Omit<LineForm, 'key'>> = {}): LineForm {
  keySeed += 1
  return {
    key: `line-${keySeed}`,
    description: '',
    quantity: '1',
    unit_price: '',
    // Sin IVA por default, que es la columna que va primero en la pantalla. Con el precio
    // vacío las dos cajas se ven igual, así que esto solo decide dónde cae lo que se tipee
    // primero — y lo cambia el propio usuario con solo escribir en la otra.
    price_includes_iva: false,
    iva_aliquot: IvaAliquot.standard,
    ...partial,
  }
}

export function emptyForm(): TemplateForm {
  return {
    name: '',
    fiscal_identity_id: null,
    customer_id: null,
    // Vacío y no `'1'`. Un default plausible es peor que ninguno acá: el punto de venta lo da
    // de alta el usuario en ARCA, así que `'1'` acertaba solo por casualidad y, al parecer un
    // valor ya elegido, hacía que ni se lo mirara. Vacío, el campo se completa solo cuando ARCA
    // informa uno solo, y cuando hay varios obliga a elegir — ver `PointOfSaleField`.
    pos: '',
    concepto: Concepto.products,
    lines: [newLine()],
  }
}

/**
 * Texto → número, aceptando las dos formas en que se escribe un importe en la Argentina.
 *
 * Si hay coma, la coma es el separador decimal y los puntos son de miles (`1.234,56`). Si no
 * hay coma, se lee tal cual (`1234.56`), que es lo que llega del backend. Sin esto, un usuario
 * que tipea `1.234,56` manda `NaN` y el total muestra cualquier cosa.
 */
export function parseAmount(text: string): number {
  const clean = text.replace(/\s/g, '')
  const normalised = clean.includes(',') ? clean.replace(/\./g, '').replace(',', '.') : clean
  const value = Number(normalised)
  return Number.isFinite(value) ? value : 0
}

/**
 * Lo que viene del backend, listo para meter en un input.
 *
 * `Decimal` viaja como string con la escala de la columna: la cantidad llega `"1.0000"` y el
 * precio `"35000.00"`. Mostrarlo así no está mal, pero es lo que el usuario tiene que borrar a
 * mano cada vez que corrige una cantidad.
 */
export function fromDecimal(text: string): string {
  if (!text.includes('.')) return text
  return text.replace(/0+$/, '').replace(/\.$/, '')
}

/** La misma normalización que `parseAmount`, pero devolviendo el string que Pydantic sabe leer
 *  como `Decimal`. Se manda el texto y no un `number` para no pasar por el binario de coma
 *  flotante en el camino de ida. */
function toDecimalString(text: string): string {
  const clean = text.replace(/\s/g, '')
  return clean.includes(',') ? clean.replace(/\./g, '').replace(',', '.') : clean
}

/**
 * **En A el precio se guarda neto; en B y C se guarda con el IVA adentro.**
 *
 * No es una decisión de esta pantalla: es la convención del proyecto, la misma que usa el
 * parser al leer un PDF (lo confirma el "IVA Contenido" del Régimen de Transparencia Fiscal en
 * las B, y el 35000 × 1,21 = 42350 de la muestra A) y la misma que aplica `invoice_totals.py`
 * al pedir el CAE. La columna `unit_price` guarda un solo número y la letra decide cómo leerlo.
 *
 * Lo que **no** decide es cómo se carga: en la pantalla el precio se puede escribir en
 * cualquiera de las dos columnas —sin IVA o con IVA— y esta tabla es la que traduce lo que se
 * escribió a lo que corresponde guardar. Ver `unitPriceFields`.
 */
const PRICE_INCLUDES_IVA: Record<VoucherType, boolean> = {
  [VoucherType.A]: false,
  [VoucherType.NCA]: false,
  [VoucherType.B]: true,
  [VoucherType.NCB]: true,
  [VoucherType.C]: true,
  [VoucherType.NCC]: true,
}

/**
 * En qué columna de la pantalla cae un precio que ya está guardado con esa letra.
 *
 * Es `PRICE_INCLUDES_IVA` con la puerta abierta a `undefined`, que es lo que llega cuando el
 * parser no pudo leer la letra del PDF importado. En ese caso se asume que el precio trae el
 * IVA adentro: es lo que vale en B y en C, tres de las cuatro combinaciones, y además es lo
 * que el usuario ve escrito en el comprobante que está importando.
 */
export function priceIncludesIva(voucherType: VoucherType | undefined): boolean {
  return voucherType === undefined ? true : PRICE_INCLUDES_IVA[voucherType]
}

/**
 * ¿Hay IVA en juego? Espejo de `VoucherType.applies_iva` del backend.
 *
 * En la C no: la emite un monotributista o un exento, que no liquidan IVA, y ARCA recibe
 * `ImpNeto == ImpTotal` con `ImpIVA = 0` sin importar qué alícuota tenga cargada la línea. Acá
 * decide dos cosas: que el total de la pantalla no invente un IVA que no se va a declarar —lo
 * inventaba hasta ahora, y era la única cuenta de esta pantalla que no cerraba contra la
 * factura emitida— y que las dos columnas de precio muestren el mismo número, porque en una C
 * lo son.
 */
const APPLIES_IVA: Record<VoucherType, boolean> = {
  [VoucherType.A]: true,
  [VoucherType.NCA]: true,
  [VoucherType.B]: true,
  [VoucherType.NCB]: true,
  [VoucherType.C]: false,
  [VoucherType.NCC]: false,
}

/**
 * La letra que sale con el emisor y el cliente que tiene elegidos el formulario.
 *
 * **La letra no se elige: se deduce**, y por eso no es un campo de `TemplateForm`. La cuenta
 * vive acá y no adentro del editor porque las tres cosas que dependen de ella —lo que se
 * muestra, lo que se valida y lo que se guarda— tienen que usar exactamente la misma, y dos de
 * ellas ocurren en las pantallas, fuera del editor.
 *
 * `undefined` es "todavía no se puede saber": falta elegir alguna de las dos puntas, o las
 * listas no llegaron. No es un caso benigno a la hora de guardar — ver `validate`.
 */
export function formVoucherType(
  form: TemplateForm,
  fiscalIdentities: FiscalIdentity[],
  customers: Customer[],
): VoucherType | undefined {
  const issuer = fiscalIdentities.find((identity) => identity.id === form.fiscal_identity_id)
  const customer = customers.find((option) => option.id === form.customer_id)
  return issuer && customer
    ? voucherTypeFor(issuer.condicion_iva, customer.condicion_iva)
    : undefined
}

/**
 * Redondeo a centavos **línea por línea**, como hace `invoice_totals.py`.
 *
 * No es cosmético: ARCA valida que el total cierre contra el neto y el IVA con dos decimales
 * exactos, así que el importe que se emite es el de los redondeados. Sumar en alta precisión y
 * redondear al final muestra un total de un centavo distinto del que sale autorizado. Contra
 * el `Decimal` del backend puede haber diferencias en un empate exacto; el número que vale es
 * el de allá, y el renglón debajo de los totales ya lo dice.
 */
function cents(value: number): number {
  return Number(value.toFixed(2))
}

/**
 * La alícuota que corre para esta línea, en tanto por uno.
 *
 * Cero cuando la letra no aplica IVA: en una C la alícuota cargada no se declara, así que
 * tampoco puede separar los dos precios de la pantalla.
 */
function rateOf(line: LineForm, voucherType: VoucherType | undefined): number {
  if (voucherType !== undefined && !APPLIES_IVA[voucherType]) return 0
  return IVA_ALIQUOT_RATES[line.iva_aliquot] / 100
}

/** El precio de la columna que el usuario **no** cargó. `''` mientras no cargó ninguna. */
function otherUnitPrice(line: LineForm, voucherType: VoucherType | undefined): string {
  if (line.unit_price.trim() === '') return ''
  const typed = parseAmount(line.unit_price)
  const rate = rateOf(line, voucherType)
  const other = line.price_includes_iva ? typed / (1 + rate) : typed * (1 + rate)
  // A dos decimales porque es un precio y porque es el que puede terminar guardándose: la
  // columna de la base tiene escala 2.
  return fromDecimal(other.toFixed(2))
}

/**
 * Las dos cajas de precio de una línea: sin IVA y con IVA.
 *
 * **Se carga cualquiera de las dos y la otra sale calculada.** El estado guarda una sola —la
 * que se tipeó— así que acá se decide cuál se muestra tal cual y cuál es la cuenta. Escribir en
 * la otra caja no pisa nada: cambia cuál es la que manda (`price_includes_iva`), y la primera
 * pasa a ser la calculada.
 *
 * Por qué dos columnas y no una: cuál hay que guardar depende de la letra —neto en A, con IVA
 * en B y C— pero el que carga un precio no piensa en la letra, piensa en el precio que tiene.
 * Con una sola caja el mismo modelo cambiaba de importe al cambiar de cliente: el número
 * quedaba igual y lo que cambiaba era cómo se lo lee, así que pasar de un cliente inscripto a
 * un consumidor final movía el total un 21% sin que nadie tocara el precio. Cargando el precio
 * que uno sabe, el importe emitido es el mismo con cualquier letra.
 */
export function unitPriceFields(
  line: LineForm,
  voucherType: VoucherType | undefined,
): { net: string; gross: string } {
  const other = otherUnitPrice(line, voucherType)
  return line.price_includes_iva
    ? { net: other, gross: line.unit_price }
    : { net: line.unit_price, gross: other }
}

/**
 * El precio que va a la base: el de la convención de la letra.
 *
 * Cuando la columna cargada ya es la que se guarda, se manda el texto **tal cual** en vez de
 * pasarlo por la cuenta de ida y vuelta. No es una optimización: `35000` que se convierte a
 * `28925.62` y vuelve no siempre vuelve a `35000`, y reabrir un modelo y guardarlo sin tocar
 * nada no puede moverle el precio.
 *
 * En A, cargar el precio con IVA sí redondea: lo que se guarda es el neto con dos decimales,
 * que multiplicado por la alícuota puede dar un centavo menos que el precio con IVA tipeado.
 * Es propio de la A y no de esta pantalla —el total de una A lo arma ARCA sumando neto e IVA,
 * no al revés—, y por eso la columna con IVA es la que se recalcula.
 */
function storedUnitPrice(line: LineForm, voucherType: VoucherType | undefined): string {
  const includes = priceIncludesIva(voucherType)
  return includes === line.price_includes_iva
    ? toDecimalString(line.unit_price)
    : otherUnitPrice(line, voucherType)
}

/**
 * El importe de la línea **tal como se va a emitir**: cantidad por el precio que se guarda.
 *
 * O sea neto en una A y con el IVA adentro en una B o una C, que es lo que después leen los
 * totales de abajo. No es la cantidad por el precio tipeado, si se tipeó en la otra columna.
 */
export function lineAmount(line: LineForm, voucherType: VoucherType | undefined): number {
  return cents(parseAmount(line.quantity) * parseAmount(storedUnitPrice(line, voucherType)))
}

/**
 * Neto, IVA y total del comprobante — las mismas tres ramas que `compute_totals` del backend.
 *
 * La letra llega como parámetro y no sale del formulario, porque **no es un campo del
 * formulario**: se deduce de las condiciones frente al IVA del emisor y del receptor. Mientras
 * falte elegir alguna de las dos no hay letra, y ahí se asume que el precio guardado trae el
 * IVA adentro — es lo que vale en B y en C, o sea en tres de las cuatro combinaciones, y el
 * número se corrige solo en cuanto el usuario elige.
 */
export function totals(form: TemplateForm, voucherType: VoucherType | undefined) {
  const includesIva = priceIncludesIva(voucherType)
  const appliesIva = voucherType === undefined ? true : APPLIES_IVA[voucherType]
  let net = 0
  let iva = 0
  for (const line of form.lines) {
    const amount = lineAmount(line, voucherType)
    const rate = IVA_ALIQUOT_RATES[line.iva_aliquot] / 100
    if (!appliesIva) {
      // La C no discrimina nada: el importe es neto y el IVA es cero, tenga la línea la
      // alícuota que tenga. Es exactamente lo que se le manda a ARCA.
      net += amount
    } else if (includesIva) {
      const lineNet = cents(amount / (1 + rate))
      net += lineNet
      iva += amount - lineNet
    } else {
      net += amount
      iva += cents(amount * rate)
    }
  }
  return { net, iva, total: net + iva }
}

/**
 * El formulario → el body del POST/PATCH.
 *
 * La letra entra como parámetro porque **de ella depende qué precio se guarda**: el neto en
 * una A, el que tiene el IVA adentro en una B o una C. Es lo único que el payload no puede
 * sacar del formulario, y por eso es un parámetro y no una cuenta de acá adentro.
 */
export function toPayload(
  form: TemplateForm,
  voucherType: VoucherType | undefined,
): InvoiceTemplateCreate {
  if (form.fiscal_identity_id === null || form.customer_id === null) {
    throw new Error('Falta la identidad fiscal o el cliente')
  }
  // Sin letra no se guarda: sin ella no se sabe si el precio de la línea va neto o con el IVA
  // adentro, y elegir mal mueve el importe un 21% en silencio. `validate` lo corta antes con
  // un mensaje; esto es la red por si alguien llama sin validar.
  if (voucherType === undefined) {
    throw new Error('No se pudo determinar la letra del comprobante')
  }
  return {
    name: form.name.trim(),
    fiscal_identity_id: form.fiscal_identity_id,
    customer_id: form.customer_id,
    pos: Number(form.pos),
    concepto: form.concepto,
    // `position` no se manda: el orden del array **es** la posición, y el CRUD la asigna con
    // un `enumerate()`. Mandarla abriría la puerta a huecos, duplicados y negativos.
    lines: form.lines.map((line) => ({
      description: line.description.trim(),
      quantity: toDecimalString(line.quantity),
      unit_price: storedUnitPrice(line, voucherType),
      iva_aliquot: line.iva_aliquot,
    })),
  }
}

/**
 * Lo que impide mandar un request que ya sabemos que va a fallar.
 *
 * No reemplaza a la validación del backend —eso es del backend— pero un 422 de Pydantic dice
 * "body.lines.0.quantity: Input should be greater than 0", que no es un mensaje para nadie que
 * no haya escrito el schema.
 */
export function validate(
  form: TemplateForm,
  voucherType: VoucherType | undefined,
): string | undefined {
  if (form.name.trim() === '') return 'Poné un nombre para reconocer el modelo.'
  if (form.fiscal_identity_id === null) return 'Elegí desde qué identidad fiscal emitís.'
  if (form.customer_id === null) return 'Elegí a quién le facturás.'
  // La letra es la que dice si el precio se guarda neto o con IVA, así que sin ella no se
  // guarda. Con las dos puntas elegidas siempre sale una; queda `undefined` solo si las listas
  // no llegaron, que es un error de carga y no algo que el usuario pueda arreglar tocando el
  // formulario — de ahí que el mensaje mande a recargar.
  if (voucherType === undefined) {
    return 'No pudimos determinar la letra del comprobante. Recargá la pantalla y probá de nuevo.'
  }
  if (form.pos.trim() === '') return 'Elegí el punto de venta.'
  if (!Number.isInteger(Number(form.pos)) || Number(form.pos) < 1) {
    return 'El punto de venta es un número entero mayor a cero.'
  }
  if (form.lines.length === 0) return 'Un modelo necesita al menos una línea.'
  for (const [index, line] of form.lines.entries()) {
    const position = index + 1
    if (line.description.trim() === '') return `La línea ${position} no tiene descripción.`
    if (parseAmount(line.quantity) <= 0) {
      return `La cantidad de la línea ${position} tiene que ser mayor a cero.`
    }
    if (line.unit_price.trim() === '') return `Falta el precio de la línea ${position}.`
    if (parseAmount(line.unit_price) < 0) {
      return `El precio de la línea ${position} no puede ser negativo.`
    }
  }
  return undefined
}
