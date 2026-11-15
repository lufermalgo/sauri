export const summary = {
  tab: "Resumen",
  transcriptTab: "Transcripción",
  tabsLabel: "Contenido de la reunión",
  draft: "Borrador",
  topic: "Tema",
  keyPoints: "Puntos clave",
  sources: "Fuentes",
  sourceAt: (time: string) => `Ir a la fuente en ${time}`,
  loading: "Cargando resumen…",
  empty: "Todavía no hay un resumen de esta reunión.",
  generate: "Generar resumen",
  submitting: "Solicitando resumen…",
  generatingBadge: "Generando",
  generating: "Redactando el resumen…",
  generatingHelp: "El resumen toma unos minutos. Cuando esté listo aparece aquí, con la etiqueta «Borrador».",
  waitingTitle: "El resumen se genera solo.",
  waitingBody: "Empezará en cuanto termine la transcripción; no tienes que hacer nada.",
  failed: "No se pudo generar el resumen.",
  retry: "Reintentar",
  copy: "Copiar",
  download: "Descargar",
  actions: "Acciones del resumen",
  copied: "Resumen copiado.",
  copyFailed: "No se pudo copiar el resumen. Revisa los permisos del portapapeles.",
  loadFailed: "No se pudo consultar el resumen. Revisa tu conexión e inténtalo de nuevo.",
  requestFailed: "No se pudo solicitar el resumen. Revisa tu conexión e inténtalo de nuevo.",
  resultUnavailable: "La solicitud terminó, pero su resumen todavía no está disponible. Vuelve a consultar.",
  failureCause: (cause?: string | null) => {
    switch (cause) {
      case "context_exceeded": return "La transcripción supera la capacidad del modelo de resumen.";
      case "summary_invalid": return "El modelo no devolvió un resumen con fuentes válidas.";
      case "llm_unavailable": return "El modelo de resumen no está disponible o agotó el tiempo de espera.";
      default: return "La generación falló sin una causa reconocida. Puedes reintentar.";
    }
  },
} as const;
