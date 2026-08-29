import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError, api } from '../api/client'
import { checkedRecently, markChecked, needsChecking } from '../api/delegation'
import {
  CONDICION_IVA_LABELS,
  CondicionIva,
  EMISOR_CONDICIONES,
  type DelegationStatus,
  type FiscalIdentity,
  type FiscalIdentityLookup,
} from '../api/types'
import { Notice } from '../components/Notice'

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

function digitsOf(value: string) {
  return value.replace(/\D/g, '')
}

/**
 * Los datos con los que arranca el formulario.
 *
 * Existe porque el alta ya no empieza vacía: empieza con lo que ARCA contestó sobre el CUIT.
 * En la edición sale de la fila guardada, y en el alta a mano sale del CUIT que el usuario
 * tipeó y nada más.
 */
interface Seed {
  tax_id: string
  name: string
  /** `null` = todavía no se sabe, y el desplegable obliga a elegir. Ver `FiscalIdentityForm`. */
  condicion_iva: CondicionIva | null
  address: string
  /** Lo que haya que avisar sobre lo que trajo el padrón: CUIT inactivo, condición vacía. */
  note?: string
}

/**
 * Una identidad fiscal: `/identidades/nueva` para el alta y `/identidades/:id` para la edición.
 *
 * Son dos rutas y un solo componente, como el modelo. Separarlos sería copiar el formulario
 * entero para cambiar el verbo HTTP y el texto del botón, y garantizar que dentro de tres meses
 * uno de los dos tenga un campo que el otro no.
 *
 * Que la edición sea una **pantalla** y no un formulario arriba de una tabla es lo que hace que
 * el "mantener apretado" sobre la identidad fiscal de un modelo aterrice donde tiene que
 * aterrizar: la pantalla que abre el gesto es `/identidades/<id>`, o sea un link como cualquier
 * otro. Antes el id viajaba como `?editar=<id>` sobre la lista, que era la misma idea con una
 * URL que había que explicar.
 */
export function FiscalIdentityPage() {
  const { id } = useParams()
  // El `key` remonta al cambiar de identidad: adentro hay un formulario sembrado con los datos
  // de la anterior, y sin el remonte entrar a otra mostraría la de antes.
  return <FiscalIdentityScreen key={id ?? 'nueva'} id={id} />
}

