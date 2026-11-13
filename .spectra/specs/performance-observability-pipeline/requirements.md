# Requisitos — Rendimiento, precisión y observabilidad de Sauri

## Introducción

Fer pidió el 13/11/2026 a las 17:10 una propuesta de reescritura desde arquitectura de software, las tres fases SDD y una primera mejora de velocidad demostrable en 30 minutos. También pidió telemetría de llamadas, recursos, tokens, trazas y logs. Este encargo autoriza elaborar las tres fases y ejecutar una primera optimización compatible; no implica aceptación del producto ni aprobación automática de nuevas políticas de datos, gastos o proveedores.

La petición real de resumen de José María terminó correctamente: aproximadamente 758 s desde entrega a persistencia. Ollama reportó 618,588 s de evaluación de 17.839 tokens de entrada y 105,793 s de generación de 294 tokens. Estos tiempos son de una observación, no percentiles ni un benchmark controlado. Hubo contención con una prueba acústica cancelada; no se cuantificó su contribución. El adaptador actual envía la transcripción completa y descarta los contadores de uso devueltos por Ollama. La asignación de turnos recorre todos los segmentos por turno. Los motores nativos comparten recursos con otros procesos en el Mac.

**Idea fuerza:** reescribir los cuellos de botella por sustituciones pequeñas, instrumentadas y reversibles, preservando contratos y calidad; no reescribir toda la aplicación ni cambiar lenguajes por intuición.

**Alcance:** captura/subida, API, outboxes/colas, base de datos, almacenamiento, preparación de audio, ASR, diarización, atribución, resumen y entrega al portal, con presupuestos de recursos y observabilidad local. Primera entrega limitada a una etapa medible y contadores seguros; el resto queda explícitamente en backlog.

**Dependencias:** `local-platform-deployment` conserva servicios centrales Docker y motores MLX/MPS nativos; `recording-speaker-review` conserva evidencia, generaciones e incertidumbre; `meeting-summaries-templates` conserva plantillas, contratos e idempotencia; `meeting-review-playback` conserva reproducción del original. No reabre aprobaciones existentes ni da por implementadas specs documentales.

## Glosario

- **Pipeline_Sauri**: recorrido desde ingreso de grabación hasta disponibilidad de resultados, separado en etapas medibles.
- **Trabajo**: una operación de una revisión/generación con intentos identificables y estado persistido.
- **Telemetria_Local**: métricas, trazas y logs operativos sin contenido de reuniones, consultables dentro del entorno local autorizado.
- **Comparacion_Controlada**: comparación del mismo trabajo con y sin cambio, registrando versión, entrada, configuración, recursos y límites.
- **Contrato_de_Calidad**: preservación de texto, límites temporales, evidencia, incertidumbre, identidad por usuario y resultados exigidos por las specs vinculadas.

## Requisitos

### Requisito 1: Sustitución incremental y reversible
**Historia de Usuario:** Como dueño, quiero mejorar la velocidad sin perder grabaciones ni funciones existentes.
#### Criterios de Aceptación
1. THE Pipeline_Sauri SHALL conservar las grabaciones originales, nombres, generaciones y resultados existentes durante una optimización.
2. WHEN una etapa sea sustituida, THE Pipeline_Sauri SHALL conservar su contrato público o introducir una versión compatible y una reversión documentada.
3. THE Pipeline_Sauri SHALL mantener los motores nativos acelerados y los servicios centrales Docker sin migrar datos ni cambiar de proveedor externo como parte de esta spec.

