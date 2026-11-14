export const copy = {
  summary: {
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
    pending: "Resumen pendiente.",
    running: "Generando resumen…",
    failed: "No se pudo generar el resumen.",
    retry: "Reintentar",
    copy: "Copiar",
    copied: "Resumen copiado.",
    copyFailed: "No se pudo copiar el resumen. Revisá los permisos del portapapeles.",
    loadFailed: "No se pudo consultar el resumen. Revisá tu conexión y reintentá.",
    requestFailed: "No se pudo solicitar el resumen. Revisá tu conexión y reintentá.",
    resultUnavailable: "La solicitud terminó, pero su resumen todavía no está disponible. Reintentá la consulta.",
    failureCause: (cause?: string | null) => {
      switch (cause) {
        case "context_exceeded": return "La transcripción supera la capacidad del modelo de resumen.";
        case "summary_invalid": return "El modelo no devolvió un resumen con fuentes válidas.";
        case "llm_unavailable": return "El modelo de resumen no está disponible o agotó el tiempo de espera.";
        default: return "La generación falló sin una causa reconocida. Podés reintentar.";
      }
    },
  },
  upload: {
    title: "Subir grabación",
    submit: "Subir y procesar",
    retry: "Reintentar",
    back: "Volver a reuniones",
    fileLabel: "Archivo de grabación",
    readingMetadata: "Leyendo metadatos de la grabación…",
    uploading: "Subiendo…",
    progressLabel: "Progreso de carga",
    awaitingConfirmation: "Archivo enviado. Esperando confirmación del servidor; el procesamiento puede seguir pendiente.",
    bytesSent: (bytes: number) => `${bytes} bytes enviados`,
    percentUploaded: (percent: number) => `${percent}% de carga`,
    errors: {
      unauthenticated: "Sesión no disponible. Iniciá sesión para subir la grabación.",
      http: (status: number) => `No se pudo subir la grabación (HTTP ${status}). Reintentá la carga.`,
      invalidResponse: "El servidor no confirmó la carga. Reintentá con el mismo archivo.",
      network: "Error de red al subir la grabación. Revisá tu conexión y reintentá.",
      timeout: "La carga agotó el tiempo de espera. Reintentá la carga.",
      aborted: "La carga se interrumpió. Reintentá la carga.",
      failed: "No se pudo subir la grabación. Reintentá la carga.",
      invalidDuration: "No se pudo leer la duración de la grabación. Elegí otro archivo de audio o video.",
      unreadableRecording: "No se pudo leer la grabación. Elegí otro archivo de audio o video compatible.",
    },
  },
} as const;
