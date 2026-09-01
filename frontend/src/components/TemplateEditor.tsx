import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router'

import { money } from '../format'
import {
  CONCEPTO_LABELS,
  IVA_ALIQUOT_LABELS,
  IvaAliquot,
  VOUCHER_TYPE_LABELS,
  type Concepto,
  type Customer,
  type FiscalIdentity,
  type VoucherType,
} from '../api/types'
import {
  formVoucherType,
  lineAmount,
  newLine,
  totals,
  unitPriceFields,
  type LineForm,
  type TemplateForm,
} from '../forms/templateForm'
import { usePointsOfSale, type PointsOfSaleState } from '../hooks/usePointsOfSale'
import { useCustomEmailEnabled } from '../subscription/useCustomEmailEnabled'
import { Notice } from './Notice'
import { PickerField } from './PickerField'

/**
 * El formulario del modelo. Es **controlado desde afuera**: el estado vive en la pantalla que
 * lo usa. La alternativa —que se lo guarde adentro y lo devuelva al guardar— no serviría para
 * la pantalla de importación, que después de dar de alta un cliente tiene que meterle el id al
 * formulario que el usuario ya empezó a tocar.
 *
 * La forma del estado, las cuentas y la conversión al payload viven en `forms/templateForm.ts`
 * — ver ahí por qué están separadas.
 */
