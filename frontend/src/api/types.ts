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

/**
 * Los valores son los códigos de `CondicionIVAReceptorId` de ARCA, verificados contra
 * `FEParamGetCondicionIvaReceptor` el 2026-08-27. Antes `FINAL` era 6 y `MONOTRIBUTO` 13, los
 * dos mal: para ARCA el 6 es "Responsable Monotributo" y el 13 es "Monotributista Social".
 */
export const CondicionIva = {
  INSCRIPTO: 1,
  EXENTO: 4,
  FINAL: 5,
  MONOTRIBUTO: 6,
} as const
export type CondicionIva = (typeof CondicionIva)[keyof typeof CondicionIva]

export const CONDICION_IVA_LABELS: Record<CondicionIva, string> = {
  [CondicionIva.INSCRIPTO]: 'Responsable inscripto',
  [CondicionIva.EXENTO]: 'Exento',
  [CondicionIva.FINAL]: 'Consumidor final',
  [CondicionIva.MONOTRIBUTO]: 'Monotributo',
}

/**
 * Las condiciones que puede tener quien **emite**.
 *
 * Consumidor final no está: no puede emitir y `FiscalIdentityCreate` la rechaza con un 422, así
 * que no se ofrece una opción que siempre falla. Vive acá y no en una pantalla porque hay dos
 * lugares que dan de alta una identidad fiscal —`FiscalIdentityPage` y el cartel del emisor
 * faltante de la importación—, y con una copia en cada uno alcanzaba con tocar una para que
 * dejaran de coincidir.
 */
export const EMISOR_CONDICIONES = [
  CondicionIva.INSCRIPTO,
  CondicionIva.MONOTRIBUTO,
  CondicionIva.EXENTO,
] as const

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
 * ¿Se le puede preguntar al padrón por este documento?
 *
 * **El padrón se consulta por CUIT y solo devuelve CUIT.** Con un DNI no hay nada que traer, y
 * el CUIL —que también son once dígitos— queda afuera porque `TaxpayerLookup` contesta siempre
 * `doc_type: CUIT`: aceptarlo daría de alta un cliente con el tipo de documento cambiado.
 *
 * Es la regla de tres pantallas —el alta de un cliente, y los dos carteles de la importación—,
 * así que vive con los tipos de la API y no adentro de una de ellas. Espera los dígitos
 * pelados: los guiones se limpian antes, donde el usuario tipea.
 */
