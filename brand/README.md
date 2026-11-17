# Marca de Sauri

El isotipo es un cuadrado de esquinas redondeadas partido por una diagonal en dos mitades doradas (dorado y oliva), con un rombo recortado en el centro.

## Qué significa

- Las dos mitades (dorado y oliva) son dos voces distintas en una conversación.
- El rombo del centro es lo que Sauri conserva de esa conversación para que puedas encontrarlo y revisarlo después.

## Archivos

| Archivo | Uso |
| --- | --- |
| `sauri-isotype.svg` | Isotipo maestro. Para tamaños de 33 px en adelante (portal, README, documentos, 48 y 128 px de la extensión). |
| `sauri-isotype-small.svg` | Misma figura con la separación más ancha y el rombo más grande. Para tamaños de 32 px o menos (favicon, íconos de 16 y 32 px). |
| `sauri-logo.svg` | Logo horizontal (isotipo + «Sauri» convertido a trazos, DM Sans Bold) para fondos claros. |
| `sauri-logo-dark.svg` | Logo horizontal para fondos oscuros. |
| `isotype-source.png` | Ilustración original del dueño. Solo referencia; no se usa en el producto. |

El isotipo ocupa todo su lienzo, sin margen: los íconos de la extensión y el favicon van de borde a borde. Solo el `apple-touch-icon` del portal (180 px) lleva fondo marfil con margen de 32 px por lado (isotipo de 116 px). Los PNG de la extensión (`extension/public/icons/`) y del portal (`frontend/public/`) se generan desde estos SVG con `rsvg-convert`, por ejemplo `rsvg-convert -w 128 -h 128 brand/sauri-isotype.svg -o icon-128.png`. En 16 y 32 px se usa la variante pequeña.

## Logo horizontal

Úsalo donde haya espacio para el nombre (cabecera del README, documentos, presentaciones): `sauri-logo.svg` sobre fondos claros y `sauri-logo-dark.svg` sobre fondos oscuros. El texto es vectorial, no necesita tipografía instalada (DM Sans, licencia SIL OFL). Altura mínima: 24 px; por debajo de eso se usa solo el isotipo. En la interfaz (barra lateral y encabezado de inicio de sesión del portal, cabecera del panel y de las opciones de la extensión) se dibuja con los componentes `BrandLogo` y `BrandWordmark` (portal: `frontend/src/components/ui/BrandLogo.tsx`; extensión: `extension/src/core/design/BrandLogo.tsx`), que repiten estos trazos tal cual. La palabra «Sauri» como marca nunca es texto vivo en otra fuente.

## Colores

- Mitad oscura (oliva): `#A59837`
- Mitad clara (dorado): `#CFBB23`
- Nombre en el logo horizontal: `#33322B` (casi negro cálido) sobre fondo claro y `#F7F3DE` (marfil) sobre fondo oscuro (ya incluidos en los archivos; no se cambian).
- Fondo del apple-touch-icon: marfil `#FFFCEE`
- El isotipo usa solo esos dos colores.

## Reglas de uso

- Tamaño mínimo: 16 px (con la variante pequeña).
- Espacio libre alrededor: un cuarto del ancho del isotipo (o de la altura del logo) por cada lado.
- No cambiar los colores, ni siquiera en modo oscuro: las dos mitades se ven bien sobre fondos claros y oscuros.
- No rotarlo, deformarlo ni cambiar la proporción.
- No agregarle texto, sombras ni contornos. El nombre «Sauri» va al lado como la palabra oficial en trazos (`BrandWordmark`), nunca como texto de la interfaz ni dentro del isotipo.
- En la interfaz se dibuja con el componente `BrandMark` del portal (`frontend/src/components/ui/BrandMark.tsx`), que elige solo la variante pequeña cuando el tamaño es de 32 px o menos.
