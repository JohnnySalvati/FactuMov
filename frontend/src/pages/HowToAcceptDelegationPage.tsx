import { Link } from 'react-router'

import { GuideFigure } from '../components/GuideFigure'

/**
 * `/como-aceptar-delegacion`: el instructivo ilustrado para el operador de FactuMov, que
 * linkea el mail «Aceptar la delegación del CUIT …» (`send_delegation_pending_email`).
 *
 * **No es para un usuario**, como `/delegacion-aceptada`: le habla a quien atiende la Clave
 * Fiscal de FactuMov. Va sin sesión por lo mismo —la identidad fiscal es de otro— y su
 * nombre lo fija `_HOW_TO_ACCEPT_PATH` del backend.
 *
 * Separado de `/delegacion-aceptada` a propósito: aquella es la herramienta —abre con un
 * token, le pregunta a ARCA y avisa al usuario—; esta es el «cómo se hace», sin token, para
 * leer antes o mientras. El mail linkea las dos.
 *
 * El trámite tiene DOS pasos y el mail que describía solo el primero costó una producción
 * (docs/arca.md → *Delegar tiene dos partes*). Acá los dos están ilustrados, y el paso 2
 * lleva el aviso de por qué aceptar la designación no alcanza. Los números son los de los
 * círculos rojos de las capturas —el paso 1 es el círculo 1; los del paso 2 siguen del 2 al
 * 9, porque tres de esas capturas las comparte con `/como-delegar`.
 */
export function HowToAcceptDelegationPage() {
  return (
    <div className="guide">
      <h1>Aceptar una delegación de Facturación Electrónica</h1>
      <p className="guide-intro">
        Un contribuyente designó a FactuMov como representante para Facturación Electrónica y
        está esperando. Son <strong>dos pasos</strong> en ARCA, con la Clave Fiscal de
        FactuMov, y van <strong>por cada CUIT</strong> que delega: no es un alta que se hace
        una vez y queda.
      </p>

      <h2>Paso 1 — Aceptar la designación</h2>
      <div className="guide-steps">
        <div className="guide-step">
          <p>
            <strong>1.</strong> Entrá a <strong>arca.gob.ar</strong> con la Clave Fiscal de
            FactuMov y abrí <strong>Aceptación de Designación</strong>. Aceptá la fila del
            representado —el CUIT que delegó—, servicio{' '}
            <strong>Facturación Electrónica</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/portal-operador.png"
            alt="Grilla de servicios del portal, con el acceso a Aceptación de Designación"
          >
            Si la fila no aparece, el contribuyente todavía no completó su parte.
          </GuideFigure>
        </div>
      </div>

      <h2>Paso 2 — Pasarle el servicio al certificado</h2>
      <div className="notice warn">
        Aceptar la designación <strong>no alcanza</strong>: habilita a la persona, pero WSAA
        le emite el ticket al <strong>certificado</strong> y la lista de relaciones que WSFE
        valida es la del certificado. Sin este paso, ARCA sigue contestando el código 600,
        igual que si no hubieras aceptado nada.
      </div>
      <div className="guide-steps">
        <div className="guide-step">
          <p>
            <strong>2.</strong> Volvé al <strong>Administrador de Relaciones</strong> y tocá{' '}
            <strong>Nueva Relación</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/nueva-relacion.png"
            alt="Pantalla del Administrador de Relaciones con tres botones a la derecha"
          >
            El mismo botón que usó el contribuyente, ahora del lado de FactuMov.
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>3–4.</strong> En <strong>Representado</strong> poné el CUIT que te delegó{' '}
            <strong>(3)</strong>. En la fila <strong>Servicio</strong>, tocá{' '}
            <strong>BUSCAR</strong> <strong>(4)</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/representado-y-servicio.png"
            alt="Formulario Incorporar nueva Relación, con el desplegable Representado y el botón BUSCAR"
          >
            Acá el <em>Representado</em> es el otro, no FactuMov.
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>5–6.</strong> Elegí <strong>ARCA</strong> <strong>(5)</strong> y después{' '}
            <strong>WebServices</strong> <strong>(6)</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/organismo-arca.png"
            alt="Lista de organismos con el botón ARCA y los enlaces Servicios Interactivos y WebServices"
          >
            En <strong>WebServices</strong>, no en «Servicios Interactivos».
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>7.</strong> Bajá hasta <strong>Facturación Electrónica</strong> y tocá su
            nombre.
          </p>
          <GuideFigure
            src="/guia-delegacion/servicio-facturacion-electronica.png"
            alt="Lista de web services de ARCA, ordenada alfabéticamente"
          >
            No «Factura electrónica de exportación» ni «… con Detalle - MTXCA».
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>8–9.</strong> En <strong>Representante</strong> tocá{' '}
            <strong>BUSCAR</strong> y elegí el <strong>computador</strong> cuyo certificado
            usa FactuMov —<strong>no tu CUIT</strong>, que es el que viene puesto por default—{' '}
            <strong>(8)</strong>. Tocá <strong>CONFIRMAR</strong> <strong>(9)</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/representante-y-confirmar.png"
            alt="Formulario completo, con el servicio elegido, el botón BUSCAR de Representante y CONFIRMAR"
          >
            En la captura, el Representante muestra un CUIT:{' '}
            <strong>ahí va el computador</strong>, no una persona. Dejar el CUIT es el error
            que hace que ARCA siga contestando 600.
          </GuideFigure>
        </div>
      </div>

      <div className="notice ok">
        Cuando termines los dos pasos, entrá al link del mail (
        <Link to="/delegacion-aceptada">delegación aceptada</Link>): le pregunta a ARCA en el
        momento y te contesta. Si dice que todavía no, casi seguro falta el paso 2 — volvé,
        completalo y entrá de nuevo. Si dice que sí, le avisamos al usuario en el acto.
      </div>
    </div>
  )
}
