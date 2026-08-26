/**
 * Espejo de los schemas Pydantic del backend.
 *
 * Escritos a mano y no generados del OpenAPI. Generarlos sería más exacto, pero mete un paso
 * de build que hay que acordarse de correr y una dependencia más; con seis recursos, la copia
 * a mano se lee mejor y el `tsc` avisa igual cuando algo no cierra. Revisar esta decisión si
 * la superficie de la API crece bastante.
 *
 * Los enums fiscales van con los **códigos de ARCA** como valor, igual que en el backend: son
 * los números que viajan en el JSON, y traducirlos acá agregaría una tabla de conversión que
 * puede desincronizarse. El texto para la pantalla sale de `LABELS`.
 */

export const CondicionIva = {
  INSCRIPTO: 1,
  EXENTO: 4,
  FINAL: 6,
  MONOTRIBUTO: 13,
} as const
export type CondicionIva = (typeof CondicionIva)[keyof typeof CondicionIva]

export const CONDICION_IVA_LABELS: Record<CondicionIva, string> = {
  [CondicionIva.INSCRIPTO]: 'Responsable inscripto',
  [CondicionIva.EXENTO]: 'Exento',
  [CondicionIva.FINAL]: 'Consumidor final',
  [CondicionIva.MONOTRIBUTO]: 'Monotributo',
}

export const DocType = {
  CUIT: 80,
  CUIL: 86,
  DNI: 96,
} as const
export type DocType = (typeof DocType)[keyof typeof DocType]

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  [DocType.CUIT]: 'CUIT',
  [DocType.CUIL]: 'CUIL',
  [DocType.DNI]: 'DNI',
}

/**
 * Lo que devuelven `/auth/login` y `/auth/me`. Son **dos campos y nada más**, igual que el
 * `UserRead` del backend: declarar acá campos que el JSON no trae los tipa como presentes y
 * el error aparece recién en runtime, como un `undefined` en la pantalla.
 */
export interface User {
  id: string
  email: string
}

/** El cuerpo de los endpoints que solo confirman algo: `MessageResponse` del backend. */
export interface MessageResponse {
  detail: string
}

export interface FiscalIdentity {
  id: string
  name: string
  condicion_iva: CondicionIva
  tax_id: string
  address: string | null
  iibb: string | null
  start_date: string | null
  /** Cuándo ARCA confirmó la delegación por última vez. `null` = nunca se verificó. */
  delegation_verified_at: string | null
  created_at: string
  updated_at: string
}

export interface FiscalIdentityCreate {
  name: string
  condicion_iva: CondicionIva
  tax_id: string
  address?: string | null
  iibb?: string | null
  start_date?: string | null
}

export interface DelegationStatus {
  granted: boolean
  message: string | null
  delegation_verified_at: string | null
  /** El CUIT de FactuMov, el que hay que autorizar en ARCA. Solo viene cuando `!granted`. */
  delegate_tax_id: string | null
}

export interface Customer {
  id: string
  name: string
  condicion_iva: CondicionIva
  doc_type: DocType
  doc_number: string
  address: string | null
  email: string | null
  created_at: string
  updated_at: string
}

export interface CustomerCreate {
  name: string
  condicion_iva: CondicionIva
  doc_type: DocType
  doc_number: string
  address?: string | null
  email?: string | null
}

/** Lo que el padrón de ARCA sabe de un CUIT. Es una propuesta: el backend no guardó nada. */
export interface TaxpayerLookup {
  doc_type: DocType
  doc_number: string
  name: string
  condicion_iva: CondicionIva
  address: string | null
  active: boolean
}

/* --- Modelos de factura ------------------------------------------------------------- */

export const VoucherType = {
  A: 'A',
  B: 'B',
  C: 'C',
  NCA: 'NCA',
  NCB: 'NCB',
  NCC: 'NCC',
} as const
export type VoucherType = (typeof VoucherType)[keyof typeof VoucherType]

