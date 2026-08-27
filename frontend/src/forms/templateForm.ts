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
  unit_price: string
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
    iva_aliquot: IvaAliquot.standard,
    ...partial,
  }
}

export function emptyForm(): TemplateForm {
  return {
    name: '',
    fiscal_identity_id: null,
    customer_id: null,
    pos: '1',
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
 * **En A el precio va neto; en B y C ya viene con el IVA adentro.**
 *
 * No es una decisión de esta pantalla: es la convención del proyecto, la misma que usa el
 * parser al leer un PDF (lo confirma el "IVA Contenido" del Régimen de Transparencia Fiscal en
 * las B, y el 35000 × 1,21 = 42350 de la muestra A). El precio se guarda tal como se carga y
 * la letra decide cómo interpretarlo.
 *
 * En C la alícuota es 0, así que la fórmula da lo mismo por los dos caminos.
 */
const PRICE_INCLUDES_IVA: Record<VoucherType, boolean> = {
  [VoucherType.A]: false,
  [VoucherType.NCA]: false,
  [VoucherType.B]: true,
  [VoucherType.NCB]: true,
  [VoucherType.C]: true,
  [VoucherType.NCC]: true,
}

export const money = new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS' })

/**
 * La letra llega como parámetro y no sale del formulario, porque **ya no es un campo del
 * formulario**: se deduce de las condiciones frente al IVA del emisor y del receptor, que son
 * dos filas de otras dos listas. Mientras falte elegir alguna de las dos no hay letra, y ahí se
 * asume que el precio trae el IVA adentro — es lo que vale en B y en C, o sea en tres de las
 * cuatro combinaciones, y el número se corrige solo en cuanto el usuario elige.
 */
export function totals(form: TemplateForm, voucherType: VoucherType | undefined) {
  const includesIva = voucherType === undefined ? true : PRICE_INCLUDES_IVA[voucherType]
  let net = 0
  let iva = 0
  for (const line of form.lines) {
    const amount = lineAmount(line)
    const rate = IVA_ALIQUOT_RATES[line.iva_aliquot] / 100
    if (includesIva) {
      const lineNet = amount / (1 + rate)
      net += lineNet
      iva += amount - lineNet
    } else {
      net += amount
      iva += amount * rate
    }
  }
  return { net, iva, total: net + iva }
}

/** El importe de una línea *tal como se carga*: sin decidir si el IVA está adentro o afuera. */
export function lineAmount(line: LineForm): number {
  return parseAmount(line.quantity) * parseAmount(line.unit_price)
}

export function toPayload(form: TemplateForm): InvoiceTemplateCreate {
  if (form.fiscal_identity_id === null || form.customer_id === null) {
    throw new Error('Falta la identidad fiscal o el cliente')
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
      unit_price: toDecimalString(line.unit_price),
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
export function validate(form: TemplateForm): string | undefined {
  if (form.name.trim() === '') return 'Poné un nombre para reconocer el modelo.'
  if (form.fiscal_identity_id === null) return 'Elegí desde qué identidad fiscal emitís.'
  if (form.customer_id === null) return 'Elegí a quién le facturás.'
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
