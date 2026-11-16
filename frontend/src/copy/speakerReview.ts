export const speakerReview = {
  heading: "Hablantes",
  confirmedState: "Confirmada",
  pendingState: "Pendiente de nombre",
  selectSpeaker: (label: string) => `Editar ${label}`,
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
  stop: "Detener",
  stopFor: (label: string) => `Detener la reproducción de ${label}`,
  close: "Cerrar",
  shortInterval: "Este hablante tiene poco audio continuo (menos de 5 segundos); puede no alcanzar para reconocer su voz.",
  noInterval: "No hay un tramo de la grabación atribuido solo a este hablante para escuchar.",
  playbackUnavailable: "La grabación original no está disponible para reproducir.",
  playbackFailed: "No se pudo reproducir la grabación original.",
  nameFor: (label: string) => `Nombre para ${label}`,
  saveName: "Guardar",
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
} as const;
