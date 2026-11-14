# Requisitos — Notas asociadas a una grabación

## Introducción

Este documento especifica el comportamiento aprobado para añadir notas asociadas a una grabación y mantenerlas distinguibles de su transcripción. El recorrido general de captura se conserva como contexto en `docs/product/baseline.md`, §4, Journey A; no se vuelve a especificar aquí.

**Alcance:** añadir notas desde la extensión o desde el control flotante cuando está visible, asociarlas con la grabación correspondiente y consultarlas desde esa grabación en el portal web, en un apartado distinto de la transcripción.

**Trazabilidad y autoridad:** el alcance deriva exclusivamente de `docs/product/baseline.md` en `d738e78d65940f17d209edf9a54af5d34e92e059` (blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`): §2, resultado 4; §3, principio “Keep related content distinct”; §4, Journey A, pasos 4 y 6, y Journey C, paso 5; §5, capacidad “Recording-associated notes, separate from transcript”; y §7, decisión abierta #5. Para rastrear el descubrimiento, véase `docs/product/discovery.md`, §2.1, entrada “Notas de grabación”, y §7, “2026-10-09 — Precisiones sobre captura, diarización, notas, portal y CRM” (apartado “Notas — expectativa”). Las referencias visuales y las ideas que solo constan en el descubrimiento no amplían el alcance aprobado.

**Idea fuerza:** una nota se asocia a la grabación que contextualiza y se mantiene aparte de su transcripción.

**Fuera de alcance:** flujo general de captura y sus controles; formato, estructura o longitud de las notas; edición de notas; y forma de acceder a ellas desde el control flotante cuando está oculto.

**Preguntas abiertas (no son requisitos):** ¿Qué formato, estructura y longitud tendrán las notas? ¿Se podrán editar? ¿Cómo se accederá a las notas desde el control flotante cuando esté oculto?

**Nota de handoff:** el código, desarrollo y pruebas existentes son evidencia del estado actual únicamente; no constituyen aceptación del producto ni autorización para ampliar el alcance. Cualquier implementación existente debe evaluarse frente a estos requisitos aprobados y la evidencia pertinente.

## Glosario

- **Grabación**: sesión capturada a la que se asocian las notas y la transcripción.
- **Nota**: contenido contextual que el usuario añade a una grabación y que se mantiene distinto de su transcripción.
- **Transcripción**: contenido textual de las intervenciones de una grabación, tratado separadamente de sus notas.
- **Control_Flotante**: control de grabación que puede estar visible; cuando está visible, el baseline incluye el acceso a notas.

## Requisitos

### Requisito 1: Añadir notas asociadas a la grabación correspondiente

**Historia de Usuario:** Como usuario funcional, quiero añadir notas desde la extensión o desde el control flotante visible, para aportar contexto a la grabación correspondiente.

#### Criterios de Aceptación

1. WHEN el usuario añade una Nota desde la extensión, THE Sauri SHALL asociar esa Nota con la Grabación correspondiente.
2. WHEN el Control_Flotante está visible y el usuario añade una Nota desde él, THE Sauri SHALL asociar esa Nota con la Grabación correspondiente.

### Requisito 2: Consultar las notas de una grabación en el portal web, separadas de la transcripción

**Historia de Usuario:** Como usuario funcional, quiero consultar las notas desde su grabación en el portal web, para acceder a ellas como contenido distinto de la transcripción.

#### Criterios de Aceptación

1. WHEN el usuario consulta una Grabación con Notas asociadas en el portal web, THE Sauri SHALL permitir consultar esas Notas desde esa Grabación.
2. WHEN una Grabación tiene una Nota y una Transcripción disponibles para consulta en el portal web, THE Sauri SHALL presentar la Nota en un apartado separado de la Transcripción.
3. WHEN el usuario consulta la Transcripción de una Grabación que tiene Notas asociadas, THE Sauri SHALL mantener esas Notas identificables como contenido distinto de la Transcripción.