export function isCuit(docType: DocType | null, docNumber: string | null): docNumber is string {
  return docType === DocType.CUIT && docNumber !== null && /^\d{11}$/.test(docNumber)
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
  /**
   * Cuándo el usuario dijo «ya delegué» con ARCA todavía diciendo que no. `null` = no avisó.
   *
   * Delegar tiene dos partes y la segunda es de FactuMov: el contribuyente designa, y después
   * hay que aceptar esa designación a mano en ARCA. WSFE contesta lo mismo en los dos casos,
   * así que este campo es lo único que distingue «no delegó» de «está esperándonos».
   */
  delegation_claimed_at: string | null
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

/**
 * Lo que el padrón de ARCA sabe de un CUIT, para sembrar el alta de una identidad fiscal.
 *
 * Es una propuesta: el backend no guardó nada. `iibb` y `start_date` no vienen —Ingresos
 * Brutos es provincial y ARCA no lo tiene, y la fecha de inicio de actividades no está como
 * tal en la respuesta— así que esos dos siguen siendo del usuario.
 */
export interface FiscalIdentityLookup {
  tax_id: string
  name: string
  /**
   * `null` cuando el padrón no muestra al CUIT ni inscripto, ni exento, ni monotributista.
   *
   * Consumidor final no es una condición que un emisor pueda tener: el backend la rechaza con
   * 422 y el desplegable ni la ofrece, así que en vez de proponer un valor imposible viene
   * vacío y lo elige el usuario.
   */
  condicion_iva: CondicionIva | null
  address: string | null
  active: boolean
}

export interface DelegationStatus {
  granted: boolean
  message: string | null
  delegation_verified_at: string | null
  delegation_claimed_at: string | null
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

/**
 * La letra que corresponde entre dos condiciones frente al IVA — espejo de
 * `services/voucher.py`.
 *
 * **La letra no se elige: se deduce.** La decide ARCA a partir de quién le factura a quién, y
 * sacadas las notas de crédito —que FactuMov no ofrece— la combinación determina exactamente
 * una. El backend hace la misma cuenta y es el que manda; acá se repite porque el editor tiene
 * que mostrar la letra y calcular el total **mientras** el usuario cambia de cliente, o sea
 * antes de que exista nada que guardar. Es la misma copia a mano que el resto de este archivo.
 *
 * `undefined` es "esa combinación no emite nada", que hoy solo pasa con un emisor consumidor
 * final — imposible de elegir, porque no está en el desplegable de identidad fiscal.
 */
export function voucherTypeFor(
  issuer: CondicionIva,
  customer: CondicionIva,
): VoucherType | undefined {
  if (issuer === CondicionIva.FINAL) return undefined
  // Solo el inscripto puede emitir A o B. El monotributista y el exento emiten C contra
  // cualquiera.
  if (issuer !== CondicionIva.INSCRIPTO) return VoucherType.C
  // La A la recibe el inscripto **y el monotributista**: desde la Ley 27.618 el inscripto que
  // le factura a un monotributista emite A. ARCA rechaza la B en ese par con el código 10243.
  return customer === CondicionIva.INSCRIPTO || customer === CondicionIva.MONOTRIBUTO
    ? VoucherType.A
    : VoucherType.B
}

export const Concepto = {
  products: 'products',
  services: 'services',
  both: 'both',
} as const
export type Concepto = (typeof Concepto)[keyof typeof Concepto]

/**
 * Espejo de `Concepto.needs_service_dates` del backend: período y vencimiento los pide ARCA
 * para todo lo que no sea solo productos, "productos y servicios" incluido.
 *
 * Está acá y no calculado en cada pantalla porque el `preview` de emisión ya trae la respuesta
 * del servidor (`needs_service_dates`) y este es el mismo criterio para las pantallas que
 * todavía no lo pidieron — el comando hablado tiene que decidir con lo que hay en la grilla.
 */
export function needsServiceDates(concepto: Concepto): boolean {
  return concepto !== Concepto.products
}

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
  // Sin `voucher_type`: el backend la deduce de las dos condiciones frente al IVA. Mandarla
  // sería decirle al servidor algo que él sabe mejor — y que puede cambiar después.
  pos: number
  concepto: Concepto
  lines: InvoiceTemplateLineCreate[]
}

/* --- Facturas emitidas -------------------------------------------------------------- */

/**
 * Una línea de una factura ya emitida. Misma forma que `InvoiceTemplateLine` y sin `Create`:
 * las líneas de una factura no se escriben desde afuera, salen de copiar las del modelo.
 */
export interface InvoiceLine {
  id: string
  position: number
  description: string
  quantity: string
  unit_price: string
  iva_aliquot: IvaAliquot
}

/**
 * Una factura emitida. **Nada de esto es editable**: es lo que ARCA autorizó.
 *
 * El emisor y el receptor vienen **copiados** y no como ids a resolver. No es redundancia:
 * es lo que se emitió, aunque el cliente haya cambiado de domicilio al día siguiente. Los
 * importes vienen guardados por lo mismo — el CAE cubre esos números.
 */
export interface Invoice {
  id: string
  fiscal_identity_id: string
  customer_id: string
  template_id: string | null

  voucher_type: VoucherType
  pos: number
  number: number
  /** `B-00001-00000042`. Lo arma el backend para que la grilla, el PDF y el mail no tengan
   *  tres versiones del mismo formato. */
  label: string
  date: string
  concepto: Concepto
  from_date: string | null
  to_date: string | null
  due_date: string | null

  cae: string
  cae_expiry: string

  net_total: string
  iva_total: string
  total: string

  issuer_name: string
  issuer_tax_id: string
  issuer_condicion_iva: CondicionIva
  issuer_address: string | null
  issuer_iibb: string | null
  issuer_start_date: string | null

  customer_name: string
  customer_doc_type: DocType
  customer_doc_number: string
  customer_condicion_iva: CondicionIva
  customer_address: string | null
  /**
   * El mail que el cliente tiene **ahora**, no una copia hecha al emitir.
   *
   * Es la única excepción a que los `customer_*` estén congelados, y es deliberada: el mail
   * no se imprime ni viaja a ARCA, es a dónde entregar el PDF — una pregunta sobre hoy.
   * Copiado, una factura emitida antes de que el cliente tuviera dirección se quedaba sin
   * dirección para siempre.
   */
  customer_email: string | null
  /**
   * Cuándo salió el mail con el PDF, la última vez. `null` = todavía no se mandó.
   *
   * No es acuse de recibo: dice que el servidor de mail lo aceptó, no que el cliente lo haya
   * abierto. Reenviar lo pisa.
   */
  sent_at: string | null
  /** A qué dirección salió ese último envío. `null` = todavía no se mandó. */
  sent_to: string | null

  created_at: string
  updated_at: string

  lines: InvoiceLine[]
}

/**
 * Qué comprobante saldría si se emitiera el modelo ahora. **No emite nada.**
 *
 * Los importes los calcula el backend con la misma función que después se los manda a ARCA.
 * El editor sabe hacer esa cuenta y la muestra mientras se tipea, pero en la pantalla de
 * confirmación el número deja de ser una estimación: es lo que se va a declarar, y tiene que
 * salir de una sola fuente.
 */
export interface InvoicePreview {
  voucher_type: VoucherType
  pos: number
  issuer_name: string
  issuer_tax_id: string
  customer_name: string
  customer_doc_number: string
  customer_email: string | null
  net_total: string
  iva_total: string
  total: string
  needs_service_dates: boolean
  /** La fecha propuesta para el comprobante: hoy. */
  date: string
  /**
   * Los extremos que ARCA acepta — ±5 días para productos, ±10 para servicios.
   *
   * Los calcula el backend con la misma función que después valida la emisión. Calcularlos
   * acá dejaría al campo ofrecer una fecha que el servidor rechaza, y el borde de la ventana
   * es exactamente donde eso pasaría.
   */
  min_date: string
  max_date: string
  /** `null` cuando se puede emitir. Cuando no, por qué — dicho antes de apretar el botón. */
  blocked_reason: string | null
}

/**
 * Lo poco que el usuario decide al emitir.
 *
 * `date` es la del comprobante y su default —cuando no se manda— es hoy. Hay un tercer límite
 * que el preview no puede saber: ARCA no acepta que la numeración de un punto de venta
 * retroceda en el tiempo, así que una fecha anterior a la del último comprobante de esa serie
 * vuelve como un 422 con la fecha mínima escrita en el mensaje.
 */
export interface EmitRequest {
  date?: string
  from_date?: string
  to_date?: string
  due_date?: string
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
  pos: number | null
  concepto: Concepto
  lines: InvoiceTemplateLineDraft[]
}
