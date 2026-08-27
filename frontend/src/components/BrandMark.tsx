/**
 * El ícono de FactuMov con su nombre al lado, que es la marca de la app en la barra de arriba
 * y arriba de las pantallas sin sesión.
 *
 * Es un `<img>` al SVG de `public/` y no un SVG inline: el mismo archivo lo usan el favicon,
 * el manifest y el script que genera los PNG, así que copiarlo acá adentro crearía una segunda
 * versión del dibujo que nadie se va a acordar de actualizar. El costo es un request más, que
 * el navegador cachea.
 */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <span className="brand">
      {/* `alt=""` y no "FactuMov": el nombre está escrito al lado, y repetirlo hace que un
          lector de pantalla lo lea dos veces seguidas. */}
      <img src="/factumov-icon.svg" alt="" width={size} height={size} />
      <span className="brand-name">FactuMov</span>
    </span>
  )
}

/**
 * "Una app de InSoft", con el logo de la casa. Va abajo de las pantallas sin sesión, que es
 * donde alguien que todavía no entró puede querer saber de quién es esto.
 */
export function InSoftCredit() {
  return (
    <p className="insoft-credit">
      <a href="https://insoft.net.ar" target="_blank" rel="noreferrer">
        <span>Una app de</span>
        {/* 40 y no 22, que sería el alto del renglón: el SVG de la casa tiene su propio
            margen adentro del `viewBox` —el dibujo ocupa 70 de sus 160 de alto— así que la
            marca se ve a poco menos de la mitad de lo que mide el `<img>`. */}
        <img src="/insoft-logo.svg" alt="InSoft" height={40} />
      </a>
    </p>
  )
}
