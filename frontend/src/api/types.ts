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
