# Marca de Sauri

El isotipo es un cuadrado de esquinas redondeadas partido por una diagonal en dos mitades verdes, con un rombo recortado en el centro.

## Qué significa

- Las dos mitades verdes son dos voces distintas en una conversación.
- El rombo del centro es lo que Sauri conserva de esa conversación para que puedas encontrarlo y revisarlo después.

## Archivos

| Archivo | Uso |
| --- | --- |
| `sauri-isotype.svg` | Isotipo maestro. Para tamaños de 33 px en adelante (portal, README, documentos, 48 y 128 px de la extensión). |
| `sauri-isotype-small.svg` | Misma figura con la separación más ancha y el rombo más grande. Para tamaños de 32 px o menos (favicon, íconos de 16 y 32 px). |
| `sauri-logo.svg` | Logo horizontal (isotipo + «Sauri» convertido a trazos, DM Sans Bold) para fondos claros. |
| `sauri-logo-dark.svg` | Logo horizontal para fondos oscuros. |
| `isotype-source.png` | Ilustración original del dueño. Solo referencia; no se usa en el producto. |

El isotipo ocupa todo su lienzo, sin margen: los íconos de la extensión y el favicon van de borde a borde. Solo el `apple-touch-icon` del portal lleva fondo marfil con margen. Los PNG de la extensión (`extension/public/icons/`) y del portal (`frontend/public/`) se generan desde estos SVG con `rsvg-convert`, por ejemplo `rsvg-convert -w 128 -h 128 brand/sauri-isotype.svg -o icon-128.png`. En 16 y 32 px se usa la variante pequeña.

## Logo horizontal

Úsalo donde haya espacio para el nombre (cabecera del README, documentos, presentaciones): `sauri-logo.svg` sobre fondos claros y `sauri-logo-dark.svg` sobre fondos oscuros. El texto es vectorial, no necesita tipografía instalada (DM Sans, licencia SIL OFL). Altura mínima: 24 px; por debajo de eso se usa solo el isotipo. En la barra lateral del portal y en el panel de la extensión se dibuja el isotipo junto al texto «Sauri» de la interfaz, no el logo.

## Colores

- Mitad oscura: `#4a7c59`
- Mitad clara: `#78a886`
- Nombre en el logo horizontal: verde muy oscuro sobre fondo claro y claro sobre fondo oscuro (ya incluidos en los archivos; no se cambian).
- Fondo del apple-touch-icon: marfil `#faf6f0`

## Reglas de uso

- Tamaño mínimo: 16 px (con la variante pequeña).
- Espacio libre alrededor: un cuarto del ancho del isotipo (o de la altura del logo) por cada lado.
- No cambiar los colores, ni siquiera en modo oscuro: las dos mitades se ven bien sobre fondos claros y oscuros.
- No rotarlo, deformarlo ni cambiar la proporción.
- No agregarle texto, sombras ni contornos. El nombre «Sauri» va al lado, escrito con el texto normal de la interfaz, nunca dentro del isotipo.
- En la interfaz se dibuja con el componente `BrandMark` del portal (`frontend/src/components/ui/BrandMark.tsx`), que elige solo la variante pequeña cuando el tamaño es de 32 px o menos.