function FiscalIdentityScreen({ id }: { id?: string }) {
  const navigate = useNavigate()

  // `null` es "no hay fila": en el alta es el estado final, y en la edición dura lo que tarda
  // la carga, que es lo que informa `loading`.
  const [identity, setIdentity] = useState<FiscalIdentity | null>(null)
  const [loading, setLoading] = useState(id !== undefined)
  const [loadError, setLoadError] = useState<string>()
  // Solo el alta: `undefined` mientras estamos en el paso del CUIT. La edición no lo usa — su
  // semilla sale de la fila.
  const [seed, setSeed] = useState<Seed>()

  useEffect(() => {
    if (id === undefined) return
    let cancelled = false
    api
      .get<FiscalIdentity>(`/fiscal-identities/${id}`)
      .then((found) => {
        if (cancelled) return
        setIdentity(found)
        setLoading(false)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setLoadError(
          caught instanceof ApiError ? caught.detail : 'No se pudo cargar la identidad fiscal.',
        )
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id])

  const editingSeed: Seed | undefined =
    identity === null
      ? undefined
      : {
          tax_id: identity.tax_id,
          name: identity.name,
          condicion_iva: identity.condicion_iva,
          address: identity.address ?? '',
        }
  const current = editingSeed ?? seed

  return (
    <div className="page">
      <Link className="back" to="/identidades">
        &larr; Identidades
      </Link>
      <h1>{identity?.name ?? 'Nueva identidad fiscal'}</h1>

      <Notice kind="error">{loadError}</Notice>
      {loading && <p className="muted">Cargando…</p>}

      {!loading && loadError === undefined && (
        <>
          {current === undefined ? (
            <TaxIdStep onReady={setSeed} />
          ) : (
            <FiscalIdentityForm
              editing={identity ?? undefined}
              initial={current}
              onCreated={() => navigate('/identidades')}
              onUpdated={setIdentity}
            />
          )}
          {/* La verificación solo tiene sentido sobre una fila que ya existe: la llamada a ARCA
              va contra el CUIT guardado. */}
          {identity !== null && <DelegationCard identity={identity} onChanged={setIdentity} />}
        </>
      )}
    </div>
  )
}

/** El aviso que corresponda sobre lo que contestó el padrón, o nada si no hay ninguno. */
function noteFor(found: FiscalIdentityLookup): string | undefined {
  if (!found.active) {
    return 'Ojo: en el padrón este CUIT figura con la clave inactiva. No va a poder emitir.'
  }
  if (found.condicion_iva === null) {
    return (
      'En el padrón este CUIT no figura inscripto en IVA, ni exento, ni monotributista. ' +
      'Elegí la condición a mano y revisala: de ella depende la letra de todo lo que emitas.'
    )
  }
  return undefined
}

/**
 * El primer paso del alta: se pide el CUIT y el resto lo trae ARCA.
 *
 * **El CUIT es lo único que el usuario sabe de memoria.** La razón social exacta, el domicilio
 * fiscal tal como está registrado y —sobre todo— la condición frente al IVA son datos que se
 * cargan mal, y de la condición depende la letra de cada comprobante: anotarse como
 * monotributista cuando ARCA lo tiene como inscripto es emitir C donde iba A.
 *
 * **Y no puede ser la única puerta.** El padrón contesta 502 cuando ARCA no está —hoy mismo,
 * mientras falte el certificado propio— y un CUIT recién inscripto puede no figurar todavía.
 * Por eso el fallo no bloquea: dice qué pasó y ofrece cargarla a mano con el CUIT ya tipeado.
 * Es la misma regla que hace que la importación de un PDF ilegible tenga un "empezar en
 * blanco".
 */
function TaxIdStep({ onReady }: { onReady: (seed: Seed) => void }) {
  const [taxId, setTaxId] = useState('')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  const digits = digitsOf(taxId)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    // El `disabled` del botón cubre el click y no el Enter en el campo — mismo motivo que en
    // la pantalla de emisión, con la diferencia de que acá lo que se duplica es una llamada a
    // ARCA y no una factura.
    if (busy || digits.length !== 11) return
    setBusy(true)
    setError(undefined)
    try {
      const found = await api.get<FiscalIdentityLookup>(`/fiscal-identities/lookup/${digits}`)
      onReady({
        tax_id: found.tax_id,
        name: found.name,
        condicion_iva: found.condicion_iva,
        address: found.address ?? '',
        note: noteFor(found),
      })
    } catch (caught) {
      // 404 es "ARCA no tiene ese CUIT" y 502 es "no se pudo preguntar". Ninguno de los dos
      // impide cargar la identidad, así que son avisos con una salida al lado.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo consultar el padrón.')
    } finally {
      setBusy(false)
    }
  }

  function byHand() {
    onReady({ tax_id: digits, name: '', condicion_iva: null, address: '' })
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <div>
        <label htmlFor="fi-lookup">CUIT</label>
        {/* Los guiones se limpian al mandar: la columna guarda once dígitos, y hacer que el
            usuario los tipee sin guiones es pedirle que se adapte al esquema. */}
        <input
          id="fi-lookup"
          required
          inputMode="numeric"
          placeholder="20-12345678-9"
          value={taxId}
          onChange={(event) => {
            setError(undefined)
            setTaxId(event.target.value)
          }}
        />
        <p className="muted">
          Buscamos en el padrón de ARCA la razón social, el domicilio y la condición frente al
          IVA. Después podés corregir lo que haga falta.
        </p>
      </div>

      <Notice kind="error">{error}</Notice>

      <button type="submit" disabled={digits.length !== 11 || busy}>
        {busy ? 'Consultando ARCA…' : 'Buscar en ARCA'}
      </button>

      {/* Aparece recién cuando el padrón falló: ofrecerlo antes sería invitar a saltear el
          camino que trae los datos bien. */}
      {error !== undefined && (
        <button type="button" className="secondary" onClick={byHand}>
          Cargarla a mano
        </button>
      )}
    </form>
  )
}

function FiscalIdentityForm({
  editing,
  initial,
  onCreated,
  onUpdated,
}: {
  editing?: FiscalIdentity
  initial: Seed
  onCreated: () => void
  onUpdated: (identity: FiscalIdentity) => void
}) {
  const [name, setName] = useState(initial.name)
  const [taxId, setTaxId] = useState(initial.tax_id)
  // `null` es "todavía no se eligió", y el desplegable arranca en su placeholder. No hay valor
  // por default a propósito: la condición decide la letra de cada comprobante que se emita, así
  // que dejar puesto "responsable inscripto" cuando no se sabe es exactamente un valor
  // plausible y equivocado — el mismo motivo por el que la letra se deduce en vez de ofrecerse.
  const [condicionIva, setCondicionIva] = useState<CondicionIva | null>(initial.condicion_iva)
  const [address, setAddress] = useState(initial.address)
  const [error, setError] = useState<string>()
  const [note, setNote] = useState(initial.note)
  const [looking, setLooking] = useState(false)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy || condicionIva === null) return
    setBusy(true)
    setError(undefined)
    setSaved(false)
    const body = {
      name,
      tax_id: digitsOf(taxId),
      condicion_iva: condicionIva,
      // Cadena vacía y "sin dato" no son lo mismo para una columna que admite NULL: mandar
      // `""` guardaría un domicilio vacío en vez de ninguno.
      address: address.trim() || null,
    }
    try {
      if (editing) {
        onUpdated(await api.patch<FiscalIdentity>(`/fiscal-identities/${editing.id}`, body))
        setSaved(true)
      } else {
        await api.post<FiscalIdentity>('/fiscal-identities', body)
        // El alta vuelve a la grilla: la tarjeta nueva ahí es la confirmación de que se guardó,
        // y es además donde el usuario iba a ir igual.
        onCreated()
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo guardar.')
    } finally {
      setBusy(false)
    }
  }

  /**
   * Vuelve a preguntarle al padrón y **pisa el formulario**, sin guardar nada.
   *
   * Sirve para el CUIT que se tipeó mal en el paso anterior y para la razón social o el
   * domicilio que cambiaron desde que se cargó la identidad. Que quede editable es el punto: el
   * backend devuelve una propuesta, no un alta.
   */
  async function lookup() {
    setLooking(true)
    setError(undefined)
    setNote(undefined)
    setSaved(false)
    try {
      const found = await api.get<FiscalIdentityLookup>(
        `/fiscal-identities/lookup/${digitsOf(taxId)}`,
      )
      setTaxId(found.tax_id)
      setName(found.name)
      setCondicionIva(found.condicion_iva)
      setAddress(found.address ?? '')
      setNote(noteFor(found) ?? 'Datos traídos del padrón. Revisalos antes de guardar.')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo consultar el padrón.')
    } finally {
      setLooking(false)
    }
  }

  /** Cualquier cambio invalida el "Guardado": dejarlo puesto es la forma más barata de que
   *  alguien salga de la pantalla creyendo que guardó lo que acaba de tipear. */
  function edited() {
    setSaved(false)
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <div className="row">
        <div>
          <label htmlFor="fi-tax-id">CUIT</label>
          <input
            id="fi-tax-id"
            required
            inputMode="numeric"
            placeholder="20-12345678-9"
            value={taxId}
            onChange={(event) => {
              edited()
              setTaxId(event.target.value)
            }}
          />
        </div>
        <button
          type="button"
          className="secondary"
          onClick={lookup}
          disabled={digitsOf(taxId).length !== 11 || looking}
          title="Trae razón social, domicilio y condición IVA del padrón de ARCA"
        >
          {looking ? 'Consultando…' : 'Traer del padrón'}
        </button>
      </div>

      {note !== undefined && (
        <Notice kind={note.startsWith('Datos traídos') ? 'ok' : 'warn'}>{note}</Notice>
      )}

      <div>
        <label htmlFor="fi-name">Nombre o razón social</label>
        <input
          id="fi-name"
          required
          value={name}
          onChange={(event) => {
            edited()
            setName(event.target.value)
          }}
        />
      </div>

      <div>
        <label htmlFor="fi-condicion">Condición frente al IVA</label>
        <select
          id="fi-condicion"
          required
          value={condicionIva ?? ''}
          onChange={(event) => {
            edited()
            setCondicionIva(Number(event.target.value) as CondicionIva)
          }}
        >
          {/* El placeholder existe solo mientras no se eligió, y sale de la lista apenas hay
              valor: así el desplegable no ofrece volver a "sin elegir", que no es un estado
              que se pueda guardar. */}
          {condicionIva === null && (
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

      <div>
        <label htmlFor="fi-address">Domicilio (opcional)</label>
        <input
          id="fi-address"
          value={address}
          onChange={(event) => {
            edited()
            setAddress(event.target.value)
          }}
        />
      </div>

      <Notice kind="error">{error}</Notice>
      {saved && <Notice kind="ok">Guardado.</Notice>}

      <button type="submit" disabled={busy}>
        {busy ? 'Guardando…' : editing ? 'Guardar cambios' : 'Crear la identidad fiscal'}
      </button>
    </form>
  )
}

/**
 * El estado de la delegación en ARCA.
 *
 * **Delegar tiene dos partes y la segunda es nuestra.** El contribuyente entra a ARCA y designa
 * a FactuMov como representante para Facturación Electrónica; después FactuMov tiene que
 * *aceptar* esa designación, a mano y con Clave Fiscal, en «Aceptación de Designación». Hasta
 * que eso pasa, WSFE contesta exactamente lo mismo que si el usuario no hubiera hecho nada.
 *
 * Por eso esta tarjeta tiene **tres** estados y no dos. Con dos, a quien ya delegó y está
 * esperándonos le decíamos «entrá a autorizarnos» con los cinco pasos: mandarlo a rehacer un
 * trámite que hizo bien, y no contarle que la demora es nuestra. El tercer estado sale de
 * `delegation_claimed_at`, que es información que no puede venir de ARCA —no publica las
 * designaciones pendientes por ningún web service— y que solo tiene el usuario.
 *
 * **Verificada no lleva botón.** Antes lo tenía porque `delegation_verified_at` significa "esto
 * era verdad en esta fecha" y la delegación se revoca sin avisarnos, así que hacía falta poder
 * repreguntar. Pero depender de que el usuario apriete un botón para enterarse de una
 * revocación nunca iba a funcionar: eso ahora lo cubre el rechequeo automático de abajo, que no
 * hay que acordarse de apretar.
 */

function DelegationCard({
  identity,
  onChanged,
}: {
  identity: FiscalIdentity
  onChanged: (identity: FiscalIdentity) => void
}) {
  const [error, setError] = useState<string>()
  // Arranca en `true` cuando el efecto de abajo va a salir a ARCA, y no se prende adentro del
  // efecto. Dos motivos, y el segundo importa más: oxlint avisa —con razón, como las veces
  // anteriores— de un `setState` sincrónico dentro de un efecto, y sobre todo prender el
  // indicador *después* del primer render hace que la tarjeta muestre "Sin verificar" un frame
  // antes de decir que está consultando. El estado inicial ya sabe cuál de los dos es.
  const [busy, setBusy] = useState(
    () => needsChecking(identity.delegation_verified_at) && !checkedRecently(identity.id),
  )
  // Por qué el chequeo automático no pudo contestar. Va aparte de `error` a propósito: `error`
  // es el cartel rojo de una acción que el usuario eligió, y esto es una nota al pie sobre algo
  // que la pantalla intentó sola.
  const [autoNote, setAutoNote] = useState<string>()
  // La última respuesta de ARCA. Se guarda por un solo dato: `delegate_tax_id`, el CUIT al que
  // hay que autorizar. No se escribe acá a mano aunque sea el mismo siempre — sale de
  // `arca.get_delegate_tax_id()`, que lo lee del certificado, y una segunda copia es
  // exactamente cómo se llega a que la pantalla diga un CUIT y el sistema espere otro.
  const [status, setStatus] = useState<DelegationStatus>()

  const run = useCallback(
    async (path: 'verify-delegation' | 'claim-delegation') => {
      // Los dos endpoints salen a ARCA con el mismo certificado, así que los dos cuentan para
      // el piso entre consultas — ver `api/delegation.ts`.
      markChecked(identity.id)
      try {
        const result = await api.post<DelegationStatus>(
          `/fiscal-identities/${identity.id}/${path}`,
        )
        setStatus(result)
        setError(undefined)
        setAutoNote(undefined)
        onChanged({
          ...identity,
          delegation_verified_at: result.delegation_verified_at,
          delegation_claimed_at: result.delegation_claimed_at,
        })
      } finally {
        setBusy(false)
      }
    },
    [identity, onChanged],
  )

  // El chequeo automático al abrir la pantalla, una sola vez por montaje.
  //
  // El `useRef` no es contra un re-render: es contra el doble montaje de StrictMode, que en
  // desarrollo dispararía dos llamadas a ARCA por cada apertura — el mismo guard que
  // `ConfirmEmailPage`. Y la condición es `needsChecking` y no "siempre": repreguntar por una
  // identidad verificada hace días no aprende nada y gasta cuota que es de todos los usuarios,
  // porque el certificado de ARCA es uno solo para toda la app. `checkedRecently` es el mismo
  // cuidado a través de los montajes, ahora que la grilla también pregunta.
  const checkedOnMount = useRef(false)
  useEffect(() => {
    if (checkedOnMount.current) return
    if (!needsChecking(identity.delegation_verified_at)) return
    if (checkedRecently(identity.id)) return
    checkedOnMount.current = true
    // **Sin cartel rojo, pero no en silencio.** Sigue sin ser un error del usuario —esto no lo
    // pidió nadie—, así que no se pinta como los de las acciones que él eligió. Pero tragarse
    // el fallo entero, que es lo que hacía antes un `.catch(() => {})`, deja un 502 o un 429
    // viéndose exactamente igual que un "ARCA dice que todavía no": la pantalla se queda en
    // «Falta un paso nuestro» afirmando que estamos mirando, justo cuando no pudimos mirar.
    void run('verify-delegation').catch((caught: unknown) => {
      setAutoNote(
        caught instanceof ApiError && caught.status === 429
          ? 'Consultamos ARCA demasiadas veces; probá de nuevo en un rato.'
          : 'No se pudo consultar ARCA recién.',
      )
    })
  }, [run, identity.id, identity.delegation_verified_at])

  async function claim() {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      await run('claim-delegation')
    } catch (caught) {
      // El 502 es "no se pudo preguntar", que no es lo mismo que "no estás delegado" — eso
      // último llega como un 200 con `granted: false`. Mezclarlos haría que un ARCA caído se
      // vea como una delegación faltante, y el usuario iría a otorgar una que ya tiene.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo verificar.')
    }
  }

  const verified = identity.delegation_verified_at
  const claimed = identity.delegation_claimed_at

  return (
    <div className="card stack">
      <h2>Delegación en ARCA</h2>

      <div className="delegation-state">
        {verified ? (
          <span className="badge ok">Verificada</span>
        ) : (
          <span className="badge pending">Sin verificar</span>
        )}
        {verified && <span className="muted">Última: {formatDate(verified)}</span>}
        {busy && <span className="muted">Consultando ARCA…</span>}
        {!busy && autoNote !== undefined && <span className="muted">{autoNote}</span>}
      </div>

      {error && <Notice kind="error">{error}</Notice>}

      {verified === null && claimed === null && (
        <>
          {/* Los pasos aparecen solos: el chequeo del montaje trae el CUIT al que hay que
              autorizar. Antes había que apretar el botón para verlos, o sea que la primera
              respuesta a "acabo de cargar mi CUIT, ¿y ahora?" era una pantalla sin
              instrucciones. */}
          {status?.delegate_tax_id != null && (
            <Notice kind="warn">
              ARCA todavía no nos autorizó para este CUIT. Entrá a autorizarnos:
              <ol>
                <li>
                  Entrá a <strong>arca.gob.ar</strong> con tu Clave Fiscal.
                </li>
                <li>Abrí «Administrador de Relaciones de Clave Fiscal».</li>
                <li>Elegí «Nueva Relación» y buscá Facturación Electrónica (WSFE).</li>
                <li>
                  Como representante indicá el CUIT{' '}
                  <strong className="mono">{status.delegate_tax_id}</strong> (FactuMov).
                </li>
                <li>Confirmá.</li>
              </ol>
            </Notice>
          )}
          {/* El botón no afirma nada: dispara la verificación igual, y solo si ARCA sigue
              diciendo que no queda anotado el aviso. Si el usuario delegó en otra pestaña
              mientras miraba esta pantalla, esto simplemente verifica y listo. */}
          <button type="button" className="secondary" onClick={claim} disabled={busy}>
            {busy ? 'Consultando ARCA…' : 'Ya delegué en ARCA'}
          </button>
        </>
      )}

      {verified === null && claimed !== null && (
        <Notice kind="warn">
          <strong>Falta un paso nuestro.</strong> Nos avisaste el {formatDate(claimed)} y ARCA
          todavía no nos habilita. Delegar tiene dos partes: vos designás a FactuMov y nosotros
          tenemos que aceptar esa designación en ARCA. Ya estamos en eso —{' '}
          <strong>te avisamos por email en cuanto puedas emitir</strong> y no hace falta que
          hagas nada más.
        </Notice>
      )}
    </div>
  )
}
