import { useEffect, useRef, useState, type ReactNode } from 'react'
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
 * Ahora las dos preguntan al padrón de ARCA **solas, apenas se importa el PDF**. No hay un botón
 * "Buscar en ARCA": pedirle al usuario que apriete un botón para averiguar algo que la app puede
 * averiguar sola es hacerle trabajar de intermediario. Lo que cambia entre las dos es qué pasa
 * con la respuesta, y no es una inconsistencia:
 *
 * - **El cliente se da de alta solo y se avisa.** Es una fila en la agenda propia del usuario:
 *   se edita, se borra, y no le dice nada a ARCA. El costo de equivocarse es un cliente de más
 *   en una lista; el de preguntar es un paso en el medio de otra tarea.
 * - **La identidad fiscal necesita un toque.** Declara "yo emito desde este CUIT", que es otra
 *   cosa: FactuMov después le verifica la delegación contra ARCA sola y le avisa al operador si
 *   falta. Y el PDF importado puede ser una factura **recibida**, donde el emisor es el
 *   proveedor: darla de alta sola convertiría al proveedor en un emisor propio, elegido en el
 *   modelo, que además no va a poder emitir nunca. Un botón de más ahí cuesta un toque; el error
 *   cuesta explicarlo.
 *
 * El PDF no queda descartado: es el que dice *a quién* preguntarle a ARCA, es con lo que se
 * compara la respuesta, y es el dato del alta cuando no hay padrón que consultar (un DNI) o
 * cuando no contesta.
 */

/**
 * Un dato del padrón, con lo que decía el PDF abajo **solo cuando difieren**.
 *
 * La diferencia es la información: si ARCA y el PDF dicen lo mismo, repetirlo es ruido; si
 * dicen distinto, el usuario necesita ver los dos para saber si está mirando al mismo
 * contribuyente.
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
 * Consulta el padrón al montarse y muestra lo que contestó; el alta la confirma el usuario con
 * un botón, por lo que dice el comentario de arriba. `onCreated` recibe la identidad ya creada:
 * la pantalla la elige en el formulario y recarga la lista del picker.
 */
