# Sauri

Plataforma interna para grabar sesiones virtuales y ofrecer transcripciones con identificación de hablantes y resumen. Este archivo reúne las reglas para todos los agentes (Claude, Codex y subagentes). `CLAUDE.md` agrega las reglas propias del orquestador.

## Quién hace qué
- **Fer (dueño):** decide producto, privacidad, gastos y seguridad. Acepta el producto al final. Prueba con sus propias grabaciones.
- **Claude (orquestador):** diseña la arquitectura, toma las decisiones técnicas críticas, revisa la calidad (QA), integra los PR y mantiene el repositorio local y remoto limpio y al día.
- **Codex y subagentes de Claude:** implementan código y pruebas, en paralelo, siempre en archivos distintos. Los subagentes también pueden revisar y leer código a gran escala.
- No se usan tarjetas de tarea ni agentes con nombre propio. La trazabilidad vive en los issues de GitHub, los PR y el `tasks.md` de cada spec.

## Alcance
- Haz solo el trabajo pedido o aprobado. No crees alternativas paralelas, simuladores, entregas de relleno ni funciones fuera de alcance.
- `docs/product/baseline.md` y las decisiones del dueño definen el alcance. Las notas de descubrimiento y las specs históricas no autorizan trabajo nuevo.
- Consulta al dueño solo cambios de producto, privacidad, gastos o seguridad. Las decisiones técnicas se resuelven con evidencia y se le explican de forma simple.
- Nada sale de la máquina: el audio, las transcripciones y los resúmenes se procesan localmente. Un servicio externo (p. ej. un modelo de lenguaje en la nube) solo se usa si el dueño lo configura de forma explícita.

## Cómo se trabaja
1. **Spec antes de código:** `.spectra/specs/<slug>/` con `requirements.md` → `design.md` → `tasks.md` (skills `spectra-req`, `spectra-design`, `spectra-tasks`; `spectra-bugfix` para fallos). Respeta las fases ya aprobadas. Documentación terminada no es código ni aceptación.
2. **Una unidad de entrega = un issue, una rama y un worktree propios**, creados desde `origin/main` en `.worktrees/`. Nunca se trabaja en el checkout raíz ni en `main`.
3. **Cada encargo incluye:** spec y tarea, issue, objetivo, alcance y exclusiones, archivos permitidos, criterios de aceptación y comandos de verificación.
4. **Implementa Codex o un subagente (Claude se reserva lo complejo); Claude revisa el diff, ejecuta las pruebas por su cuenta e integra.** Publica el PR quien desarrolló la unidad; el trabajo de Codex lo publica un subagente con acceso a git. Un informe de un agente nunca se acepta sin verificarlo.
5. **Calidad insuficiente:** se devuelve una sola vez al mismo agente con hallazgos concretos. Si vuelve a fallar, Claude lo corrige o lo reasigna a un modelo más fuerte.
6. **Integración:** merge del PR tras la verificación de Claude; las ramas remotas se borran solas al integrar. Publicación, integración y aceptación del dueño son estados distintos.
7. **Skills:** usa `skills-manager` para buscar o vincular las skills que la tarea necesite.

## Entregas reales
- Entrega funcionalidad real con pruebas. No sustituyas producción por simulaciones, no debilites pruebas ni recortes alcance para que pasen. Los datos simulados sirven en pruebas, no como validación.
- Antes de dar algo por listo: pruebas del backend, `npm run typecheck` y `npm run test` si toca TypeScript, `ruff` y `mypy` sin errores nuevos. Reporta lo que se ejecutó y lo que no (`NO VERIFICADO`); una marca verde por sí sola no prueba nada.
- El CI de GitHub puede estar inactivo por facturación: la verificación local es obligatoria.
- Las recorridas visuales de la interfaz se hacen en el navegador integrado y no sustituyen las pruebas del backend.

## Código
- Identificadores, comentarios y mensajes de commit en inglés, sin acentos. El texto que ve el usuario, en español, vive solo en `frontend/src/copy/` (único lugar exento del verificador de idioma). No se eluden los hooks (`.githooks`, `.claude/hooks/block-main-git.sh`).
- Cambios acotados, simples y con nombres claros; sin código muerto ni defensas innecesarias; consistentes con el proyecto. Lee antes de editar.
- Python con `cd backend && uv run --extra dev ...` (el `python3` de esta máquina no es el del proyecto). Secretos solo por archivo o variable de entorno, nunca en registros ni en el repositorio.
- Los motores de IA (transcripción, hablantes, resumen) corren nativos en el Mac (fuera de Docker, puertos 8001–8003) para aprovechar el hardware; el resto corre en **Docker Desktop** como el proyecto de Compose **`sauri`** (portal, api, worker, postgres, minio/RustFS, rabbitmq). La arquitectura es hexagonal: cada motor tras un contrato estable, intercambiable por configuración. Servicios, puertos y comandos en `docs/architecture/overview.md` («Entorno local con Docker Desktop»).

## Seguridad del repositorio (Code changes and Git protection)
- Antes de borrar una rama o worktree con trabajo sin integrar, se archiva en `~/Proyectos/sauri-archive/`. Nunca se descartan cambios ajenos.
- No borres rutas que puedan ser enlaces simbólicos a carpetas fuera del repositorio (las skills `~/.agents/library/` ya se vaciaron una vez así). Comprueba con `test -L` antes.
- No toques archivos del dueño fuera del repositorio ni su entorno de pruebas. No hagas `git push --force`, ni commit directo a `main`.
- Docker: el proyecto `sauri` y sus volúmenes (`sauri_pgdata`, `sauri_minio-data`) son el entorno principal del dueño; nunca se borran, recrean ni reutilizan para pruebas sin su autorización. Las pruebas usan bases y contenedores desechables con otro nombre (`sauri_qa_*`, `sauri-qa-*`), solo en `127.0.0.1`, y se eliminan al terminar. Borrar contenedores, imágenes o volúmenes ajenos a una prueba propia requiere autorización del dueño.

## Dónde va cada cosa
- Documentos de producto → `docs/product/` (línea base y descubrimiento).
- Arquitectura → `docs/architecture/`.
- Operación y despliegue → `docs/operations/`.
- Referencias de diseño → `docs/design/`.
- Informes antiguos → `docs/history/`.
- Specs → `.spectra/specs/` (índice y estado en `.spectra/README.md`).
- Scripts → `scripts/` (dev, engines, platform, tests).
- Configuración de agentes → `.claude/` (Claude) y `.agents/` (Codex). Las skills son enlaces a la biblioteca del dueño, gestionada con `skills-manager`: no se modifican, copian ni borran.
- Los archivos generados (cachés, `node_modules`, builds, entornos virtuales) nunca se versionan.
