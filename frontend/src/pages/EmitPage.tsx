import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiError, api } from '../api/client'
import {
  VOUCHER_TYPE_LABELS,
  type EmitRequest,
  type Invoice,
  type InvoicePreview,
} from '../api/types'
import { DictateDate } from '../components/DictateDate'
import { Notice } from '../components/Notice'
import { SpeakToggle } from '../components/SpeakToggle'
import { formatDate, isoDate, money } from '../format'
import { useResource } from '../hooks/useResource'
import { say, spokenAmount, spokenDate } from '../speak'

/**
 * La pantalla de confirmación de la emisión.
 *
 * **Existe porque emitir es irreversible.** Con `ARCA_ENV=prod`, apretar el botón deja un
 * comprobante con validez legal a nombre de un CUIT real, y no hay forma de deshacerlo desde
 * la app: se anula con una nota de crédito, que FactuMov no emite. Un botón "Emitir" directo
 * en la pantalla del modelo, al lado de "Guardar cambios", habría sido un dedo mal apoyado en
 * un celular.
 *
 * Por eso es una pantalla aparte y no un `window.confirm`: hay que mostrar la letra, el
 * destinatario y el importe exacto, y eso no entra en un diálogo del sistema — que además
 * bloquea el hilo, no se puede estilar, y en algunos navegadores queda suprimido si el
 * usuario marcó "no mostrar más", o sea que la confirmación desaparece sin que nadie se
 * entere. Es la misma decisión que se tomó para el borrado de las tarjetas.
 *
 * Los importes salen del `preview` del backend y no de la cuenta del editor. Las dos dan lo
 * mismo hoy; la diferencia es que este número es el que se va a declarar.
 *
 * **La fecha del comprobante se puede cambiar, y viene con hoy puesto.** Es lo que se emite
 * casi siempre; correrla existe para el papel que tiene que decir otra cosa —se facturó el
 * viernes y se cargó el lunes— y ARCA la admite dentro de una ventana de pocos días. Los
 * extremos los da el `preview` para que el campo no ofrezca una fecha que el servidor rechaza.
 *
 * **Las cuatro fechas pueden llegar dictadas desde la grilla**, colgadas de la query
 * (`?fecha=&desde=&hasta=&vence=`). Es la mitad de "emitir alquiler desde el 1 de agosto":
 * `commands.ts` arma la ruta y esta pantalla la lee. Lo que el comando **no** cambia es que
 * esta pantalla exista y que el botón lo apriete el dedo — la voz llena el formulario, nada
 * más.
 */
export function EmitPage() {
  const { id } = useParams()
  return id ? <EmitScreen key={id} id={id} /> : <Navigate to="/" replace />
}

