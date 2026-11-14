# Sauri

Graba sesiones virtuales y ofrece transcripciones con identificación de hablantes. Estas reglas compartidas complementan las responsabilidades de cada agente.

## Alcance y comunicación
- Ejecutá solo trabajo solicitado o aprobado; no generes actividad para ocupar agentes. `PRODUCT_BASELINE.md` y las aprobaciones del dueño definen alcance; notas de descubrimiento y specs históricas no autorizan trabajo nuevo. Dentro de un objetivo aprobado, corregí errores técnicos y actualizá el plan y su inventario sin pedir nueva autorización, siempre que preserves comportamiento, controles y límites acordados; un archivo o una tarea técnica adicional no constituye por sí solo nuevo alcance. Consultá cambios reales de producto, alcance, privacidad, gastos o seguridad y respetá restricciones explícitas del dueño.
- Consultá al dueño cambios de producto, privacidad, gastos o políticas de seguridad. No eludas permisos. Explicá funcionalidad, impacto, costos y riesgos en español claro, sin trasladarle decisiones técnicas resolubles con evidencia; recomendá una acción concreta.
- Colaborá solo con agentes del proyecto actual. La visibilidad global no autoriza colaboración externa. Única excepción: Teo para configuración de APX, nunca como intermediario operativo de Sauri. Mantené producto, diseño, investigación y validación dentro del equipo.
- Preservá secretos, cambios ajenos y el entorno de pruebas del dueño. La validación técnica no sustituye su aceptación de producto.

## Especificaciones y encargos
- Specs: `.spectra/specs/<slug>/`. Fases: `spectra-req` → `requirements.md`; `spectra-design` → `design.md`; `spectra-tasks` → `tasks.md`. En bugfix, `spectra-bugfix` → `bugfix.md` reemplaza la primera fase. Cargá la skill y referencias de la fase pertinente.
- Reutilizá specs; contrastá estado y aprobaciones con evidencia y código. Respetá aprobaciones de fase sin pedir nuevamente las existentes. Documentación completa no prueba implementación ni aceptación.
- Cada encargo de implementación incluye spec, requisitos/tareas, issue, objetivo funcional, alcance/exclusiones, dependencias, contratos, criterios de aceptación, pruebas y condición de cierre: PR listo para integrar o integración verificada, indicando quién integra.
- Para iniciar una tarea, asigná ejecutor, objetivo y descripción; crear una tarjeta o cambiar su estado no inicia trabajo. No dupliques esa asignación mediante delegación. No delegues ediciones triviales. Empezá con una pieza delegada a la vez; paralelizá trabajo independiente autorizado con recursos disponibles, interfaces explícitas y sin editar simultáneamente los mismos archivos.
- Mantené trazabilidad y estados coherentes entre `tasks.md`, tareas APX, issues, commits y PRs. Quien asigna verifica la entrega; las revisiones aportan evidencia, no aprobaciones obligatorias de especialistas ausentes.

## Implementación, pruebas y Git
- Al cambiar código, usá rama y worktree aislados por unidad de entrega; tareas estrechamente relacionadas pueden compartirlos. No implementes en el checkout raíz ni en `main`. Esto no exige worktrees para consultas o coordinación.
- No hagas commit/push directo a `main`, desactives hooks ni eludas controles. Protecciones: `.githooks`, `.claude/hooks/block-main-git.sh`; `make setup` configura hooks.
- Entregá funcionalidad real, pruebas y documentación necesaria. No sustituyas producción por simulaciones, debilites pruebas ni recortes alcance para aprobarlas. Datos simulados sirven para pruebas, no como validación de la funcionalidad real; etapas parciales deben aportar avances reales y explicitar faltantes.
- Revisá diff y criterios de aceptación; ejecutá pruebas pertinentes de backend, integración y regresión. Registrá comandos, resultados observados y límites. Para Rust y TypeScript, deben pasar respectivamente la validación Rust y el typecheck definidos por el proyecto antes de declarar listo un PR que los modifique; no supongas comandos genéricos.
- Para recorridos interactivos usá el navegador APX. Para suites automatizadas, los comandos del repositorio. La skill Playwright no autoriza otro navegador interactivo ni eludir login, bloqueos o handoff; las pruebas de interfaz no sustituyen las de backend.
- Publicá commits y PR vinculados cuando la implementación lo requiera; no fabriques commits/PRs vacíos para tareas sin cambios. Antes de integrar, comprobá el candidato actual, pruebas, hallazgos de seguridad y correcciones. Publicación, integración y aceptación son estados distintos: cerrá según el encargo; una entrega integrada requiere merge y condiciones de aceptación verificados.
- Eliminá ramas/worktrees solo con trabajo preservado y limpieza autorizada. Nunca descartes cambios ajenos.

## Calidad y contexto
- Leé código y contexto pertinentes antes de editar; cargá detalles cuando hagan falta y releé solo si pudieron cambiar. Ampliá la lectura en auditorías o dependencias transversales.
- Hacé cambios acotados, sin efectos ni ediciones ajenos al encargo; preferí ediciones puntuales y justificá reescrituras. Buscá soluciones completas, simples, de bajo acoplamiento, seguras ante regresiones, con nombres claros, sin código muerto y consistentes con el proyecto; programación defensiva solo en límites del sistema. Revisá alternativas más simples antes de entregar cambios sustanciales.
- Evaluá evidencia, riesgos y contradicciones materiales; explicitá costos, seguridad o cumplimiento sin exigir debates formales rutinarios.
- Consultá según la tarea `backend/`, `frontend/`, `extension/`, `packages/`, manifiestos y configuración de pruebas; contrastá `README.md`, `Makefile` y `docs/` con el código. Cargá skills pertinentes; no inventes capacidades ni permisos.
