import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  CONDICION_IVA_LABELS,
  CondicionIva,
  EMISOR_CONDICIONES,
  isCuit,
  type Customer,
  type CustomerCreate,
  type CustomerDraft,
  type FiscalIdentity,
  type FiscalIdentityLookup,
  type TaxpayerLookup,
} from '../api/types'
import { Notice } from './Notice'

/**
 * Las dos partes del comprobante que el PDF nombra y la cuenta todavía no tiene: el CUIT que
 * lo emitió y el cliente que lo recibió.
 *
 * **Antes las dos salidas eran malas.** El emisor faltante ofrecía un link a
 * `/identidades/nueva`: irse de la pantalla descarta el draft entero —vive en el estado de
 * `NewTemplatePage`, no en la URL ni en el server— así que "cargalo" costaba volver a importar
 * el PDF al volver. Y el cliente faltante se daba de alta **con los datos del PDF**, que es
 * texto leído de una factura ajena: la razón social viene cortada por el ancho de la columna, y
 * la condición frente al IVA sale de un rótulo impreso que puede estar viejo. De esa condición
 * depende la letra de todo lo que se emita después.
 *
 * Ahora las dos le preguntan al padrón de ARCA, muestran lo que contestó y crean recién cuando
 * el usuario acepta. El alta sigue siendo explícita —un botón, no un efecto de la importación,
 * la misma regla que hace que `/import` no escriba nada— y ocurre **sin salir de la pantalla**,
 * así que el modelo a medio importar no se pierde.
 *
 * El PDF no queda descartado: es el que dice *a quién* preguntarle a ARCA, es con lo que se
 * compara la respuesta, y sigue siendo el dato del alta cuando no hay padrón que consultar (un
 * DNI) o cuando no contesta.
 */

/**
 * Un dato del padrón, con lo que decía el PDF abajo **solo cuando difieren**.
 *
 * La diferencia es la información: si ARCA y el PDF dicen lo mismo, repetirlo es ruido; si
 * dicen distinto, el usuario necesita ver los dos para saber si está mirando al mismo
 * contribuyente antes de aceptar.
 */
function Row({ label, value, onPdf }: { label: string; value: ReactNode; onPdf?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value}
        {onPdf !== undefined && (
          <span className="muted" style={{ display: 'block', fontSize: '0.82rem' }}>
            En el PDF figura como {onPdf}.
          </span>
        )}
      </dd>
    </div>
  )
}

/**
 * El CUIT que emitió el PDF, cuando no es ninguna de las identidades fiscales cargadas.
 *
 * `onCreated` recibe la identidad ya creada: la pantalla la elige en el formulario y recarga la
 * lista del picker, que es lo que hace desaparecer este cartel.
 */