export function TemplateEditor({
  value,
  onChange,
  fiscalIdentities,
  customers,
  onSubmit,
  submitLabel,
  canSubmit = true,
  busy,
  error,
}: {
  value: TemplateForm
  onChange: (form: TemplateForm) => void
  fiscalIdentities: FiscalIdentity[]
  customers: Customer[]
  onSubmit: () => void
  submitLabel: string
  /**
   * Si hay algo para guardar. Con `false` **el botón no se dibuja**, no se dibuja apagado.
   *
   * Un modelo abierto y no tocado no tiene nada que guardar, y ofrecer "Guardar cambios"
   * igual le pregunta al usuario si quiere guardar unos cambios que no hizo — que es la forma
   * más barata de hacerlo dudar de si los hizo. Apagado sería la mitad del arreglo: el botón
   * seguiría estando y seguiría siendo lo primero que se ve al final del formulario.
   *
   * El default es `true` porque un modelo nuevo siempre se puede guardar: ahí el formulario
   * no se compara contra nada, no existe todavía.
   */
  canSubmit?: boolean
  busy: boolean
  error?: string
}) {
  const navigate = useNavigate()

  // La letra del comprobante **se deduce, no se elige**: la decide ARCA a partir de la
  // condición frente al IVA del emisor y de la del receptor. Antes había un desplegable con
  // seis opciones, cinco de las cuales eran siempre incorrectas para un par dado; ahora hay un
  // renglón que dice cuál sale. El backend hace la misma cuenta y es el que manda — acá se
  // repite para poder mostrarla, sumar y convertir el precio mientras el usuario todavía no
  // guardó nada. La cuenta vive en `templateForm` porque las pantallas la necesitan igual para
  // guardar: es la que decide si el precio de la línea va neto o con el IVA adentro.
  const voucherType = formVoucherType(value, fiscalIdentities, customers)

  // Los puntos de venta del emisor elegido. Se piden acá y no en las pantallas porque el que
  // sabe qué identidad fiscal está elegida en este momento es el formulario.
  const pointsOfSale = usePointsOfSale(value.fiscal_identity_id)

  const sums = totals(value, voucherType)

  function patch(changes: Partial<TemplateForm>) {
    onChange({ ...value, ...changes })
  }

  function patchLine(key: string, changes: Partial<LineForm>) {
    patch({
      lines: value.lines.map((line) => (line.key === key ? { ...line, ...changes } : line)),
    })
  }

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault()
        // El guard además del botón que no está: sin botón de submit, un `<form>` con un solo
        // campo de texto se envía igual apretando Enter. Sin esto, el Enter mandaría un PATCH
        // que no cambia nada y la pantalla diría "Guardado." sobre un guardado que no ocurrió.
        if (!canSubmit) return
        onSubmit()
      }}
    >
      <div className="card stack">
        <div>
          <label htmlFor="t-name">Nombre del modelo</label>
          <input
            id="t-name"
            required
            maxLength={200}
            placeholder="Alquiler mensual"
            value={value.name}
            onChange={(event) => patch({ name: event.target.value })}
          />
        </div>

        <PickerField
          label="Emito como"
          options={fiscalIdentities.map((identity) => ({
            id: identity.id,
            title: identity.name,
            subtitle: identity.tax_id,
          }))}
          value={value.fiscal_identity_id}
          onChange={(id) => patch({ fiscal_identity_id: id })}
          // El "mantener apretado" aterriza en la pantalla de esa identidad fiscal. El id
          // viaja en el path justamente para que esto sea un link común.
          onEditCurrent={(id) => navigate(`/identidades/${id}`)}
          editHint="Tocá para cambiar · mantené apretado para editarla"
          manageTo="/identidades"
          manageLabel="Administrar identidades fiscales"
          emptyLabel="Elegí una identidad fiscal"
        />

        <PickerField
          label="Le facturo a"
          options={customers.map((customer) => ({
            id: customer.id,
            title: customer.name,
            subtitle: customer.doc_number,
          }))}
          value={value.customer_id}
          onChange={(id) => patch({ customer_id: id })}
          onEditCurrent={(id) => navigate(`/clientes/${id}`)}
          editHint="Tocá para cambiar · mantené apretado para editarlo"
          manageTo="/clientes"
          manageLabel="Administrar clientes"
          emptyLabel="Elegí un cliente"
        />

        <div className="derived">
          <span className="field-label">Comprobante</span>
          {voucherType !== undefined ? (
            <strong>{VOUCHER_TYPE_LABELS[voucherType]}</strong>
          ) : (
            <span className="muted">Elegí el emisor y el cliente</span>
          )}
          <span className="field-hint">
            La define ARCA según la condición frente al IVA de los dos, no se elige.
          </span>
        </div>

        <PointOfSaleField
          value={value.pos}
          onChange={(pos) => patch({ pos })}
          state={pointsOfSale}
        />

        <div className="row">
          <div>
            <label htmlFor="t-concepto">Concepto</label>
            <select
              id="t-concepto"
              value={value.concepto}
              onChange={(event) => patch({ concepto: event.target.value as Concepto })}
            >
              {Object.entries(CONCEPTO_LABELS).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="card stack">
        <h2>Detalle</h2>

        {value.lines.map((line, index) => (
          <div className="line" key={line.key}>
            <div className="line-head">
              <span className="line-number">#{index + 1}</span>
              <button
                type="button"
                className="icon"
                aria-label={`Eliminar la línea ${index + 1}`}
                title="Eliminar la línea"
                // Sin confirmación a propósito: acá no hay nada guardado todavía y volver a
                // escribir una línea cuesta menos que el diálogo. El tacho de las tarjetas,
                // que sí borra algo de la base, tiene dos pasos.
                onClick={() =>
                  patch({ lines: value.lines.filter((other) => other.key !== line.key) })
                }
              >
                🗑
              </button>
            </div>

            <input
              aria-label={`Descripción de la línea ${index + 1}`}
              placeholder="Descripción"
              maxLength={200}
              value={line.description}
              onChange={(event) => patchLine(line.key, { description: event.target.value })}
            />

            <LineFields
              line={line}
              voucherType={voucherType}
              onChange={(changes) => patchLine(line.key, changes)}
            />

            <div className="line-amount">
              <span className="muted">Importe</span>
              <strong>{money.format(lineAmount(line, voucherType))}</strong>
            </div>
          </div>
        ))}

        <button
          type="button"
          className="secondary"
          onClick={() => patch({ lines: [...value.lines, newLine()] })}
        >
          + Agregar línea
        </button>

        <div className="totals">
          <div>
            <span className="muted">Neto</span>
            <span>{money.format(sums.net)}</span>
          </div>
          <div>
            <span className="muted">IVA</span>
            <span>{money.format(sums.iva)}</span>
          </div>
          <div className="totals-total">
            <span>Total</span>
            <strong>{money.format(sums.total)}</strong>
          </div>
        </div>
        <p className="totals-note">
          El total es una cuenta de esta pantalla para que veas lo que estás cargando. El
          importe que vale es el que autorice ARCA al emitir.
        </p>
      </div>

      <EmailCard value={value} onChange={patch} />

      <Notice kind="error">{error}</Notice>

      {canSubmit && (
        <button type="submit" disabled={busy}>
          {busy ? 'Guardando…' : submitLabel}
        </button>
      )}
    </form>
  )
}