export function MissingIssuer({
  taxId,
  onCreated,
}: {
  taxId: string
  onCreated: (identity: FiscalIdentity) => void
}) {
  const [found, setFound] = useState<FiscalIdentityLookup>()
  const [created, setCreated] = useState<FiscalIdentity>()
  // Arranca en lo que dijo el padrón, que puede ser `null`: hay CUIT que no figuran ni
  // inscriptos, ni exentos, ni monotributistas. Ahí la elige el usuario, igual que en el alta de
  // una identidad — ver *Consumidor final no está en el desplegable*.
  const [condicion, setCondicion] = useState<CondicionIva | null>(null)
  const [error, setError] = useState<string>()
  const [looking, setLooking] = useState(true)
  const [busy, setBusy] = useState(false)

  // StrictMode monta dos veces en desarrollo y esto sale a ARCA: sin la guarda, cada
  // importación gasta dos consultas del presupuesto en vez de una. Es la misma trampa que la
  // confirmación de mail, que ahí costaba un token de un solo uso.
  const asked = useRef(false)

  useEffect(() => {
    if (asked.current) return
    asked.current = true
    api
      .get<FiscalIdentityLookup>(`/fiscal-identities/lookup/${taxId}`)
      .then((taxpayer) => {
        setFound(taxpayer)
        setCondicion(taxpayer.condicion_iva)
      })
      .catch((caught: unknown) => {
        // 404 es "ARCA no tiene ese CUIT" y 502 es "no se pudo preguntar". Ninguno de los dos
        // deja sin salida: abajo del error quedan las otras dos puertas.
        setError(caught instanceof ApiError ? caught.detail : 'No se pudo consultar el padrón.')
      })
      .finally(() => setLooking(false))
  }, [taxId])

  async function create() {
    if (found === undefined || condicion === null) return
    setBusy(true)
    setError(undefined)
    try {
      const identity = await api.post<FiscalIdentity>('/fiscal-identities', {
        // El nombre de la identidad es la razón social del padrón. Es un campo libre y único por
        // usuario, pero pedirle acá que invente un apodo sería un paso más en el medio de otra
        // tarea: se renombra después desde `/identidades/<id>` si hace falta.
        name: found.name,
        tax_id: found.tax_id,
        condicion_iva: condicion,
        address: found.address,
      })
      setCreated(identity)
      onCreated(identity)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo crear la identidad fiscal.')
    } finally {
      setBusy(false)
    }
  }

  // La tarjeta **no desaparece** cuando el alta sale bien: decir qué se creó es la mitad del
  // trabajo. Por eso la pantalla la sigue mostrando —no le toca el draft— y el final feliz se
  // dibuja acá.
  if (created !== undefined) {
    return (
      <div className="card stack">
        <Notice kind="ok">
          Agregué la identidad fiscal <strong>{created.name}</strong> (
          <span className="mono">{created.tax_id}</span>) con los datos de ARCA, y la dejé elegida
          en el modelo.
        </Notice>
        <p className="muted" style={{ margin: 0 }}>
          Para emitir desde este CUIT falta que lo tengas delegado a FactuMov en ARCA. Eso se
          revisa en Identidades, cuando termines con el modelo.
        </p>
      </div>
    )
  }

  return (
    <div className="card stack">
      <Notice kind="warn">
        El PDF lo emitió el CUIT <strong className="mono">{taxId}</strong>, que no está entre tus
        identidades fiscales.
      </Notice>

      {looking && <p className="muted" style={{ margin: 0 }}>Buscándolo en el padrón de ARCA…</p>}

      {found !== undefined && (
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
            {busy ? 'Agregando…' : 'Agregarla a mis identidades fiscales'}
          </button>
          <p className="muted" style={{ margin: 0 }}>
            Es el CUIT desde el que vas a emitir: se agrega solo si lo confirmás. Si el PDF es una
            factura que recibiste, no lo agregues — elegí tu identidad más abajo.
          </p>
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

/** De dónde salieron los datos con los que se dio de alta el cliente. */
type Source = 'padron' | 'pdf'

/**
 * El receptor del PDF, cuando todavía no está en la cartera de clientes.
 *
 * **Se da de alta solo y después se cuenta.** No hay botón: preguntar "¿lo agrego?" cuando la
 * respuesta va a ser siempre que sí es un paso de más, y el alta es reversible —una fila de la
 * agenda del usuario, que se edita y se borra— así que el costo de equivocarse es bajo y el de
 * preguntar se paga en cada importación.
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
  const [created, setCreated] = useState<{ customer: Customer; source: Source }>()
  const [warning, setWarning] = useState<string>()
  const [error, setError] = useState<string>()

  const cuit = isCuit(draft.doc_type, draft.doc_number) ? draft.doc_number : undefined

  // Acá la guarda de StrictMode no evita una consulta de más sino **un cliente de más**: el
  // segundo montaje volvería a postear y ARCA no tiene nada que ver. El 409 por documento
  // duplicado lo atajaría, pero contar con un error del backend para no duplicar una fila es
  // dejar la corrección en el lugar equivocado.
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    async function resolve() {
      let body = fallback
      let source: Source = 'pdf'
      let note: string | undefined

      if (cuit !== undefined) {
        try {
          const taxpayer = await api.get<TaxpayerLookup>(`/customers/lookup/${cuit}`)
          body = {
            name: taxpayer.name,
            condicion_iva: taxpayer.condicion_iva,
            doc_type: taxpayer.doc_type,
            doc_number: taxpayer.doc_number,
            // El domicilio del padrón es el fiscal y puede no estar; el del PDF es el que el
            // emisor le imprimió al comprobante. Con los dos, gana ARCA; con uno solo, ese.
            address: taxpayer.address ?? draft.address,
            // El mail no lo trae ninguno de los dos: se carga desde el cliente cuando haya que
            // mandarle una factura.
            email: null,
          }
          source = 'padron'
          if (!taxpayer.active) {
            note = 'En el padrón este CUIT figura con la clave inactiva.'
          }
        } catch (caught) {
          // 404 —ARCA no tiene ese CUIT— y 502 —no se pudo preguntar— no cancelan el alta: la
          // hacen con lo que trajo el PDF, que es peor dato pero es un dato. Lo que no se puede
          // es dar de alta con datos del PDF **sin decirlo**.
          note = caught instanceof ApiError ? caught.detail : 'No se pudo consultar el padrón.'
        }
      } else {
        note = 'El padrón solo se consulta por CUIT.'
      }

      if (body === undefined) {
        setError(
          `${note ?? 'No se pudo consultar el padrón.'} El PDF tampoco trajo todos los datos ` +
            'del cliente, así que no hay con qué darlo de alta.',
        )
        return
      }

      try {
        const customer = await api.post<Customer>('/customers', body)
        setCreated({ customer, source })
        setWarning(note)
        onCreated(customer)
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.detail : 'No se pudo dar de alta el cliente.')
      }
    }

    void resolve()
    // Corre una sola vez, al montarse, y el linter tiene que aguantárselo. Las dependencias que
    // pide salen del draft, que no cambia mientras la tarjeta está en pantalla; y si cambiaran,
    // volver a correr no refrescaría nada: daría de alta un segundo cliente. La lista vacía es
    // la intención, no un olvido — por eso la guarda de arriba y no un `[cuit, fallback, …]`
    // que se re-arma en cada render y depende igual de la guarda para no duplicar la fila.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const label =
    draft.name !== null ? (
      <>
        El cliente <strong>{draft.name}</strong> (
        <span className="mono">{draft.doc_number}</span>)
      </>
    ) : (
      <>
        El CUIT <strong className="mono">{draft.doc_number}</strong> que recibió esa factura
      </>
    )

  if (created === undefined) {
    return (
      <div className="card stack">
        <Notice kind="warn">{label} todavía no está en tu cartera.</Notice>
        {error === undefined ? (
          <p className="muted" style={{ margin: 0 }}>
            {cuit !== undefined ? 'Buscándolo en el padrón de ARCA…' : 'Dándolo de alta…'}
          </p>
        ) : (
          <>
            <Notice kind="error">{error}</Notice>
            <p className="muted" style={{ margin: 0 }}>
              Podés <Link to="/clientes/nuevo">cargarlo desde Clientes</Link> — pero irse de esta
              pantalla descarta lo que se importó del PDF.
            </p>
          </>
        )}
      </div>
    )
  }

  const customer = created.customer
  // Lo que el PDF decía y el padrón no confirmó. Son los dos datos que importan: el nombre es
  // con lo que el usuario reconoce al cliente, y de la condición cuelga la letra.
  const pdfName = draft.name !== null && draft.name !== customer.name ? draft.name : undefined
  const pdfCondicion =
    draft.condicion_iva !== null && draft.condicion_iva !== customer.condicion_iva
      ? CONDICION_IVA_LABELS[draft.condicion_iva]
      : undefined

  return (
    <div className="card stack">
      {created.source === 'padron' ? (
        <Notice kind="ok">
          {label} no estaba en tu cartera: lo di de alta con los datos de ARCA y lo dejé elegido
          en el modelo.
        </Notice>
      ) : (
        <Notice kind="warn">
          {label} no estaba en tu cartera: lo di de alta con los datos del PDF, que son los que
          alguien imprimió en ese comprobante. Revisá sobre todo la condición frente al IVA: de
          ella depende la letra.
        </Notice>
      )}

      {warning !== undefined && <Notice kind="warn">{warning}</Notice>}

      <dl className="summary">
        <Row label="Documento" value={<span className="mono">{customer.doc_number}</span>} />
        <Row label="Nombre o razón social" value={customer.name} onPdf={pdfName} />
        <Row
          label="Condición frente al IVA"
          value={CONDICION_IVA_LABELS[customer.condicion_iva]}
          onPdf={pdfCondicion}
        />
        {customer.address !== null && <Row label="Domicilio" value={customer.address} />}
      </dl>

      <p className="muted" style={{ margin: 0 }}>
        Si algo no coincide, se corrige después en Clientes: irse ahora descarta lo que se
        importó del PDF.
      </p>
    </div>
  )
}
