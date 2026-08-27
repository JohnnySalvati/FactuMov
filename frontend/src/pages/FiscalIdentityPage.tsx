import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  CONDICION_IVA_LABELS,
  CondicionIva,
  type DelegationStatus,
  type FiscalIdentity,
} from '../api/types'
import { Notice } from '../components/Notice'

/** Consumidor final no puede emitir, y el backend lo rechaza con un 422. Se saca de la lista
 *  para no ofrecer una opción que siempre falla. */
const EMISOR_CONDICIONES = [
  CondicionIva.INSCRIPTO,
  CondicionIva.MONOTRIBUTO,
  CondicionIva.EXENTO,
] as const

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
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
          <FiscalIdentityForm
            editing={identity ?? undefined}
            onCreated={() => navigate('/identidades')}
            onUpdated={setIdentity}
          />
          {/* La verificación solo tiene sentido sobre una fila que ya existe: la llamada a ARCA
              va contra el CUIT guardado. */}
          {identity !== null && <DelegationCard identity={identity} onChanged={setIdentity} />}
        </>
      )}
    </div>
  )
}

function FiscalIdentityForm({
  editing,
  onCreated,
  onUpdated,
}: {
  editing?: FiscalIdentity
  onCreated: () => void
  onUpdated: (identity: FiscalIdentity) => void
}) {
  const [name, setName] = useState(editing?.name ?? '')
  const [taxId, setTaxId] = useState(editing?.tax_id ?? '')
  const [condicionIva, setCondicionIva] = useState<CondicionIva>(
    editing?.condicion_iva ?? CondicionIva.INSCRIPTO,
  )
  const [address, setAddress] = useState(editing?.address ?? '')
  const [error, setError] = useState<string>()
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(undefined)
    setSaved(false)
    const body = {
      name,
      tax_id: taxId.replace(/\D/g, ''),
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

  /** Cualquier cambio invalida el "Guardado": dejarlo puesto es la forma más barata de que
   *  alguien salga de la pantalla creyendo que guardó lo que acaba de tipear. */
  function edited() {
    setSaved(false)
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
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

      <div className="row">
        <div>
          <label htmlFor="fi-tax-id">CUIT</label>
          {/* Los guiones se limpian al mandar: la columna guarda once dígitos, y hacer que el
              usuario los tipee sin guiones es pedirle que se adapte al esquema. */}
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
        <div>
          <label htmlFor="fi-condicion">Condición frente al IVA</label>
          <select
            id="fi-condicion"
            value={condicionIva}
            onChange={(event) => {
              edited()
              setCondicionIva(Number(event.target.value) as CondicionIva)
            }}
          >
            {EMISOR_CONDICIONES.map((value) => (
              <option key={value} value={value}>
                {CONDICION_IVA_LABELS[value]}
              </option>
            ))}
          </select>
        </div>
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

/** Cada cuánto vale la pena volver a preguntarle a ARCA por una delegación ya verificada.
 *
 *  No es un vencimiento: es cada cuánto se repregunta sola. La delegación se revoca del lado de
 *  ARCA sin avisarnos, y sin esto la app se enteraría recién con un rechazo al emitir — o sea
 *  en el peor momento posible. Una semana es holgado porque revocar no es frecuente, y el costo
 *  es una llamada por identidad por semana. */
const STALE_AFTER_MS = 7 * 24 * 60 * 60 * 1000

function needsChecking(verifiedAt: string | null): boolean {
  return verifiedAt === null || Date.now() - new Date(verifiedAt).getTime() > STALE_AFTER_MS
}

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
  const [busy, setBusy] = useState(() => needsChecking(identity.delegation_verified_at))
  // La última respuesta de ARCA. Se guarda por un solo dato: `delegate_tax_id`, el CUIT al que
  // hay que autorizar. No se escribe acá a mano aunque sea el mismo siempre — sale de
  // `arca.get_delegate_tax_id()`, que lo lee del certificado, y una segunda copia es
  // exactamente cómo se llega a que la pantalla diga un CUIT y el sistema espere otro.
  const [status, setStatus] = useState<DelegationStatus>()

  const run = useCallback(
    async (path: 'verify-delegation' | 'claim-delegation') => {
      try {
        const result = await api.post<DelegationStatus>(
          `/fiscal-identities/${identity.id}/${path}`,
        )
        setStatus(result)
        setError(undefined)
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
  // porque el certificado de ARCA es uno solo para toda la app.
  const checkedOnMount = useRef(false)
  useEffect(() => {
    if (checkedOnMount.current) return
    if (!needsChecking(identity.delegation_verified_at)) return
    checkedOnMount.current = true
    // Silencioso a propósito: esto no lo pidió nadie. Si ARCA no contesta, la pantalla se queda
    // mostrando lo que ya sabía, que sigue siendo cierto. El cartel rojo queda para las dos
    // acciones que el usuario sí eligió.
    void run('verify-delegation').catch(() => {})
  }, [run, identity.delegation_verified_at])

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