/**
 * El mail con el que se manda la factura emitida de este modelo: asunto y cuerpo.
 *
 * **Vacío significa "el mail de FactuMov"**, no un mail en blanco, y por eso los dos campos
 * van con el texto por default de placeholder en vez de sembrados con él. Sembrarlos sería
 * convertir a todo el mundo en alguien que escribió un texto propio: el día que se corrija la
 * redacción del mail de la app, los modelos que nunca se tocaron seguirían mandando la copia
 * vieja. Y en el editor, la diferencia entre gris y negro es la que dice si esto es tuyo.
 *
 * **Es un texto fijo, sin variables**, y el placeholder lo deja a la vista: lo que se escriba
 * sale igual en todas las facturas de este modelo. El número del comprobante, el importe y el
 * CAE están en el PDF adjunto, que va siempre — el mail es el acompañamiento, no el
 * comprobante. La alternativa (aceptar `{cliente}`, `{total}`) es una plantilla que hay que
 * enseñar y que se rompe en silencio con una llave mal cerrada, sobre un mail que sale para
 * afuera.
 *
 * Con el plan Free los campos se ven pero no se editan, y el aviso dice por qué. Se ven, y no
 * se esconden, porque esconderlos deja al que no es Pro sin manera de enterarse de que esto
 * existe — que es exactamente la información que la pantalla del plan necesita que tenga. Y si
 * hay un texto guardado de cuando la cuenta era Pro, aparece con su aviso propio: sigue ahí,
 * no se está usando, y se puede borrar aunque no se pueda editar.
 *
 * En el mismo archivo que el editor por lo mismo que `LineFields` y `PointOfSaleField`: no lo
 * usa nadie más.
 */
/** El cuerpo por default, con datos de ejemplo. Es el placeholder del campo de texto. */
const PLACEHOLDER_BODY = `Hola,

Te adjuntamos la factura B 0001-00000123 de Fulano SRL por $ 42.350,00.

El comprobante está autorizado por ARCA; el CAE y su vencimiento figuran al pie del PDF.`

function EmailCard({
  value,
  onChange,
}: {
  value: TemplateForm
  onChange: (changes: Partial<TemplateForm>) => void
}) {
  const enabled = useCustomEmailEnabled()
  const hasOwnText = value.email_subject.trim() !== '' || value.email_body.trim() !== ''

  return (
    <div className="card stack">
      <h2>Mail al cliente</h2>

      {enabled ? (
        <p className="field-hint" style={{ margin: 0 }}>
          Lo que le llega al cliente cuando le mandás una factura emitida con este modelo. Si
          los dejás vacíos mandamos el texto de FactuMov, que es el que está en gris.
        </p>
      ) : (
        <Notice kind="warn">
          Escribir el texto del mail es del plan Pro — <Link to="/plan">ver tu plan</Link>. Con
          el plan Free se manda el texto de FactuMov, que lleva el número del comprobante, tu
          razón social y el importe.
        </Notice>
      )}

      <div>
        <label htmlFor="t-email-subject">Asunto</label>
        <input
          id="t-email-subject"
          maxLength={200}
          disabled={!enabled}
          placeholder="Factura B 0001-00000123 de Fulano SRL"
          value={value.email_subject}
          onChange={(event) => onChange({ email_subject: event.target.value })}
        />
      </div>

      <div>
        <label htmlFor="t-email-body">Texto</label>
        <textarea
          id="t-email-body"
          rows={5}
          maxLength={2000}
          disabled={!enabled}
          placeholder={PLACEHOLDER_BODY}
          value={value.email_body}
          onChange={(event) => onChange({ email_body: event.target.value })}
        />
        <span className="field-hint">
          Es un texto fijo: sale igual en todas las facturas de este modelo. El número, el
          importe y el CAE van en el PDF, que se adjunta siempre.
        </span>
      </div>

      {!enabled && hasOwnText && (
        <>
          <p className="totals-note" style={{ margin: 0 }}>
            Este texto lo escribiste cuando tenías Pro. Sigue guardado y vuelve solo si volvés
            a Pro; mientras tanto se manda el de FactuMov.
          </p>
          {/* Borrarlo se permite siempre, también sin Pro: lo que deja en su lugar es el mail
              por default, así que nunca puede empeorar nada. Es la única salida del que ya no
              puede editarlo — el backend hace la misma distinción. */}
          <button
            type="button"
            className="secondary"
            onClick={() => onChange({ email_subject: '', email_body: '' })}
          >
            Borrar el texto que tenía
          </button>
        </>
      )}
    </div>
  )
}

