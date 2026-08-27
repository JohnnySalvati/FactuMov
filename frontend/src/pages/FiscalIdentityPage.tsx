import { useEffect, useState, type FormEvent } from 'react'
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
          {identity !== null && <DelegationCard identity={identity} onVerified={setIdentity} />}
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
 * El estado de la delegación y el botón para verificarla.
 *
 * `delegation_verified_at` dice "esto era verdad en esta fecha", no "esto es verdad": ARCA
 * permite revocar la delegación sin avisarnos. Por eso el botón sigue estando aunque ya esté
 * verificada, y la fecha se muestra siempre.
 */
function DelegationCard({
  identity,
  onVerified,
}: {
  identity: FiscalIdentity
  onVerified: (identity: FiscalIdentity) => void
}) {
  const [status, setStatus] = useState<DelegationStatus>()
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  async function verify() {
    setBusy(true)
    setError(undefined)
    try {
      const result = await api.post<DelegationStatus>(
        `/fiscal-identities/${identity.id}/verify-delegation`,
      )
      setStatus(result)
      // Solo hay algo nuevo que guardar cuando dio que sí: es el único caso en que el backend
      // escribió el timestamp.
      if (result.granted) {
        onVerified({ ...identity, delegation_verified_at: result.delegation_verified_at })
      }
    } catch (caught) {
      // El 502 es "no se pudo preguntar", que no es lo mismo que "no estás delegado" — eso
      // último llega como un 200 con `granted: false`. Mezclarlos haría que un ARCA caído se
      // vea como una delegación faltante, y el usuario iría a otorgar una que ya tiene.
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo verificar.')
    } finally {
      setBusy(false)
    }
  }

  const verified = identity.delegation_verified_at

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
      </div>

      <button type="button" className="secondary" onClick={verify} disabled={busy}>
        {busy ? 'Consultando ARCA…' : 'Verificar ahora'}
      </button>

      {error && <Notice kind="error">{error}</Notice>}

      {status && !status.granted && (
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
            <li>Confirmá y volvé a apretar «Verificar ahora».</li>
          </ol>
        </Notice>
      )}

      {status?.granted && <Notice kind="ok">Listo, ya podés emitir con este CUIT.</Notice>}
    </div>
  )
}
