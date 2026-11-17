# Landing de Sauri

Página pública que explica Sauri a quien no lo conoce. Vive en `landing/` (HTML y CSS estáticos, sin compilación) y se publicará con GitHub Pages cuando el dueño decida cómo (el repositorio es privado: Pages exige GitHub Pro o un repositorio público).

Decisiones del dueño (2026-11-16): publicación a decidir al final; llamada a la acción = solicitar acceso anticipado por correo; material = capturas reales de una reunión de demostración inventada; idioma = español primero, estructura lista para inglés.

## 1. Qué aprendimos de apxagent.app (estrategia, no estilo)

APX abre con una promesa de una frase y una captura real visible sin desplazarse; sigue con qué puedes hacer, una sección numerada de tres pasos, documentación, preguntas frecuentes y un cierre con la misma llamada a la acción. Usa capturas estáticas reales (sin video automático), código copiable y una página de privacidad que separa con precisión lo que se queda en el equipo, lo que sale siempre, lo que sale solo si lo aceptas y lo que nunca sale. Admite la fricción de instalación con franqueza. La misma llamada a la acción se repite con el mismo texto en cabecera, portada, sección de descarga y cierre.

Adaptamos a Sauri:
1. Promesa de una frase y la pantalla real de una reunión sin desplazarse.
2. «Cómo funciona» en tres pasos: grabar, revisar quién habló, revisar el resumen.
3. El resumen como borrador: tú tienes la última palabra.
4. Privacidad como prueba concreta (qué se queda, qué sale y cuándo), no como un candado decorativo.
5. Honestidad sobre el estado: en desarrollo, solo Mac con Apple silicon y Chrome.
6. Preguntas frecuentes cortas.
7. Una sola llamada a la acción con el mismo texto en cabecera, portada y cierre.

No imitamos: comparativas con competidores, galerías largas de ilustraciones, muchas rutas de documentación, ni callar el estado del producto.

## 2. Plan de material visual

Todo sale de una reunión inventada («Hortalia», tres personas ficticias con voces sintéticas del Mac) procesada en Sauri: capturas reales sin datos de reuniones verdaderas.

| Pieza | Mensaje | Qué muestra | Sección |
|---|---|---|---|
| `meeting-detail` | «Esto es lo que obtienes» | Reunión completa: video, transcripción con hablantes en color y resumen | Portada |
| `extension-panel` | Grabar es un clic | Panel de la extensión «Grabar reunión» listo para grabar | Paso 1 |
| `speakers` | Sabes quién dijo qué | Panel de hablantes junto al video con los nombres asignados | Paso 2 |
| `summary` | Un borrador que revisas | Panel de resumen: asunto, puntos clave, próximos pasos | Paso 3 |
| `follow` (video corto, sin sonido) | La transcripción sigue al video | Resaltado que avanza con la reproducción | Lo que puedes hacer |
| `transcript` | Turnos claros | Recorte de turnos con colores por hablante | Lo que puedes hacer |
| `library` | Todo queda ordenado | Biblioteca con miniaturas y fechas | Lo que puedes hacer |
| `upload` | También sirve con grabaciones que ya tienes | Pantalla «Subir grabación» | Lo que puedes hacer |

Formato: PNG de origen y WebP optimizado, con `width`/`height` declarados; el video corto en WebM sin audio, con póster y sin reproducción automática si el visitante pidió reducir el movimiento.

## 3. Textos

Límite de lo que se promete: `docs/product/baseline.md` (alcance aprobado) y lo ya integrado. No se prometen el chat con la grabación (fase 2), ni tiempos exactos, ni precios.

**Cabecera:** logo · Cómo funciona · Privacidad · Preguntas · botón «Solicitar acceso».

**Portada**
- Etiqueta: «En desarrollo · acceso anticipado para Mac»
- Titular: «Tus reuniones, transcritas y resumidas en tu propio Mac»
- Bajada: «Sauri graba la reunión desde una pestaña de Chrome, reconoce quién habló y te deja un resumen en borrador para revisar. La grabación no sale de tu equipo.»
- Botones: «Solicitar acceso anticipado» (principal) · «Ver cómo funciona» (secundario)

**Cómo funciona** — «De la reunión al resumen en tres pasos»
1. «Graba desde Chrome» — «Abre la extensión, elige la pestaña de la reunión y pulsa grabar. Funciona con Google Meet y con cualquier reunión que tengas abierta en el navegador.»
2. «Revisa quién habló» — «Sauri separa las voces y pone cada intervención a nombre de su hablante. Si no reconoce una voz, la deja como «Hablante 2» hasta que tú le pongas nombre, y la próxima vez la recuerda.»
3. «Revisa el resumen» — «Recibes un borrador con el asunto principal, los puntos clave y los próximos pasos. Tú lo lees, lo ajustas y decides qué compartir.»

**Lo que puedes hacer** — «Todo lo de la reunión, en un solo lugar»
- «La transcripción sigue al video» — «Mientras reproduces, la frase que se está diciendo se resalta. Haz clic en cualquier frase para saltar a ese momento.»
- «Encuentra cualquier reunión» — «Tu biblioteca ordena las grabaciones por fecha, con búsqueda y filtros.»
- «Sube grabaciones que ya tienes» — «¿Grabaste con otra herramienta? Sube el archivo y Sauri lo procesa igual.»
- «Llévate lo que necesites» — «Descarga el video, la transcripción o el resumen.»
- «Resúmenes a tu manera» — «Crea plantillas para que cada tipo de reunión tenga el resumen que necesitas.»
- «Notas aparte» — «Toma notas durante la grabación; quedan junto a la reunión, separadas de la transcripción.»

