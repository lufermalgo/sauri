export const upload = {
  title: "Subir grabación",
  submit: "Subir y procesar",
  retry: "Reintentar",
  heading: "Subir una grabación",
  intro: "Elige el audio o el video de tu reunión y Sauri se encarga del resto.",
  back: "Volver a la biblioteca",
  dropTitle: "Arrastra aquí tu grabación",
  dropHint: "o elígela desde tu equipo",
  fileLabel: "Elegir archivo",
  selectedFileHeading: "Archivo elegido",
  sizeMb: (bytes: number) => bytes < 52429
    ? "menos de 0,1 MB"
    : `${(bytes / 1048576).toLocaleString("es", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} MB`,
  duration: (seconds: number) => {
    const total = Math.max(0, Math.round(seconds));
    return `${Math.floor(total / 60).toString().padStart(2, "0")}:${(total % 60).toString().padStart(2, "0")}`;
  },
  remove: "Quitar",
  errorHeading: "No se pudo subir la grabación.",
  readingMetadata: "Leyendo metadatos de la grabación…",
  uploading: "Subiendo…",
  transferHeading: "Subiendo grabación…",
  progressSectionLabel: "Subida en curso",
  progressLabel: "Progreso de la subida",
  transferHelp: "No cierres esta pestaña hasta que termine. Cuando llegue al 100 %, abriremos la reunión y verás cómo avanza el proceso.",
  transferred: (loaded: number, total: number, percent: number) => {
    const mb = (bytes: number) => `${(bytes / 1048576).toLocaleString("es", { maximumFractionDigits: bytes < 10485760 ? 1 : 0 })} MB`;
    return `${mb(loaded)} de ${mb(total)} · ${percent} %`;
  },
  awaitingConfirmation: "Archivo enviado. Esperando confirmación del servidor; el procesamiento puede seguir pendiente.",
  bytesSent: (bytes: number) => `${bytes} bytes enviados`,
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
} as const;
