# Sauri

Plataforma interna para grabar sesiones virtuales y ofrecer transcripciones con identificación de hablantes y resumen. Este archivo reúne las reglas para todos los agentes (Claude, Codex y subagentes). `CLAUDE.md` agrega las reglas propias del orquestador.

## Quién hace qué
- **Fer (dueño):** decide producto, privacidad, gastos y seguridad. Acepta el producto al final. Prueba con sus propias grabaciones.
- **Claude (orquestador):** diseña la arquitectura, toma las decisiones técnicas críticas, revisa la calidad (QA), integra los PR y mantiene el repositorio local y remoto limpio y al día.
- **Codex y subagentes de Claude:** implementan código y pruebas, en paralelo, siempre en archivos distintos. Los subagentes también pueden revisar y leer código a gran escala.
- No existe ni se usa APX, ni tarjetas de tarea, ni agentes con nombre propio. La trazabilidad vive en los issues de GitHub, los PR y el `tasks.md` de cada spec.

## Alcance
- Haz solo el trabajo pedido o aprobado. No crees alternativas paralelas, simuladores, entregas de relleno ni funciones fuera de alcance.
- `PRODUCT_BASELINE.md` y las decisiones del dueño definen el alcance. Las notas de descubrimiento y las specs históricas no autorizan trabajo nuevo.
- Consulta al dueño solo cambios de producto, privacidad, gastos o seguridad. Las decisiones técnicas se resuelven con evidencia y se le explican de forma simple.
- Nada sale de la máquina: el audio, las transcripciones y los resúmenes se procesan localmente. Un servicio externo (p. ej. un modelo de lenguaje en la nube) solo se usa si el dueño lo configura de forma explícita.

## Cómo se trabaja
1. **Spec antes de código:** `.spectra/specs/<slug>/` con `requirements.md` → `design.md` → `tasks.md` (skills `spectra-req`, `spectra-design`, `spectra-tasks`; `spectra-bugfix` para fallos). Respeta las fases ya aprobadas. Documentación terminada no es código ni aceptación.
2. **Una unidad de entrega = un issue, una rama y un worktree propios**, creados desde `origin/main` en `.worktrees/`. Nunca se trabaja en el checkout raíz ni en `main`.
3. **Cada encargo incluye:** spec y tarea, issue, objetivo, alcance y exclusiones, archivos permitidos, criterios de aceptación y comandos de verificación.
4. **Implementa Codex o un subagente; Claude revisa el diff, ejecuta las pruebas por su cuenta e integra.** Un informe de un agente nunca se acepta sin verificarlo.
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
- Los motores de audio corren nativos en el Mac (fuera de Docker) para aprovechar el hardware; el resto, en Docker Compose. La arquitectura es hexagonal: cada motor tras un contrato estable, intercambiable por configuración. Ver `docs/ARCHITECTURE.md`.

## Seguridad del repositorio (Code changes and Git protection)
- Antes de borrar una rama o worktree con trabajo sin integrar, se archiva en `~/Proyectos/sauri-archive/`. Nunca se descartan cambios ajenos.
- No borres rutas que puedan ser enlaces simbólicos a carpetas fuera del repositorio (las skills `~/.agents/library/` ya se vaciaron una vez así). Comprueba con `test -L` antes.
- No toques archivos del dueño fuera del repositorio ni su entorno de pruebas. No hagas `git push --force`, ni commit directo a `main`.
