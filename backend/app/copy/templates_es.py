"""Owner-approved Spanish seed copy, versioned November 14, 2026.

Keep this seed immutable for migration replay; future copy changes need a new version.
User edits are stored in the database, not here.
"""

DEFAULT_CATEGORY = "General"
DEFAULT_NAME = "Resultados clave"
DEFAULT_INSTRUCTIONS = (
    "Identificación del tema principal; argumentos y puntos clave; presentación clara y estructurada"
)
DEFAULT_PROVENANCE = "propuesta del dueño 14/11/2026, editable"

# Version 2, owner-approved November 15, 2026: the default summary follows the structure of the
# owner's reference sample. Version 1 above stays untouched so migration 015 replays unchanged and
# migration 020 can recognize unedited v1 templates by their exact text.
DEFAULT_INSTRUCTIONS_V2 = (
    "Escribe un resumen claro, completo y bien estructurado de la reunión, en español, con este orden. "
    "1) Asunto principal: un párrafo de 3 a 5 frases que diga de qué trata la reunión, el contexto y la "
    "pregunta, el problema o la tensión central. "
    "2) Puntos clave y desarrollo de la discusión: entre 4 y 8 bloques temáticos en el orden en que se "
    "trataron. Cada bloque lleva un título corto que nombre el tema y quién lo planteó cuando importe, y "
    "debajo viñetas con hechos, cifras, argumentos, propuestas y dudas; usa subviñetas para fases, "
    "escenarios, definiciones o ejemplos. Conserva cifras, nombres propios, fechas y términos tal como se "
    "dijeron. Mantén separados las propuestas, las dudas o desacuerdos, las decisiones y los compromisos: "
    "escribe las decisiones como «Decisión: …» dentro del tema donde se tomaron y, si hubo próximos pasos, "
    "cierra los bloques con «Próximos pasos y compromisos», con responsable y fecha solo si se dijeron. "
    "3) Conclusión: un párrafo corto con lo acordado, lo pendiente y lo necesario para avanzar. "
    "Reglas: no menciones minutos ni marcas de tiempo; no inventes datos, personas, cifras ni decisiones; "
    "si algo no quedó claro, dilo; no expandas siglas que no estén definidas; no infieras ausencias; "
    "llama «Hablante N» (o «Hablante ?») a quien no tenga nombre asignado y conserva los nombres ya asignados."
)
DEFAULT_PROVENANCE_V2 = "propuesta del dueño 15/11/2026, editable"
