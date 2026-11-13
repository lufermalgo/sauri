# #880 / #882 — Estado terminal y aislamiento de selección

Fecha: 2026-11-13. Base `7e8d296` (#882). Hallazgos de revisión independiente de Nahuel sobre ese SHA, dentro del core aprobado y de las reglas existentes de aislamiento/estado veraz. No modifica políticas, número de hablantes ni coordinación T-15.

## Corrección

- `not_reconstructible` es terminal: se detiene la consulta periódica, se conserva la transcripción, se muestra que la separación no está disponible y no se ofrece un enlace que anuncie párrafos por hablante listos.
- Una carga queda asociada a la selección que la inició. Si se selecciona B durante la carga A, el éxito o error tardío de A no cambia los controles/estado de B ni dispara consultas sobre una grabación B que aún no se subió. Si la selección cambia durante la inspección previa, no se inicia la carga obsoleta. No se cancela ni borra una carga ya aceptada por el servidor.
- La identidad seleccionada se invalida al desmontar. Los controles de autorización y el contrato de carga permanecen intactos.

## Pruebas

Desde raíz del worktree, usando las dependencias ya instaladas del repositorio:

- RED del estado terminal: prueba falla por ausencia del aviso y espera infinita sobre la base.
- El primer intento de dos pruebas de cambio de archivo encontró además un selector ambiguo de testing (`/recording/i` también identifica el medio auxiliar). Se hizo exacto el selector; ese fallo de setup no se usa como evidencia RED.
- RED de aislamiento, con selector corregido y sin los guards de selección: **2 failed / 22 skipped**, por ausencia del botón Upload tras la respuesta tardía (éxito/error). No falla por setup.
- GREEN: `vitest run --root frontend`: **127 passed**, 11 archivos.
- `npm run typecheck`: **PASS** en extension, frontend y shared-types.
- `npm run build --workspace frontend`: **PASS**.
- `git diff --check`: **PASS**.

Logs privados en scratch del hilo: `ui-red.log`, `upload-red.log`, `ui-green.log`. Datos de fixtures exclusivamente sintéticos. No sustituyen los dos videos reales ni certifican exactitud del modelo.

## Verificación interactiva y límites

Arranqué frontend aislado en `http://127.0.0.1:15373`, sin modificar el portal habitual15273 ni motores/Docker. Navegador APX confirmó la pantalla real de login, sin sesión en este origen. Se ofreció handoff legítimo para una cuenta de pruebas; venció sin confirmación. Se detuvo la interacción, sin copiar tokens, eludir autenticación ni usar otro navegador. **Los dos comportamientos visuales corregidos quedan UNVERIFIED en navegador autenticado**, aunque sus pruebas automatizadas pasan. No se declara listo para integrar ni se traslada esa comprobación como aceptación del dueño.

El tercer hallazgo de Nahuel (GET diarization con varias generaciones) se corrige en una unidad backend independiente T13/T14 #652/#653, sin editar estos archivos ni activar T-15. CI/facturación y privacidad T-15 conservan sus bloqueos; integración reservada a Fer.