/**
 * Los cuatro campos de una línea: cantidad, precio sin IVA, alícuota y precio con IVA.
 *
 * **Los dos precios son la misma caja vista de los dos lados.** Se carga cualquiera de ellos y
 * el otro aparece calculado; escribir en el calculado invierte los papeles. El estado guarda
 * uno solo —cuál, lo dice `price_includes_iva`— y `unitPriceFields` arma el par, así que las
 * dos cajas nunca pueden discrepar entre sí ni con la alícuota.
 *
 * Por qué los dos y no solo el que se guarda: el que carga un precio piensa en el precio que
 * tiene —el de la lista, el que le dice al cliente— y no en si la letra que le va a tocar lo
 * quiere neto o con el IVA adentro. Ver `unitPriceFields` para lo que eso arregla al cambiar
 * de cliente.
 *
 * En una C las dos columnas muestran el mismo número: no hay IVA que sacar ni que poner, y la
 * alícuota que quede cargada no se declara. Es lo mismo que hace `compute_totals` allá.
 *
 * Fuera de `TemplateEditor` pero en el mismo archivo, por el mismo motivo que
 * `PointOfSaleField`: no lo usa nadie más y sacarlo a otro archivo lo alejaría del formulario
 * del que es parte.
 */
function LineFields({
  line,
  voucherType,
  onChange,
}: {
  line: LineForm
  voucherType: VoucherType | undefined
  onChange: (changes: Partial<LineForm>) => void
}) {
  const prices = unitPriceFields(line, voucherType)

  return (
    <>
      <div className="line-fields">
        <div>
          <label htmlFor={`${line.key}-qty`}>Cantidad</label>
          <input
            id={`${line.key}-qty`}
            inputMode="decimal"
            value={line.quantity}
            onChange={(event) => onChange({ quantity: event.target.value })}
          />
        </div>
        <div>
          <label htmlFor={`${line.key}-net`}>Precio sin IVA</label>
          <input
            id={`${line.key}-net`}
            inputMode="decimal"
            placeholder="0,00"
            value={prices.net}
            // Escribir acá no solo cambia el precio: además declara que **este** es el que se
            // cargó, y el de al lado pasa a ser el calculado.
            onChange={(event) =>
              onChange({ unit_price: event.target.value, price_includes_iva: false })
            }
          />
        </div>
        <div>
          <label htmlFor={`${line.key}-iva`}>IVA</label>
          <select
            id={`${line.key}-iva`}
            value={line.iva_aliquot}
            onChange={(event) =>
              onChange({ iva_aliquot: Number(event.target.value) as IvaAliquot })
            }
          >
            {Object.entries(IVA_ALIQUOT_LABELS).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${line.key}-gross`}>Precio c/IVA</label>
          <input
            id={`${line.key}-gross`}
            inputMode="decimal"
            placeholder="0,00"
            value={prices.gross}
            onChange={(event) =>
              onChange({ unit_price: event.target.value, price_includes_iva: true })
            }
          />
        </div>
      </div>
      <span className="field-hint">
        Cargá el precio donde te quede cómodo: el otro se calcula con la alícuota.
      </span>
    </>
  )
}

/**
 * El punto de venta: un desplegable con lo que ARCA tiene dado de alta, y una caja de texto
 * cuando no hay lista que ofrecer.
 *
 * **Era un input libre con `1` de default**, que es la peor combinación posible: el número lo
 * da de alta el usuario en ARCA —no acá— así que no hay forma de que lo deduzca de la pantalla,
 * y un default plausible hace que ni siquiera se pregunte cuál va. El que emite con el punto de
 * venta 5 se enteraba recién al pedir el CAE, con un rechazo de ARCA.
 *
 * Los cinco estados sin lista caen todos en el mismo input libre, y eso es a propósito: no
 * poder mostrar la lista **no puede impedir guardar un modelo**. Lo que cambia entre ellos es
 * el texto de abajo, que es lo único que distingue "andá a darlo de alta en ARCA" de "esperá y
 * probá de nuevo".
 *
 * Fuera de `TemplateEditor` pero en el mismo archivo: no lo usa nadie más, y sacarlo a su
 * propio archivo por prolijidad dejaría el campo lejos del formulario del que es parte.
 */
function PointOfSaleField({
  value,
  onChange,
  state,
}: {
  value: string
  onChange: (pos: string) => void
  state: PointsOfSaleState
}) {
  const points = state.status === 'ready' ? state.points : []
  const onlyPoint = points.length === 1 ? points[0] : undefined

  // Con un solo punto de venta no hay nada que elegir y se completa solo; con varios no se
  // elige por el usuario, que sería adivinar cuál. **Solo toca el campo vacío**: un modelo
  // guardado con el 5 lo conserva aunque hoy ARCA ofrezca otro, porque pisarlo cambiaría en
  // silencio con qué numeración emite algo que ya estaba andando.
  useEffect(() => {
    if (value === '' && onlyPoint !== undefined) onChange(String(onlyPoint.number))
  }, [value, onlyPoint, onChange])

  if (points.length > 0) {
    // El valor guardado puede no estar en la lista: un punto de venta dado de baja en ARCA
    // después de que se creó el modelo, o uno que se cargó a mano cuando ARCA no contestaba.
    // Se agrega como opción igual —si no, el `<select>` mostraría otro número sin que nadie lo
    // haya cambiado— y el aviso explica por qué está marcado.
    const known = points.some((point) => String(point.number) === value)
    // El tipo de emisión solo aparece cuando desempata. Con todos iguales es ruido en un
    // desplegable que en el celular ya está apretado.
    const showTypes = new Set(points.map((point) => point.emission_type)).size > 1

    return (
      <div>
        <label htmlFor="t-pos">Punto de venta</label>
        <div className="narrow">
          <select id="t-pos" value={value} onChange={(event) => onChange(event.target.value)}>
            {value === '' && <option value="">Elegí uno</option>}
            {!known && value !== '' && <option value={value}>{value}</option>}
            {points.map((point) => (
              <option key={point.number} value={String(point.number)}>
                {showTypes ? `${point.number} · ${point.emission_type}` : point.number}
              </option>
            ))}
          </select>
        </div>
        <span className="field-hint">
          {!known && value !== ''
            ? `El ${value} no figura entre los puntos de venta de este CUIT en ARCA. ` +
              'Si es el que usás, revisalo allá antes de emitir.'
            : 'Los que tenés dados de alta en ARCA para este CUIT.'}
        </span>
      </div>
    )
  }

  return (
    <div>
      <label htmlFor="t-pos">Punto de venta</label>
      <div className="narrow">
        <input
          id="t-pos"
          inputMode="numeric"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
      <span className="field-hint">{HINTS[state.status]}</span>
    </div>
  )
}

/** El texto de abajo del campo cuando no hay lista. Uno por estado — ver `PointOfSaleField`. */
const HINTS: Record<PointsOfSaleState['status'], string> = {
  idle: 'Elegí desde qué identidad fiscal emitís y traemos los de ARCA.',
  loading: 'Buscando en ARCA los puntos de venta de este CUIT…',
  // `ready` acá es siempre la lista vacía: con puntos, el componente sale por la otra rama.
  ready:
    'Este CUIT no tiene ningún punto de venta dado de alta en ARCA. Dalo de alta allá y volvé ' +
    'a entrar, o escribí el número si ya lo sabés.',
  notDelegated:
    'Sin la delegación no podemos preguntarle a ARCA cuáles tenés. Verificala en la identidad ' +
    'fiscal y volvé.',
  unavailable: 'No pudimos consultarle a ARCA cuáles tenés. Escribí el número que usás.',
}