export function MissingIssuer({
  taxId,
  onCreated,
}: {
  taxId: string
  onCreated: (identity: FiscalIdentity) => void
}) {
  const [found, setFound] = useState<FiscalIdentityLookup>()
  // Arranca en lo que dijo el padrón, que puede ser `null`: hay CUIT que no figuran ni
  // inscriptos, ni exentos, ni monotributistas. Ahí la elige el usuario, igual que en el alta de
  // una identidad — ver *Consumidor final no está en el desplegable*.
  const [condicion, setCondicion] = useState<CondicionIva | null>(null)
  const [error, setError] = useState<string>()
  const [looking, setLooking] = useState(false)
  const [busy, setBusy] = useState(false)

  async function lookup() {
    setLooking(true)
    setError(undefined)
    try {
      const taxpayer = await api.get<FiscalIdentityLookup>(`/fiscal-identities/lookup/${taxId}`)
      setFound(taxpayer)
      setCondicion(taxpayer.condicion_iva)
    } catch (caught) {
      // 404 es "ARCA no tiene ese CUIT" y 502 es "no se pudo preguntar". Ninguno de los dos deja
      // sin salida: abajo del error quedan las otras dos puertas.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo consultar el padrón.')
    } finally {
      setLooking(false)
    }
  }

  async function create() {
    if (found === undefined || condicion === null) return
    setBusy(true)
    setError(undefined)
    try {
      const created = await api.post<FiscalIdentity>('/fiscal-identities', {
        // El nombre de la identidad es la razón social del padrón. Es un campo libre y único por
        // usuario, pero pedirle acá que invente un apodo sería un paso más en el medio de otra
        // tarea: se renombra después desde `/identidades/<id>` si hace falta.
        name: found.name,
        tax_id: found.tax_id,
        condicion_iva: condicion,
        address: found.address,
      })
      onCreated(created)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo crear la identidad fiscal.')
      // No se apaga en el camino feliz: `onCreated` hace desaparecer este cartel entero.
      setBusy(false)
    }
  }

  return (
    <div className="card stack">
      <Notice kind="warn">
        El PDF lo emitió el CUIT <strong className="mono">{taxId}</strong>, que no está entre tus
        identidades fiscales.
      </Notice>

      {found === undefined ? (
        <>
          <p className="muted" style={{ margin: 0 }}>
            Lo buscamos en el padrón de ARCA y te mostramos lo que figura; recién después se crea.
            También podés elegir otra identidad más abajo.
          </p>
          <button type="button" className="secondary" onClick={lookup} disabled={looking}>
            {looking ? 'Consultando ARCA…' : 'Buscar en ARCA'}
          </button>
        </>
      ) : (
        <>
          <dl className="summary">
            <Row label="CUIT" value={<span className="mono">{found.tax_id}</span>} />
            <Row label="Razón social" value={found.name} />
            {found.condicion_iva !== null && (
              <Row
                label="Condición frente al IVA"
                value={CONDICION_IVA_LABELS[found.condicion_iva]}
              />
            )}
            {found.address !== null && <Row label="Domicilio" value={found.address} />}
          </dl>

          {!found.active && (
            <Notice kind="warn">
              Ojo: en el padrón este CUIT figura con la clave inactiva. No va a poder emitir.
            </Notice>
          )}

          {found.condicion_iva === null && (
            <>
              <Notice kind="warn">
                En el padrón este CUIT no figura inscripto en IVA, ni exento, ni monotributista.
                Elegí la condición y revisala: de ella depende la letra de todo lo que emitas.
              </Notice>
              <div>
                <label htmlFor="mi-condicion">Condición frente al IVA</label>
                <select
                  id="mi-condicion"
                  value={condicion ?? ''}
                  onChange={(event) => setCondicion(Number(event.target.value) as CondicionIva)}
                >
                  {condicion === null && (
                    <option value="" disabled>
                      Elegí una…
                    </option>
                  )}
                  {EMISOR_CONDICIONES.map((value) => (
                    <option key={value} value={value}>
                      {CONDICION_IVA_LABELS[value]}
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}

          <button type="button" onClick={create} disabled={busy || condicion === null}>
            {busy ? 'Creando…' : 'Crear la identidad fiscal'}
          </button>
        </>
      )}

      <Notice kind="error">{error}</Notice>

      {/* Aparece recién cuando el padrón falló, y avisa lo que cuesta: el link se lleva puesto
          el modelo importado. Antes era la única salida y no lo decía. */}
      {error !== undefined && found === undefined && (
        <p className="muted" style={{ margin: 0 }}>
          Podés elegir otra identidad más abajo, o{' '}
          <Link to="/identidades/nueva">cargarla a mano</Link> — pero irse de esta pantalla
          descarta lo que se importó del PDF.
        </p>
      )}
    </div>
  )
}

/**
 * El receptor del PDF, cuando todavía no está en la cartera de clientes.
 *
 * `draft` es lo que el parser leyó y `fallback` es ese mismo draft ya validado como un alta
 * completa —o `undefined` si le falta alguno de los campos obligatorios—. Los dos se usan: el
 * draft para saber a qué CUIT preguntarle y para comparar contra lo que conteste ARCA, el
 * fallback para el alta cuando no hay padrón.
 */
export function MissingCustomer({
  draft,
  fallback,
  onCreated,
}: {
  draft: CustomerDraft
  fallback: CustomerCreate | undefined
  onCreated: (customer: Customer) => void
}) {
  const [found, setFound] = useState<TaxpayerLookup>()
  const [error, setError] = useState<string>()
  const [looking, setLooking] = useState(false)
  const [busy, setBusy] = useState(false)

  const cuit = isCuit(draft.doc_type, draft.doc_number) ? draft.doc_number : undefined

  // Lo que el PDF decía y el padrón no confirma. Son los dos datos que importan: el nombre es
  // con lo que el usuario reconoce al cliente, y de la condición cuelga la letra.
  const pdfName = draft.name !== null && draft.name !== found?.name ? draft.name : undefined
  const pdfCondicion =
    draft.condicion_iva !== null && draft.condicion_iva !== found?.condicion_iva
      ? CONDICION_IVA_LABELS[draft.condicion_iva]
      : undefined

  async function lookup() {
    if (cuit === undefined) return
    setLooking(true)
    setError(undefined)
    try {
      setFound(await api.get<TaxpayerLookup>(`/customers/lookup/${cuit}`))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo consultar el padrón.')
    } finally {
      setLooking(false)
    }
  }

  async function create(body: CustomerCreate) {
    setBusy(true)
    setError(undefined)
    try {
      onCreated(await api.post<Customer>('/customers', body))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo dar de alta el cliente.')
      setBusy(false)
    }
  }

  function fromPadron(taxpayer: TaxpayerLookup): CustomerCreate {
    return {
      name: taxpayer.name,
      condicion_iva: taxpayer.condicion_iva,
      doc_type: taxpayer.doc_type,
      doc_number: taxpayer.doc_number,
      // El domicilio del padrón es el fiscal y puede no estar; el del PDF es el que el emisor le
      // imprimió al comprobante. Con los dos, gana ARCA; con uno solo, ese.
      address: taxpayer.address ?? draft.address,
      // El mail no lo trae ninguno de los dos: se carga desde el cliente cuando haya que
      // mandarle una factura.
      email: null,
    }
  }

  return (
    <div className="card stack">
      <Notice kind="warn">
        {draft.name !== null ? (
          <>
            El cliente <strong>{draft.name}</strong> (
            <span className="mono">{draft.doc_number}</span>) todavía no está en tu cartera.
          </>
        ) : (
          <>
            El CUIT <strong className="mono">{draft.doc_number}</strong> que recibió esa factura
            todavía no está en tu cartera.
          </>
        )}
      </Notice>

      {found === undefined ? (
        <>
          {cuit !== undefined && (
            <>
              <p className="muted" style={{ margin: 0 }}>
                Lo buscamos en el padrón de ARCA —razón social, domicilio y condición frente al
                IVA— y te mostramos lo que figura antes de darlo de alta.
              </p>
              <button type="button" className="secondary" onClick={lookup} disabled={looking}>
                {looking ? 'Consultando ARCA…' : 'Buscar en ARCA'}
              </button>
            </>
          )}

          {/* Con un DNI no hay padrón que consultar, así que el alta con lo que trajo el PDF no
              es un plan B sino el único camino: se ofrece de entrada, y como botón principal.
              Cuando sí hay CUIT aparece recién si ARCA falló — ofrecerlo antes sería invitar a
              saltear el camino que trae los datos bien. */}
          {fallback !== undefined && (cuit === undefined || error !== undefined) && (
            <button
              type="button"
              className={cuit === undefined ? undefined : 'secondary'}
              onClick={() => create(fallback)}
              disabled={busy}
            >
              {busy ? 'Dando de alta…' : 'Darlo de alta con los datos del PDF'}
            </button>
          )}

          {fallback === undefined && error !== undefined && (
            <p className="muted" style={{ margin: 0 }}>
              El PDF tampoco trajo todos los datos del cliente, así que no hay con qué darlo de
              alta acá. Podés <Link to="/clientes/nuevo">cargarlo desde Clientes</Link> — pero
              irse de esta pantalla descarta lo que se importó del PDF.
            </p>
          )}
        </>
      ) : (
        <>
          <dl className="summary">
            <Row label="CUIT" value={<span className="mono">{found.doc_number}</span>} />
            <Row label="Razón social" value={found.name} onPdf={pdfName} />
            <Row
              label="Condición frente al IVA"
              value={CONDICION_IVA_LABELS[found.condicion_iva]}
              onPdf={pdfCondicion}
            />
            {(found.address ?? draft.address) !== null && (
              <Row label="Domicilio" value={found.address ?? draft.address} />
            )}
          </dl>

          {!found.active && (
            <Notice kind="warn">
              Ojo: en el padrón este CUIT figura con la clave inactiva.
            </Notice>
          )}

          <button type="button" onClick={() => create(fromPadron(found))} disabled={busy}>
            {busy ? 'Dando de alta…' : 'Crear el cliente'}
          </button>

          {/* Solo cuando ARCA y el PDF no coinciden, y solo como segunda opción. Ahí puede ser
              que el parser haya leído mal el CUIT y el padrón esté contestando por otro
              contribuyente: sin esta salida, la única forma de no aceptar a un desconocido es
              perder el modelo importado. */}
          {(pdfName !== undefined || pdfCondicion !== undefined) && fallback !== undefined && (
            <button
              type="button"
              className="secondary"
              onClick={() => create(fallback)}
              disabled={busy}
            >
              Mejor con los datos del PDF
            </button>
          )}
        </>
      )}

      <Notice kind="error">{error}</Notice>
    </div>
  )
}
