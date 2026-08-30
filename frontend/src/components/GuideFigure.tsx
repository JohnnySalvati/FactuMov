import type { ReactNode } from 'react'

/**
 * Una captura de ARCA con su epígrafe, para los instructivos de delegación
 * (`/como-delegar` y `/como-aceptar-delegacion`).
 *
 * Las imágenes viven en `public/guia-delegacion/` y las genera
 * `scripts/annotate_delegation_guide.py` a partir de las capturas crudas: el círculo
 * numerado y la flecha están **quemados en el PNG**, pero el texto que explica cada número
 * va acá, en el `<figcaption>`. Así se corrige la redacción sin volver a rasterizar y lo lee
 * un lector de pantalla, que del dibujo no saca nada.
 *
 * Por eso el `alt` describe qué pantalla es y no repite el epígrafe.
 *
 * **Sin `loading="lazy"`**, aunque el instructivo sea largo: las siete capturas juntas pesan
 * ~180 KB, y sin dimensiones intrínsecas declaradas una imagen `lazy` mide 0 hasta que
 * carga, lo que descuadra el scroll de la página entera a medida que van apareciendo. No hay
 * nada que ganar cargándolas de a una.
 */
export function GuideFigure({
  src,
  alt,
  children,
}: {
  src: string
  alt: string
  children: ReactNode
}) {
  return (
    <figure className="guide-figure">
      <img src={src} alt={alt} />
      <figcaption>{children}</figcaption>
    </figure>
  )
}
