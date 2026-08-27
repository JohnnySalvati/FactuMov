import { useNavigate } from 'react-router'

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
  lineAmount,
  money,
  newLine,
  totals,
  type LineForm,
  type TemplateForm,
} from '../forms/templateForm'
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
  busy,
  error,
}: {
  value: TemplateForm
  onChange: (form: TemplateForm) => void
  fiscalIdentities: FiscalIdentity[]
  customers: Customer[]
  onSubmit: () => void
  submitLabel: string
  busy: boolean
  error?: string
}) {
  const navigate = useNavigate()
  const sums = totals(value)

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

        <div className="row">
          <div>
            <label htmlFor="t-voucher">Comprobante</label>
            <select
              id="t-voucher"
              value={value.voucher_type}
              onChange={(event) => patch({ voucher_type: event.target.value as VoucherType })}
            >
              {Object.entries(VOUCHER_TYPE_LABELS).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="narrow">
            <label htmlFor="t-pos">Punto de venta</label>
            <input
              id="t-pos"
              inputMode="numeric"
              value={value.pos}
              onChange={(event) => patch({ pos: event.target.value })}
            />
          </div>
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

            <div className="row">
              <div className="narrow">
                <label htmlFor={`${line.key}-qty`}>Cantidad</label>
                <input
                  id={`${line.key}-qty`}
                  inputMode="decimal"
                  value={line.quantity}
                  onChange={(event) => patchLine(line.key, { quantity: event.target.value })}
                />
              </div>
              <div>
                <label htmlFor={`${line.key}-price`}>Precio unitario</label>
                <input
                  id={`${line.key}-price`}
                  inputMode="decimal"
                  placeholder="0,00"
                  value={line.unit_price}
                  onChange={(event) => patchLine(line.key, { unit_price: event.target.value })}
                />
              </div>
              <div className="narrow">
                <label htmlFor={`${line.key}-iva`}>IVA</label>
                <select
                  id={`${line.key}-iva`}
                  value={line.iva_aliquot}
                  onChange={(event) =>
                    patchLine(line.key, {
                      iva_aliquot: Number(event.target.value) as IvaAliquot,
                    })
                  }
                >
                  {Object.entries(IVA_ALIQUOT_LABELS).map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="line-amount">
              <span className="muted">Importe</span>
              <strong>{money.format(lineAmount(line))}</strong>
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

      <Notice kind="error">{error}</Notice>

      <button type="submit" disabled={busy}>
        {busy ? 'Guardando…' : submitLabel}
      </button>
    </form>
  )
}