**Privacidad** — «Tus reuniones se quedan contigo»
- Bajada: «Sauri hace el trabajo pesado en tu Mac: transcribir, reconocer voces y resumir. No hace falta subir tus reuniones a la nube.»
- «Se queda en tu Mac» — «Las grabaciones, las transcripciones, los resúmenes y los nombres que asignas a cada voz.»
- «Sale solo si tú lo eliges» — «Si prefieres que un servicio externo haga una tarea (por ejemplo, el resumen), lo conectas tú, para esa tarea. Ese servicio recibe lo que necesita para hacerla.»
- «Te avisa antes» — «Al activar un servicio externo, Sauri te muestra qué sale del equipo y hacia dónde, y te pide confirmarlo.»

**Estado** — «Sauri está en desarrollo»
- «Lo usamos a diario y lo mejoramos cada semana, pero todavía no es una versión final. Hoy funciona en Mac con Apple silicon y con Google Chrome.»

**Preguntas frecuentes**
- «¿Mis reuniones se suben a internet?» — «No. Sauri las procesa en tu Mac. Solo sale algo si tú conectas un servicio externo para una tarea, y Sauri te avisa antes.»
- «¿Qué reuniones puedo grabar?» — «Cualquier reunión que tengas abierta en una pestaña de Chrome, como Google Meet. También puedes subir grabaciones que ya tengas.»
- «¿Debo avisar a los participantes?» — «Sí. Pide permiso antes de grabar, como harías con cualquier grabadora.»
- «¿Qué necesito para usarlo?» — «Un Mac con Apple silicon y Google Chrome.»
- «¿En qué idiomas funciona?» — «La aplicación está en español e inglés, y transcribe reuniones en esos idiomas.»
- «¿Puedo corregir los nombres de los hablantes?» — «Sí. Puedes renombrar a cualquier hablante en cualquier momento, y Sauri usa tus correcciones en tus siguientes reuniones.»

**Cierre** — «¿Quieres probar Sauri?» · «Escríbenos y te contamos cómo empezar.» · botón «Solicitar acceso anticipado».

**Pie:** logo · «Sauri está en desarrollo.» · enlaces a las secciones.

Glosario fijo: «grabación» (no «sesión»), «reunión», «transcripción», «hablante», «resumen en borrador», «servicio externo» (no «proveedor» en la landing), «tu Mac».

## 4. Implementación (para quien la mantenga)

- **Estructura:** `landing/index.html` + `styles.css` + `tokens.css` + `motion.js` + `assets/`. Sin compilación ni dependencias; se abre con cualquier servidor estático (`python3 -m http.server --directory landing`).
- **Tokens:** `tokens.css` copia los `--ds-*` de `frontend/src/design/tokens.css` (claro/oscuro con `light-dark()`, Chrome 123+). La escala propia de la página usa el prefijo `--lp-*`. Si cambia el diseño del portal, actualizar `tokens.css`.
- **Paleta (Terra ampliada, decisión del dueño 2026-11-16):** verde `#4a7c59` (único color de botones), terracota `#9a5b2e`, azul pizarra `#3f6a8a` y ocre `#e3c77a`/`#705c30`, con marfil `#faf6f0` y tierra `#2e3230` de base. Terracota y azul son los tonos de hablante 2 y 3 del producto; el ocre es el par de aviso. Definidos como `--lp-*` en `styles.css` con versión clara y oscura. Uso: chips de la portada, números de pasos, etiquetas de sección, tarjetas de funciones, iconos de privacidad, bloque de estado (ocre) y cierre (terracota suave). El producto (portal y extensión) no cambia.
- **Una sola acción primaria** por grupo; el mismo texto «Solicitar acceso anticipado» en cabecera, portada y cierre. El botón abre un `mailto:` (sin servicios externos); el destino es `lufermalgo@gmail.com`.
- **Imágenes:** capturas reales de la reunión de demostración «Hortalia» (personas y voces ficticias), PNG + WebP con `width`/`height`. Sin datos de reuniones reales ni del perfil del usuario. El video `follow.webm` no tiene audio, solo se reproduce a la vista, respeta `prefers-reduced-motion` y tiene botón de pausa (WCAG 2.2.2).
- **Accesibilidad:** `lang="es"`, un solo `h1`, enlace para saltar al contenido, `alt` en todas las capturas, logo decorativo con nombre en el enlace, sin desbordamiento horizontal a 375 px. Pendiente: revisión de contraste con herramienta externa.
- **Inglés:** el texto vive en `index.html`; para traducir, duplicar a `landing/en/` con el mismo marcado y enlazar ambos con `hreflang`.
- **Limitación conocida del producto:** el resumen de la demo dice «Hablante 1/2/3» aunque los hablantes ya tengan nombre (el resumen se genera antes de nombrarlos y la interfaz no permite regenerarlo).
