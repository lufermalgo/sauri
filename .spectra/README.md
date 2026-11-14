# Índice de especificaciones

Cada carpeta de `.spectra/specs/<slug>/` contiene la especificación de una función o corrección (requisitos o bugfix, diseño y tareas). Se conservan como historia del proyecto. **Solo `core-speech-pipeline` está vigente**; el resto no autoriza trabajo nuevo y, si se retoma, debe hacerse como una unidad nueva con aprobación del dueño.

Fases: requisitos (o `bugfix.md` en correcciones), diseño y tareas, según `.config.spectra` de cada spec. Documentación completa no prueba implementación ni aceptación de producto.

| Spec | Tipo | Fases | Estado |
|---|---|---|---|
| [`alembic-version-id-width`](specs/alembic-version-id-width/) | Bugfix | 3/3 completas | Completada (histórica) |
| [`bugfix-migration-009-lineage`](specs/bugfix-migration-009-lineage/) | Bugfix | 3/3 completas | Completada (histórica) |
| [`chrome-recording-completion`](specs/chrome-recording-completion/) | Feature | 3/3 completas | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`core-speech-pipeline`](specs/core-speech-pipeline/) | Feature | 3/3 completas | Vigente |
| [`extension-capture-preferences`](specs/extension-capture-preferences/) | Feature | 1/3 (pendiente: diseño, tareas) | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`fix-backend-lint-type-baseline`](specs/fix-backend-lint-type-baseline/) | Bugfix | 3/3 completas | Completada (histórica) |
| [`fix-meeting-completion-state`](specs/fix-meeting-completion-state/) | Bugfix | 2/3 (pendiente: tareas) | Histórica (fases pendientes, retomar con nueva unidad) |
| [`fix-stale-meeting-recovery`](specs/fix-stale-meeting-recovery/) | Bugfix | 3/3 completas | Completada (histórica) |
| [`fix-transcript-word-fragments`](specs/fix-transcript-word-fragments/) | Bugfix | 3/3 completas | Completada (histórica) |
| [`local-platform-deployment`](specs/local-platform-deployment/) | Feature | 3/3 completas | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`meeting-review-playback`](specs/meeting-review-playback/) | Feature | 3/3 completas | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`meeting-summaries-templates`](specs/meeting-summaries-templates/) | Feature | 3/3 completas | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`performance-observability-pipeline`](specs/performance-observability-pipeline/) | Feature | 3/3 completas | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`portal-visual-design`](specs/portal-visual-design/) | Feature | 3/3 completas | Plan listo; implementación pendiente de revisión del dueño |
| [`recording-library-metadata`](specs/recording-library-metadata/) | Feature | 1/3 (pendiente: diseño, tareas) | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`recording-notes`](specs/recording-notes/) | Feature | 3/3 completas | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`recording-speaker-review`](specs/recording-speaker-review/) | Feature | 3/3 completas | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`speaker-recognition-test-screen`](specs/speaker-recognition-test-screen/) | Feature | 3/3 completas | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`speaker-recognition-test-screen-login`](specs/speaker-recognition-test-screen-login/) | Feature | 2/3 (pendiente: tareas) | Histórica (pendiente de producto, retomar con nueva unidad) |
| [`uploaded-meeting-default-title`](specs/uploaded-meeting-default-title/) | Bugfix | Sin `.config.spectra`; solo registro de aceptación | Histórica (solo registro de aceptación) |