export const VOUCHER_TYPE_LABELS: Record<VoucherType, string> = {
  [VoucherType.A]: 'Factura A',
  [VoucherType.B]: 'Factura B',
  [VoucherType.C]: 'Factura C',
  [VoucherType.NCA]: 'Nota de crédito A',
  [VoucherType.NCB]: 'Nota de crédito B',
  [VoucherType.NCC]: 'Nota de crédito C',
}

export const Concepto = {
  products: 'products',
  services: 'services',
  both: 'both',
} as const
export type Concepto = (typeof Concepto)[keyof typeof Concepto]

export const CONCEPTO_LABELS: Record<Concepto, string> = {
  [Concepto.products]: 'Productos',
  [Concepto.services]: 'Servicios',
  [Concepto.both]: 'Productos y servicios',
}

/**
 * El valor es el **código de ARCA**, igual que en el backend; la alícuota de verdad está en
 * `IVA_ALIQUOT_RATES`. Que el código no sea el porcentaje es de ARCA, no nuestro: el 5 es 21%.
 */
export const IvaAliquot = {
  exempt: 3,
  reduced: 4,
  standard: 5,
  higher: 6,
} as const
export type IvaAliquot = (typeof IvaAliquot)[keyof typeof IvaAliquot]

export const IVA_ALIQUOT_LABELS: Record<IvaAliquot, string> = {
  [IvaAliquot.exempt]: '0%',
  [IvaAliquot.reduced]: '10,5%',
  [IvaAliquot.standard]: '21%',
  [IvaAliquot.higher]: '27%',
}

export const IVA_ALIQUOT_RATES: Record<IvaAliquot, number> = {
  [IvaAliquot.exempt]: 0,
  [IvaAliquot.reduced]: 10.5,
  [IvaAliquot.standard]: 21,
  [IvaAliquot.higher]: 27,
}

/**
 * `quantity` y `unit_price` son **strings**, no números: Pydantic serializa `Decimal` como
 * string para no perder la escala (`"1.00"`, no `1.0`). Tiparlos como `number` acá los
 * rompería en silencio en el primer importe con centavos.
 */
export interface InvoiceTemplateLine {
  id: string
  position: number
  description: string
  quantity: string
  unit_price: string
  iva_aliquot: IvaAliquot
  created_at: string
  updated_at: string
}

export interface InvoiceTemplateLineCreate {
  description: string
  quantity: string
  unit_price: string
  iva_aliquot: IvaAliquot
}

export interface InvoiceTemplate {
  id: string
  name: string
  fiscal_identity_id: string
  customer_id: string
  voucher_type: VoucherType
  pos: number
  concepto: Concepto
  created_at: string
  updated_at: string
  lines: InvoiceTemplateLine[]
}

export interface InvoiceTemplateCreate {
  name: string
  fiscal_identity_id: string
  customer_id: string
  voucher_type: VoucherType
  pos: number
  concepto: Concepto
  lines: InvoiceTemplateLineCreate[]
}

/* --- Importación de PDF ------------------------------------------------------------- */

export interface CustomerDraft {
  name: string | null
  condicion_iva: CondicionIva | null
  doc_type: DocType | null
  doc_number: string | null
  address: string | null
}

export interface InvoiceTemplateLineDraft {
  description: string | null
  quantity: string | null
  unit_price: string | null
  iva_aliquot: IvaAliquot | null
}

/**
 * Lo que devuelve `POST /invoice-templates/import`. Es una **propuesta**: el backend leyó el
 * PDF y no guardó nada. Casi todo es opcional porque un PDF ilegible contesta 200 con todo en
 * `null` en vez de tirar error, y la pantalla ofrece carga manual.
 */
export interface InvoiceTemplateDraft {
  name: string | null
  fiscal_identity_id: string | null
  issuer_tax_id: string | null
  customer_id: string | null
  customer: CustomerDraft
  voucher_type: VoucherType | null
  pos: number | null
  concepto: Concepto
  lines: InvoiceTemplateLineDraft[]
}