### Requisito 2: Evidencia de velocidad
**Historia de Usuario:** Como dueño, quiero distinguir aceleraciones reales de estimaciones.
#### Criterios de Aceptación
1. WHEN se declare una mejora, THE Comparacion_Controlada SHALL identificar etapa, versiones, entrada, repeticiones, tiempos individuales, mediana, aceleración y equivalencia de salida.
2. THE Comparacion_Controlada SHALL diferenciar resultados de inferencia real, replay de datos reales, fixtures y cargas sintéticas.
3. THE Comparacion_Controlada SHALL NOT extrapolar una aceleración de función al tiempo completo del Pipeline_Sauri.
4. WHEN termine la ventana inicial de 30 minutos, THE Comparacion_Controlada SHALL entregar el resultado observado o un fallo/bloqueo concreto; no etiquetar una ejecución pendiente como mejora conseguida.
5. WHEN se considere lista la primera optimización, THE Comparacion_Controlada SHALL demostrar una reducción de al menos 20% de mediana en su etapa objetivo con igualdad de salida; ese umbral no es una promesa de aceleración total.

### Requisito 3: Recursos y admisión global
**Historia de Usuario:** Como usuario, quiero que trabajos pesados no se perjudiquen entre sí ni congelen la plataforma.
#### Criterios de Aceptación
1. WHEN un Trabajo solicite inferencia pesada, THE Pipeline_Sauri SHALL adquirir una reserva de recursos compartida entre ASR, diarización y resúmenes de Sauri antes de ejecutarlo.
2. WHILE no exista capacidad suficiente, THE Pipeline_Sauri SHALL mantener el Trabajo en espera veraz, sin perderlo ni reiniciarlo en bucle.
3. WHEN un proceso muera o pierda su reserva, THE Pipeline_Sauri SHALL recuperar capacidad mediante vencimiento y fencing sin permitir commits de un propietario obsoleto.
4. THE Pipeline_Sauri SHALL observar presión global del host sin detener, descargar modelos ni modificar procesos ajenos a Sauri.

### Requisito 4: Precisión protegida
**Historia de Usuario:** Como usuario, quiero resultados más rápidos sin confundir voces ni omitir contenido.
#### Criterios de Aceptación
1. WHEN se optimice la atribución temporal, THE Pipeline_Sauri SHALL producir idénticos turnos asignados, hablantes, desempates y overlap_ms para entradas equivalentes, tanto en modo acumulado como exclusivo.
2. THE Pipeline_Sauri SHALL conservar incertidumbre, silencios, solapamientos y voces distintas; SHALL NOT forzar tres hablantes ni fusionar IDs sin evidencia.
3. WHEN se proponga cambiar modelo, VAD, tamaño de ventana o estrategia de resumen, THE Comparacion_Controlada SHALL medir calidad además de velocidad antes de habilitarlo por defecto.
4. THE Pipeline_Sauri SHALL NOT generar ni guardar muestras de voz derivadas; las pruebas acústicas usarán el original y memoria/pipes sin persistir derivados.

### Requisito 5: Trazabilidad extremo a extremo
**Historia de Usuario:** Como responsable, quiero localizar dónde se demora o falla cada operación.
#### Criterios de Aceptación
1. WHEN comience un Trabajo, THE Telemetria_Local SHALL correlacionar HTTP, publicación, espera, consumo, motor, persistencia y entrega mediante trace_id/span_id y operation_id opaco.
2. WHEN se reintente un Trabajo, THE Telemetria_Local SHALL distinguir intento, motivo categorizado, duración y resultado, conservando la relación causal con el intento previo.
3. THE Telemetria_Local SHALL medir por separado espera en cola, carga de modelo, preparación, inferencia y persistencia; datos no disponibles SHALL declararse ausentes, no cero.
4. THE Telemetria_Local SHALL registrar versión de servicio, revisión de código, motor, modelo y dispositivo para comparar ejecuciones.

