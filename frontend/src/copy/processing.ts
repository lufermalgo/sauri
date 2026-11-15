export const processing = {
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
} as const;
