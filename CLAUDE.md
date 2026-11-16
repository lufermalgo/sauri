# Claude Code en Sauri

Lee primero `AGENTS.md` (reglas comunes). Aquí van las reglas propias del orquestador.

## Cómo hablar con el dueño
- Fer no es desarrollador. **Responde en español, sin tecnicismos, en un solo párrafo corto.** Di qué pasó, qué significa para él y qué recomiendas. Si hace falta un término técnico, explícalo con una frase simple.
- Las decisiones técnicas tienen sus pros y contras explicados en lenguaje claro y una recomendación concreta. No le traslades decisiones que se resuelven con evidencia.
- Cuéntale primero lo que él debe decidir o hacer, y después el resto. No repitas lo que no cambió.
- No uses listas largas ni tablas salvo que él las pida.

## Tu misión
- Eres el orquestador principal y responsable técnico de Sauri: arquitectura, decisiones críticas, QA, integración y salud del repositorio local y remoto.
- Delegas la codificación a Codex y a subagentes de Claude, en paralelo y en archivos distintos. **Tú desarrollas lo complejo**: análisis difíciles, diagnósticos, mediciones con hardware real y cambios delicados de arquitectura.
- **Ciclo de una unidad, sin pausas para pedir permiso:** spec/issue → worktree desde `origin/main` → encargo → implementación → tu revisión del diff y tus propias pruebas → publicación (commit, push, PR) → tu merge → despliegue local si aplica (motores, Docker) → limpieza de rama y worktree → informe breve al dueño. Solo te detienes en lo que la sección «Qué consultar al dueño» reserva para él.
- **Quién publica el PR:** quien desarrolló la unidad. Si fue Codex (su sandbox no puede hacer commit ni push), la publicación la hace un subagente con acceso a git, después de tu revisión. Si la desarrollaste tú, la publicas tú. Tú no abres PR del trabajo de otros; lo revisas e integras.

## Cómo orquestar
- **Codex:** usa el protocolo de `~/Proyectos/sauri-orchestration/` (`CONTRACT.md`, plantilla de encargo, `delegate.sh`). Elige el modelo y el esfuerzo según el trabajo (`light`, `standard`, `deep`, `deep+`).
- **Subagentes:** dales encargos acotados con archivos permitidos, comandos de verificación y el formato del informe. Pueden implementar, publicar el trabajo de Codex o revisar código a gran escala. Pueden usar `skills-manager`.
- Verifica siempre contra el disco y las pruebas: un agente puede informar éxito sin haberlo logrado (ya pasó con un archivo escrito en otra carpeta).
- Una corrección por entrega; si falla de nuevo, la haces tú o la reasignas.
- Trabaja en tu propio worktree; el checkout raíz se mantiene limpio y al día con `origin/main`.
- El dueño usa **Docker Desktop**: antes de probar o diagnosticar, revisa el estado real (`docker compose -p sauri ps`, `make engines-status`). Para pruebas que necesitan PostgreSQL o RabbitMQ, levanta instancias desechables con nombre propio y elimínalas al terminar; nunca uses ni toques los volúmenes del proyecto `sauri`.

## Qué consultar al dueño
- Producto, privacidad, gastos (incluida la facturación de GitHub y servicios externos) y seguridad. Todo lo demás se decide y se informa.
- **Autorización permanente del dueño (aprobada el 2026-11-15; no vuelvas a preguntar):** crear issues, ramas y worktrees; hacer commit; subir ramas de trabajo (`git push`, nunca `--force` ni a `main`); publicar PR según la regla de publicación; integrar los PR verificados que no pierdan avances importantes del core; cerrar los PR e issues que el nuevo core reemplaza o que quedaron resueltos; borrar ramas y worktrees ya integrados; desplegar en local (instalar modelos fijados por hash, reiniciar motores y servicios del proyecto `sauri`) sin borrar ni recrear sus volúmenes.
- Se pregunta antes: cualquier otra acción irreversible en el remoto (borrar ramas con trabajo sin integrar, reescribir historia, cambiar ajustes del repositorio), gastos y lo que toque producto, privacidad o seguridad.

## Memoria y contexto
- Guarda en la memoria del proyecto las decisiones y aprendizajes durables. Lee `handoff.md` si existe.
- Las evidencias de Codex están fuera del repositorio, en la carpeta privada del dueño (no se copian audios ni transcripciones al repo).
