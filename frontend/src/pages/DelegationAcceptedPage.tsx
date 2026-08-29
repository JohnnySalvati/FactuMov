import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'

import { ApiError, api } from '../api/client'
import type { DelegationAcceptance } from '../api/types'
import { Notice } from '../components/Notice'

type Status = 'working' | 'done' | 'failed'

/**
 * Donde aterriza el link del mail al operador: `/delegacion-aceptada?token=…`.
 *
 * **La única pantalla de la app que no es para un usuario.** El resto le habla a alguien que
 * emite facturas; esta le habla a quien atiende la Clave Fiscal de FactuMov, que acaba de
 * aceptar una designación en ARCA y quiere saber si con eso alcanzó. Por eso no está adentro
 * de `RequireAuth`: el operador no tiene por qué tener cuenta, y aunque la tuviera la
 * identidad fiscal es de otro. Lo que lo autoriza es el token del link.
 *
 * La ruta la fija `APP_BASE_URL` + `_DELEGATION_ACCEPTED_PATH` del backend. Cambiarle el
 * nombre acá sin cambiarlo allá deja apuntando a la nada los mails ya enviados.
 *
 * **Pregunta sola al montar**, como `ConfirmEmailPage` y al revés que `ResetPasswordPage`:
 * acá no falta ningún dato que solo el operador pueda dar. Él ya dijo lo que tenía que decir
 * al abrir el link, y hacerle apretar un botón para recibir la respuesta que vino a buscar
 * sería una pantalla de más. El token no es de un solo uso, así que si algo lo dispara de más
 * —el doble montaje de StrictMode, que el `useRef` esquiva igual— el costo es una consulta a
 * ARCA y no un link quemado.
 *
 * **El "todavía no" es la mitad útil, no un error.** Aceptar la designación habilita a la
 * persona y no al certificado: si falta la segunda relación, ARCA sigue contestando lo mismo
 * que si nadie hubiera hecho nada. Esta pantalla es el único lugar donde eso se ve a tiempo,
 * o sea con las pestañas de ARCA todavía abiertas — de ahí el botón para volver a preguntar
 * sin tener que buscar el mail otra vez.
 */
export function DelegationAcceptedPage() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [status, setStatus] = useState<Status>(token ? 'working' : 'failed')
  const [result, setResult] = useState<DelegationAcceptance>()
  const [error, setError] = useState<string | undefined>(
    token ? undefined : 'El link no trae token. Copialo entero desde el mail.',
  )

  const ask = useCallback(() => {
    if (!token) return
    setStatus('working')
    setError(undefined)
    api
      .post<DelegationAcceptance>('/delegations/accepted', { token })
      .then((acceptance) => {
        setResult(acceptance)
        setStatus('done')
      })
      .catch((caught: unknown) => {
        // El 400 del token gastado y el 502 de ARCA caído son cosas distintas y el backend
        // las explica distinto, así que el texto sale de ahí en vez de inventarse uno.
        setError(caught instanceof ApiError ? caught.detail : 'No se pudo consultar ARCA.')
        setStatus('failed')
      })
  }, [token])

  // El guard es por el doble montaje de StrictMode: sin él, abrir el link gastaría dos
  // consultas a ARCA en desarrollo y la segunda tardaría en contestar sobre una pantalla que
  // ya había mostrado la primera.
  const asked = useRef(false)
  useEffect(() => {
    if (asked.current) return
    asked.current = true
    ask()
  }, [ask])

  return (
    <div className="centered">
      <h1>Delegación en ARCA</h1>
      <div className="card">
        {status === 'working' && <p className="muted">Preguntándole a ARCA…</p>}

        {status === 'failed' && <Notice kind="error">{error}</Notice>}

        {status === 'done' && result?.granted && (
          <Notice kind="ok">
            Listo: ARCA ya nos habilita a emitir por el CUIT {result.tax_id} (
            {result.identity_name}). Le avisamos al usuario, que ya puede facturar. No hace
            falta que vuelvas a entrar a este link.
          </Notice>
        )}

        {status === 'done' && result && !result.granted && (
          <>
            <Notice kind="warn">
              ARCA todavía no nos habilita a emitir por el CUIT {result.tax_id} (
              {result.identity_name}).
            </Notice>
            {/* El texto de ARCA no alcanza para explicar nada —el código 600 dice "no
                apareció el CUIT en la lista de relaciones" tanto si no hay designación como
                si falta la del computador— pero es el dato crudo y sirve para soporte. */}
            {result.message && <p className="muted">ARCA contestó: {result.message}</p>}
            <p>
              Lo más probable es que falte el <strong>paso 2</strong>: la relación del servicio
              de Facturación Electrónica con el <strong>computador</strong> como representante,
              no con tu CUIT. Aceptar la designación habilita a la persona; el ticket lo emite
              WSAA para el certificado, y la lista de relaciones que se valida es la de él.
            </p>
            <p className="muted">
              Completalo en el Administrador de Relaciones y volvé a preguntar. Los pasos
              están en el mail.
            </p>
          </>
        )}

        {status !== 'working' && !result?.granted && token && (
          <p>
            <button type="button" onClick={ask}>
              Volver a preguntarle a ARCA
            </button>
          </p>
        )}
      </div>
    </div>
  )
}
