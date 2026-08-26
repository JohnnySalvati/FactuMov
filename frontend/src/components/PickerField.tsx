import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { useLongPress } from '../hooks/useLongPress'

export interface PickerOption {
  id: string
  title: string
  subtitle?: string
}

/**
 * Un campo que se elige de una lista, con dos gestos encima.
 *
 * **Tocar** abre la lista para cambiar el valor. **Mantener apretado** entra a editar el que
 * está elegido. Los dos van sobre el mismo elemento a propósito: adentro del modelo, la
 * identidad fiscal y el cliente son un dato del modelo *y* una entidad propia, y el usuario
 * llega a las dos cosas desde donde las está mirando en vez de tener que acordarse de en qué
 * pantalla vivía cada una.
 *
 * La contra del gesto es que es invisible, así que hay un renglón que lo dice. No alcanza con
 * eso solo: `useLongPress` engancha además el `contextmenu`, que es la misma acción para el
 * botón derecho y para el teclado.
 *
 * No es un `<select>` aunque se le parezca. El nativo abre el picker del sistema —que en el
 * celular está muy bien— pero no deja colgarle un gesto propio ni mostrar dos renglones por
 * opción, y acá hacen falta las dos cosas: el CUIT abajo del nombre es lo que distingue dos
 * clientes que se llaman parecido.
 */
export function PickerField({
  label,
  options,
  value,
  onChange,
  onEditCurrent,
  editHint,
  manageTo,
  manageLabel,
  emptyLabel,
}: {
  label: string
  options: PickerOption[]
  value: string | null
  onChange: (id: string) => void
  /** Qué hacer al mantener apretado. Solo se llama cuando hay algo elegido. */
  onEditCurrent: (id: string) => void
  editHint: string
  manageTo: string
  manageLabel: string
  emptyLabel: string
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find((option) => option.id === value)

  const longPress = useLongPress(() => {
    if (value !== null) onEditCurrent(value)
  })

  return (
    <div className="field">
      <span className="field-label">{label}</span>

      <button
        type="button"
        className={`field-button${selected ? '' : ' placeholder'}`}
        onClick={() => setOpen(true)}
        {...longPress}
      >
        <span className="field-value">
          <strong>{selected ? selected.title : emptyLabel}</strong>
          {selected?.subtitle && <span className="muted">{selected.subtitle}</span>}
        </span>
        <span className="field-chevron" aria-hidden="true">
          ⌄
        </span>
      </button>

      {selected && <span className="field-hint">{editHint}</span>}

      {open && (
        <Sheet title={label} onClose={() => setOpen(false)}>
          {options.length === 0 && <p className="empty">{emptyLabel}</p>}
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`sheet-option${option.id === value ? ' selected' : ''}`}
              onClick={() => {
                onChange(option.id)
                setOpen(false)
              }}
            >
              <span className="field-value">
                <strong>{option.title}</strong>
                {option.subtitle && <span className="muted">{option.subtitle}</span>}
              </span>
              {option.id === value && <span aria-hidden="true">✓</span>}
            </button>
          ))}
          <Link className="sheet-manage" to={manageTo} onClick={() => setOpen(false)}>
            {manageLabel}
          </Link>
        </Sheet>
      )}
    </div>
  )
}

/**
 * La hoja que sube desde abajo en el celular y es un diálogo centrado en pantalla ancha.
 *
 * El backdrop cierra al tocarlo y `Escape` también: en el celular no hay tecla, y en la
 * computadora esperar el click justo sobre el fondo es incómodo. Las dos salidas cuestan tres
 * líneas cada una y la ausencia de cualquiera de ellas se nota enseguida.
 */
function Sheet({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  // Dos efectos y no uno. El `onClose` llega como arrow inline, o sea con identidad nueva en
  // cada render: enganchar el teclado cuesta nada y volver a hacerlo no molesta, pero guardar
  // y restaurar el `overflow` del body en cada render sí — la segunda pasada guardaría como
  // "valor original" el `hidden` que puso la primera, y la página quedaría trabada al cerrar.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  useEffect(() => {
    // El body no scrollea mientras la hoja está abierta: sin esto, desplazar dentro de la
    // lista arrastra la página de atrás en cuanto la lista llega a su tope.
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      {/* El click de adentro no llega al backdrop: si no, elegir una opción cerraría dos
          veces —y con el `stopPropagation` puesto acá no hace falta repetirlo en cada fila. */}
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sheet-head">
          <strong>{title}</strong>
          <button type="button" className="icon" onClick={onClose} aria-label="Cerrar">
            ✕
          </button>
        </div>
        <div className="sheet-body">{children}</div>
      </div>
    </div>
  )
}