/** El primer y el último día del mes en curso, y hoy, en el `YYYY-MM-DD` que espera la API. */
function defaultPeriod() {
  const now = new Date()
  return {
    from_date: isoDate(new Date(now.getFullYear(), now.getMonth(), 1)),
    to_date: isoDate(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
    due_date: isoDate(now),
  }
}

/**
 * Una fecha que llegó por la query, si de verdad es una fecha.
 *
 * La query la escribe `emitPath` con lo que entendió el dictado, pero también la puede
 * escribir cualquiera a mano: sin esta verificación, `?fecha=mañana` entraría tal cual al
 * `<input type="date">`, que lo muestra vacío, y el campo quedaría en blanco sin explicación.
 * La forma alcanza —que el día exista lo verificó `parseSpokenDate`, y el rango lo verifica el
 * backend.
 */
function dateParam(params: URLSearchParams, key: string): string | undefined {
  const value = params.get(key)
  return value !== null && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : undefined
}

/**
 * Todo el comprobante, dicho en voz alta.
 *
 * **Es la lectura completa de lo que se va a emitir**, y por eso ocurre acá y no en la grilla:
 * el comando hablado solo conoce lo que se dijo, y lo que hay que confirmar antes de pedir un
 * CAE es lo que la pantalla muestra — la letra que dedujo el backend, el emisor, el cliente, el
 * importe que se va a declarar y las cuatro fechas, tanto las que se dictaron como las que la
 * app puso sola. Un resumen dicho antes de esta pantalla omitiría justamente lo que nadie
 * eligió y nadie revisó.
 *
 * Va en el mismo archivo que el `<dl>` que muestra esos datos, y en el mismo orden, por lo
 * mismo que `outcomeAloud` está pegado a su texto: son la misma respuesta por dos canales, y la
 * que se desactualice va a ser la que quede lejos.
 *
 * El CUIT y el documento **no se dicen**: once dígitos leídos de corrido no los verifica nadie
 * de oído, y alargan la lectura justo antes de lo único que hay que decidir. Quedan en la
 * pantalla, que es donde se comparan.
 *
 * `blocked_reason` va al final, que es donde está el botón: si no se puede emitir, eso es lo
 * que hay que hacer y tiene que ser lo último que quede sonando.
 */
function previewAloud(
  data: InvoicePreview,
  date: string,
  period: { from_date: string; to_date: string; due_date: string },
  today: Date,
): string {
  const lines = [
    `${VOUCHER_TYPE_LABELS[data.voucher_type]}, punto de venta ${data.pos}`,
    `Emite ${data.issuer_name}`,
    `A ${data.customer_name}`,
    `Total ${spokenAmount(data.total)}`,
    `Fecha ${spokenDate(date, today)}`,
  ]
  if (data.needs_service_dates) {
    lines.push(
      `Período desde el ${spokenDate(period.from_date, today)}`,
      `hasta el ${spokenDate(period.to_date, today)}`,
      `Vence el ${spokenDate(period.due_date, today)}`,
    )
  }
  if (data.blocked_reason !== null) lines.push(`No se puede emitir. ${data.blocked_reason}`)
  return `${lines.join('. ')}.`
}

function EmitScreen({ id }: { id: string }) {
  const fetcher = useCallback(
    () => api.get<InvoicePreview>(`/invoice-templates/${id}/preview`),
    [id],
  )
  const preview = useResource(fetcher)
  const navigate = useNavigate()

  const [params] = useSearchParams()
  const spoken = {
    date: dateParam(params, 'fecha'),
    from_date: dateParam(params, 'desde'),
    to_date: dateParam(params, 'hasta'),
    due_date: dateParam(params, 'vence'),
  }
  const dictated = Object.values(spoken).some((value) => value !== undefined)

  // Lo dictado pisa al default campo por campo y no en bloque: "emitir alquiler vence el 10"
  // dice una sola de las tres fechas del período, y las otras dos siguen siendo el mes en
  // curso. Es un inicializador perezoso, así que la query se lee una vez y después el estado
  // es del usuario — si corrige un campo a mano, un re-render no se lo pisa de vuelta.
  const [period, setPeriod] = useState(() => {
    const fallback = defaultPeriod()
    return {
      from_date: spoken.from_date ?? fallback.from_date,
      to_date: spoken.to_date ?? fallback.to_date,
      due_date: spoken.due_date ?? fallback.due_date,
    }
  })
  // `undefined` = el usuario no la tocó ni la dictó, o sea que vale la que propone el preview.
  // No se inicializa con `isoDate(new Date())` aunque daría lo mismo: la fecha que se va a
  // declarar tiene una sola fuente, y es la misma que calculó los extremos de la ventana.
  const [chosenDate, setChosenDate] = useState<string | undefined>(spoken.date)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    // El guard no es decorativo: sin él, un segundo submit mientras el primero está en vuelo
    // emite dos facturas. El `disabled` del botón cubre el click, pero no el Enter en un
    // campo del formulario.
    if (busy) return
    setBusy(true)
    setError(undefined)
    const body: EmitRequest = {
      ...(preview.data?.needs_service_dates ? period : {}),
      ...(chosenDate !== undefined ? { date: chosenDate } : {}),
    }
    try {
      const invoice = await api.post<Invoice>(`/invoice-templates/${id}/emit`, body)
      // `replace` para que el "atrás" del navegador no vuelva a la pantalla de confirmar una
      // emisión que ya ocurrió.
      navigate(`/facturas/${invoice.id}`, { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : 'No se pudo emitir.')
      setBusy(false)
    }
  }

  const data = preview.data

  /**
   * Apenas la pantalla tiene qué mostrar, la app la lee entera. **Una sola vez.**
   *
   * Se lee lo que hay cuando la pantalla aparece, que es lo que se va a emitir si el usuario no
   * toca nada. Corregir una fecha después no vuelve a disparar las siete líneas: esa corrección
   * ya tiene su propia respuesta hablada —la del micrófono del campo, que dice la fecha
   * sola— y releer todo en cada retoque terminaría con el usuario apagando la voz, y con eso
   * perdiendo la lectura, que es lo que vale.
   *
   * La guarda es una ref y no una lista de dependencias recortada. Recortarla diría lo mismo y
   * escondería que el efecto usa `period` y `chosenDate`; así el linter ve todo lo que se usa y
   * "una sola vez" queda escrito en el código en vez de deducido de lo que falta.
   */
  const alreadyRead = useRef(false)
  useEffect(() => {
    if (data === undefined || alreadyRead.current) return
    alreadyRead.current = true
    say(previewAloud(data, chosenDate ?? data.date, period, new Date()))
  }, [data, chosenDate, period])

  // Los dos fracasos posibles también se dicen: no poder cargar el preview y no poder emitir.
  // Es el mismo criterio que los errores del micrófono — el que no está mirando la pantalla
  // está esperando algo que no va a llegar, y el segundo es además el momento más tenso de la
  // app, con el dedo recién levantado del botón.
  useEffect(() => {
    if (preview.error !== undefined) say(preview.error)
  }, [preview.error])
  useEffect(() => {
    if (error !== undefined) say(error)
  }, [error])

  return (
    <div className="page">
      <Link className="back" to={`/modelos/${id}`}>
        ← Modelo
      </Link>
      {/* El interruptor de la voz va acá **y** en la grilla: esta es la pantalla que más
          habla, así que tiene que ser una en la que se pueda callar. Es el mismo botón y la
          misma preferencia, y apagarlo corta la lectura en curso. */}
      <div className="page-head">
        <h1>Emitir</h1>
        <SpeakToggle />
      </div>

      <Notice kind="error">{preview.error ?? error}</Notice>
      {preview.loading && data === undefined && <p className="muted">Cargando…</p>}

      {data !== undefined && (
        <form className="card stack" onSubmit={onSubmit}>
          <dl className="summary">
            <div>
              <dt>Comprobante</dt>
              <dd>
                Factura {data.voucher_type} — punto de venta {data.pos}
              </dd>
            </div>
            <div>
              <dt>Emite</dt>
              <dd>
                {data.issuer_name} <span className="muted">({data.issuer_tax_id})</span>
              </dd>
            </div>
            <div>
              <dt>A</dt>
              <dd>
                {data.customer_name} <span className="muted">({data.customer_doc_number})</span>
              </dd>
            </div>
            <div>
              <dt>Total</dt>
              <dd className="amount">{money.format(Number(data.total))}</dd>
            </div>
          </dl>

          {/* Que las fechas hayan venido dictadas **se dice**. La pantalla es idéntica con
              hoy puesto por default que con una fecha que entendió el micrófono, y son dos
              cosas distintas: una la eligió la app y la otra la entendió de una frase. Si
              entendió mal, este renglón es lo que manda a mirar los campos antes de apretar. */}
          {dictated && (
            <p className="totals-note" style={{ margin: 0 }}>
              Las fechas de abajo las puso el dictado. Revisalas antes de emitir.
            </p>
          )}

          <DictateDate
            id="date"
            label="Fecha del comprobante"
            value={chosenDate ?? data.date}
            min={data.min_date}
            max={data.max_date}
            onChange={setChosenDate}
            hint={
              /* `min`/`max` los pone el navegador, pero el usuario puede tipear igual y el
                 selector nativo del celular no siempre los respeta: el 422 del backend es el
                 que manda. Decir cuál es la ventana evita descubrirla a fuerza de rechazos.

                 El dictado no la respeta tampoco, y a propósito: si se entendió una fecha
                 fuera de la ventana hay que verla escrita para saber que hay que corregirla. */
              <p className="muted" style={{ margin: '0.35rem 0 0', fontSize: '0.82rem' }}>
                ARCA la acepta entre el {formatDate(data.min_date)} y el{' '}
                {formatDate(data.max_date)}, y nunca anterior a la del último comprobante de esta
                serie.
              </p>
            }
          />

          {data.needs_service_dates && (
            <>
              {/* Solo para servicios: ARCA exige el período facturado y el vencimiento del
                  pago, y los rechaza si falta alguno. Vienen con el mes en curso puesto,
                  que es lo que se factura el 99% de las veces. */}
              <div className="row">
                <DictateDate
                  id="from_date"
                  label="Período desde"
                  value={period.from_date}
                  onChange={(from_date) => setPeriod({ ...period, from_date })}
                />
                <DictateDate
                  id="to_date"
                  label="Hasta"
                  value={period.to_date}
                  onChange={(to_date) => setPeriod({ ...period, to_date })}
                />
              </div>
              <DictateDate
                id="due_date"
                label="Vencimiento del pago"
                value={period.due_date}
                onChange={(due_date) => setPeriod({ ...period, due_date })}
              />
            </>
          )}

          {data.blocked_reason !== null ? (
            <Notice kind="warn">{data.blocked_reason}</Notice>
          ) : (
            <Notice kind="warn">
              Esto le pide el CAE a ARCA y <strong>no se puede deshacer</strong>. Para dejar sin
              efecto una factura emitida hace falta una nota de crédito, que se hace en el sitio
              de ARCA.
            </Notice>
          )}

          <button type="submit" disabled={busy || data.blocked_reason !== null}>
            {busy ? 'Emitiendo…' : `Emitir factura ${data.voucher_type}`}
          </button>
        </form>
      )}
    </div>
  )
}
