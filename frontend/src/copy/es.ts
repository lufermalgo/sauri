export const copy = {
  processing: {
    loading: "Consultando estado…",
    queued: "En cola",
    joining: "Uniéndose a la reunión",
    recording: "Grabando",
    transcribing: "Transcribiendo",
    identifying: "Identificando hablantes",
    speakerWaitExpired: "La identificación de hablantes está tardando más de lo esperado; vuelve a abrir la reunión más tarde",
    completed: "Completada",
    failed: "Fallida",
    unknown: "Estado de procesamiento no reconocido.",
    loadFailed: "No se pudo consultar el estado. Revisá tu conexión.",
    transcriptPending: "La transcripción todavía no está disponible.",
    diarizationFailed: "No se pudo consultar la identificación de hablantes.",
    failureCause: (cause?: string | null) => {
      switch (cause) {
        case "could_not_join": return "No se pudo entrar a la reunión.";
        case "meeting_cancelled": return "La reunión fue cancelada.";
        case "engine_failure":
        case "engine_failed": return "El motor no pudo procesar la grabación.";
        case "engine_contract_mismatch": return "El motor de transcripción devolvió un formato incompatible.";
        case "invalid_response": return "El motor de transcripción devolvió una respuesta inválida.";
        default: return "El procesamiento falló sin una causa reconocida.";
      }
    },
  },
  transcript: {
    unknownSpeaker: "Speaker ?",
    legacyUnknownSpeaker: "Speaker N",
    ambiguous: "Atribución de hablante incierta",
    playAt: (time: string) => `Reproducir turno en ${time}`,
    play: "Reproducir turno",
  },
  speakerReview: {
    heading: "Revisión de hablantes",
    pending: "Revisión pendiente: escuchá a cada hablante y confirmá o escribí su nombre.",
    complete: "Revisión completa.",
    dispositionLabel: (disposition: "confirmed" | "named" | "corrected" | null) => {
      switch (disposition) {
        case "confirmed": return "Confirmado";
        case "named": return "Nombrado";
        case "corrected": return "Corregido";
        default: return "Pendiente";
      }
    },
    listen: "Escuchar",
    listenTo: (label: string) => `Escuchar a ${label} en la grabación original`,
    shortInterval: "Este hablante tiene poco audio continuo (menos de 5 segundos); puede no alcanzar para reconocer su voz.",
    noInterval: "No hay un tramo de la grabación atribuido solo a este hablante para escuchar.",
    playbackUnavailable: "La grabación original no está disponible para reproducir.",
    playbackFailed: "No se pudo reproducir la grabación original.",
    nameFor: (label: string) => `Nombre para ${label}`,
    saveName: "Guardar nombre",
    saveNameFor: (label: string) => `Guardar nombre de ${label}`,
    confirm: "Confirmar",
    confirmFor: (label: string) => `Confirmar ${label}`,
    correct: "Corregir",
    correctFor: (label: string) => `Corregir nombre de ${label}`,
    saving: "Guardando…",
    saveFailed: "No se pudo guardar la revisión. Reintentá.",
    loadFailed: "No se pudo consultar la revisión de hablantes.",
    conflict: "La revisión cambió mientras la editabas. Recargá la reunión para ver la versión actual.",
    notFound: "No se encontró la revisión de hablantes de esta reunión.",
  },
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