### Requisito 6: Consumos de llamadas, tokens y recursos
**Historia de Usuario:** Como dueño, quiero saber qué consume Sauri y cuánto cuesta cada etapa.
#### Criterios de Aceptación
1. THE Telemetria_Local SHALL contar solicitudes, errores, cancelaciones, reintentos, bytes transferidos y duraciones por servicio y operación.
2. WHEN el proveedor informe uso, THE Telemetria_Local SHALL registrar tokens de entrada/salida, tiempos de carga/evaluación/generación, tasas derivadas y cache hit si existe; SHALL distinguir uso real de estimado.
3. THE Telemetria_Local SHALL medir CPU, memoria residente, I/O y disco de procesos/contenedores de Sauri y presión/memoria disponible del host.
4. WHERE la plataforma exponga GPU/Metal y energía sin permisos adicionales, THE Telemetria_Local SHALL registrarlos con fuente y alcance; IF no están disponibles, THEN THE Telemetria_Local SHALL indicar no disponible y no atribuir consumo global a un proceso.
5. THE Telemetria_Local SHALL distinguir costo monetario configurado de consumo local; SHALL NOT inventar tarifas, energía ni costos cuando no exista una fuente.
6. THE Telemetria_Local SHALL medir consultas/pool DB, profundidad/edad de cola, outboxes pendientes, almacenamiento y latencia HTTP del portal sin texto de SQL con valores ni URLs firmadas.

### Requisito 7: Seguridad y privacidad de observabilidad
**Historia de Usuario:** Como dueño, quiero diagnosticar sin exponer mis reuniones.
#### Criterios de Aceptación
1. THE Telemetria_Local SHALL excluir audio, texto de transcripción, prompts, respuestas, nombres, emails, cookies, tokens de acceso, contraseñas, URLs firmadas y cuerpos HTTP mediante lista positiva de campos.
2. THE Telemetria_Local SHALL restringir métricas a etiquetas de cardinalidad acotada; SHALL NOT usar IDs de reunión/usuario/trabajo como etiquetas.
3. THE Telemetria_Local SHALL mantener exportación externa deshabilitada por defecto y acceso local autenticado o por red interna no publicada.
4. WHEN falle el colector, THE Pipeline_Sauri SHALL continuar con buffers acotados y un contador de pérdida de telemetría sin bloquear el resultado de producto.
5. THE Telemetria_Local SHALL limitar retención local a 7 días y almacenamiento a 512 MiB como presupuesto inicial, aplicando rotación y documentando ajuste y borrado; estos límites no autorizan borrar datos de producto.

### Requisito 8: Diagnóstico utilizable y validación
**Historia de Usuario:** Como dueño, quiero observar el estado interno y comprobar mejoras sostenidas.
#### Criterios de Aceptación
1. THE Telemetria_Local SHALL permitir consultar una línea temporal por Trabajo y paneles de latencia, errores, recursos, tokens y backlog, diferenciando ausente de cero.
2. THE Comparacion_Controlada SHALL medir p50/p95 solo con población y tamaño de muestra explícitos y medir overhead activado/desactivado con objetivo menor al 5% de mediana de etapa.
3. THE Pipeline_Sauri SHALL pasar suites pertinentes de backend/integración/regresión y la validación de lenguaje definida por el proyecto cuando cambie Rust o TypeScript.
4. WHEN se entregue una pantalla nueva o modificada, THE Pipeline_Sauri SHALL verificarla en navegador APX con captura; esa verificación no sustituye aceptación del dueño.

### Requisito 9: Límites y promoción
**Historia de Usuario:** Como dueño, quiero controlar riesgos y entender qué está instalado.
#### Criterios de Aceptación
1. THE Pipeline_Sauri SHALL distinguir documentación terminada, código publicado, integración, instalación y aceptación de producto.
2. THE Pipeline_Sauri SHALL NOT cambiar políticas de seguridad, privacidad, gasto, proveedores ni descarga de modelos sin la decisión correspondiente del dueño.
3. THE Pipeline_Sauri SHALL NOT habilitar streaming de captura, cambiar algoritmo de resumen ni reemplazar pyannote solo por inspiración externa; tales candidatos requieren comparación y cumplimiento de los requisitos anteriores.
