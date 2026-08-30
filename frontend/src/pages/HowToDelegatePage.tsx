import { GuideFigure } from '../components/GuideFigure'

/**
 * `/como-delegar`: el instructivo ilustrado que linkea el mail «Cómo autorizar a FactuMov a
 * emitir tus facturas» (`send_delegation_instructions_email`).
 *
 * Va sin sesión y en `PublicLayout`: el usuario lo abre desde el mail apenas confirma la
 * cuenta, antes de cargar ningún CUIT, y bien puede no estar logueado todavía. Su nombre lo
 * fija `_HOW_TO_DELEGATE_PATH` del backend — cambiarlo acá sin cambiarlo allá deja los mails
 * ya enviados apuntando a la nada, igual que `/confirmar-email`.
 *
 * El mail sigue trayendo los pasos en texto (por si esto no carga, y para el lector de
 * pantalla); esta pantalla es la versión con capturas, que es lo que pidió Miguel porque «la
 * página de ARCA es muy críptica». Los números de los pasos son los de los círculos rojos de
 * las imágenes, y por eso los escribimos a mano: algunas capturas marcan dos clics.
 */

// El CUIT que ARCA tiene que ver como representante. Es el del certificado de FactuMov y es
// "un hecho del proyecto, no de la instalación" (docs/arca.md → *El CUIT de FactuMov*): el
// mismo default que `ArcaSettings.arca_delegate_tax_id` en el backend, que es quien lo
// nombra de verdad en el mail leyéndolo del certificado. Acá va escrito porque la SPA no
// tiene por dónde preguntarlo y el número no cambia.
const FACTUMOV_TAX_ID = '20182810674'

export function HowToDelegatePage() {
  return (
    <div className="guide">
      <h1>Autorizar a FactuMov en ARCA</h1>
      <p className="guide-intro">
        Para que FactuMov emita facturas a nombre de tu CUIT, ARCA necesita que lo autorices
        vos. Es un trámite online, gratis y se hace <strong>una sola vez por CUIT</strong>.
        Vas a necesitar tu Clave Fiscal (nivel 3 o más).
      </p>

      <div className="guide-steps">
        <div className="guide-step">
          <p>
            <strong>1.</strong> Entrá a <strong>arca.gob.ar</strong> con tu Clave Fiscal y
            abrí <strong>Administrador de Relaciones</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/portal-contribuyente.png"
            alt="Portal de Clave Fiscal de ARCA, con la barra de accesos arriba"
          >
            Está en la barra de arriba del portal. También aparece como{' '}
            <em>«Administrador de Relaciones de Clave Fiscal»</em> en la grilla de servicios.
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>2.</strong> Tocá <strong>Nueva Relación</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/nueva-relacion.png"
            alt="Pantalla del Administrador de Relaciones con tres botones a la derecha"
          >
            No es <em>«Adherir Servicio»</em>: ese sirve para sumar un servicio a tu propia
            Clave Fiscal, no para autorizar a otro.
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>3–4.</strong> En <strong>Representado</strong> dejá tu propio nombre —el
            CUIT que va a emitir— <strong>(3)</strong>. Después, en la fila{' '}
            <strong>Servicio</strong>, tocá <strong>BUSCAR</strong> <strong>(4)</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/representado-y-servicio.png"
            alt="Formulario Incorporar nueva Relación, con el desplegable Representado y el botón BUSCAR"
          >
            Si en el desplegable aparece más de un nombre, elegí el tuyo.
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>5–6.</strong> En la lista de organismos elegí <strong>ARCA</strong>{' '}
            <strong>(5)</strong> y después <strong>WebServices</strong> <strong>(6)</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/organismo-arca.png"
            alt="Lista de organismos con el botón ARCA y los enlaces Servicios Interactivos y WebServices"
          >
            «Facturación Electrónica» es un web service, así que está en{' '}
            <strong>WebServices</strong> y no en «Servicios Interactivos».
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>7.</strong> Bajá por la lista hasta{' '}
            <strong>Facturación Electrónica</strong> y tocá su nombre.
          </p>
          <GuideFigure
            src="/guia-delegacion/servicio-facturacion-electronica.png"
            alt="Lista de web services de ARCA, ordenada alfabéticamente"
          >
            La lista está ordenada alfabética. Cuidado con las parecidas: no es «Factura
            electrónica de exportación» ni «Factura Electrónica con Detalle - MTXCA».
          </GuideFigure>
        </div>

        <div className="guide-step">
          <p>
            <strong>8–9.</strong> Volvés al formulario. En <strong>Representante</strong> tocá{' '}
            <strong>BUSCAR</strong> y cargá el CUIT de FactuMov,{' '}
            <strong className="mono">{FACTUMOV_TAX_ID}</strong> <strong>(8)</strong>. Después
            tocá <strong>CONFIRMAR</strong> <strong>(9)</strong>.
          </p>
          <GuideFigure
            src="/guia-delegacion/representante-y-confirmar.png"
            alt="Formulario completo, con el servicio elegido, el botón BUSCAR de Representante y CONFIRMAR"
          >
            Es la <strong>BUSCAR</strong> de la fila <em>Representante</em>, la de abajo.
          </GuideFigure>
        </div>
      </div>

      <div className="notice ok">
        Listo. Ahora cargá tu CUIT en FactuMov, en <strong>Identidades fiscales</strong>.
        Nosotros verificamos la autorización solos y te avisamos por mail cuando puedas
        emitir: puede demorar un rato porque del lado de FactuMov también hay un par de pasos
        para hacer. No hace falta que nos escribas.
      </div>
    </div>
  )
}
