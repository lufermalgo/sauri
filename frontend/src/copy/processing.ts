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
  summarizing: "Generando el resumen",
  stepsLabel: "Etapas del procesamiento",
  steps: {
    upload: "Subida",
    transcription: "Transcripción",
    speakers: "Hablantes",
    summary: "Resumen",
  },
  stepState: {
    done: "completada",
    current: "en curso",
    pending: "pendiente",
  },
  percent: (value: number) => `≈ ${value} %`,
  elapsed: (time: string) => `Llevamos ${time}`,
  remaining: (minutes: number) => minutes <= 1
    ? "Falta alrededor de un minuto, estimado"
    : `Faltan unos ${minutes} min, estimado`,
  remainingUnderMinute: "Falta menos de un minuto, estimado",
  overtime: "Está tardando un poco más de lo normal…",
  noEstimate: "Sin estimación de tiempo para esta grabación.",
  explain: {
    queued: "Tu grabación está en la fila y empezará en cuanto el motor quede libre.",
    transcription: (audioMinutes: number | null, stageMinutes: number | null) =>
      audioMinutes && stageMinutes
        ? `Convirtiendo el audio en texto. Una reunión de ${audioMinutes} ${audioMinutes === 1 ? "minuto" : "minutos"} tarda unos ${stageMinutes} ${stageMinutes === 1 ? "minuto" : "minutos"}.`
        : "Convirtiendo el audio en texto.",
    speakers: "Reconociendo quién habla en cada momento. Suele tardar menos de un minuto.",
    summary: (stageMinutes: number | null) => stageMinutes
      ? `Escribiendo el resumen y los puntos clave. Para esta reunión tarda unos ${stageMinutes} ${stageMinutes === 1 ? "minuto" : "minutos"}.`
      : "Escribiendo el resumen y los puntos clave.",
    overtime: "Sigue trabajando; no tienes que hacer nada.",
  },
  leaveHint: "Puedes salir de esta página: el trabajo sigue y aquí verás el resultado.",
  doneTitle: "Completada",
  doneBody: "Tu reunión ya está lista: transcripción, hablantes y resumen.",
  announce: (stage: string, percent: number | null, minutes: number | null) =>
    [stage, percent === null ? null : `aproximadamente ${percent} por ciento`,
      minutes === null ? null : minutes <= 1 ? "falta alrededor de un minuto" : `faltan unos ${minutes} minutos`,
    ].filter(Boolean).join(", "),
  libraryProgress: (stage: string, percent: number | null) =>
    percent === null ? stage : `${stage} · ≈ ${percent} %`,
  libraryOvertime: (stage: string) => `${stage} · tardando más de lo normal`,
  libraryProgressLabel: "Progreso estimado del procesamiento",
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
