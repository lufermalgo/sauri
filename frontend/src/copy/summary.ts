export const summary = {
  tab: "Resumen",
  transcriptTab: "Transcripción",
  tabsLabel: "Contenido de la reunión",
  draft: "Borrador",
  topic: "Tema",
  keyPoints: "Puntos clave",
  mainTopic: "Asunto principal",
  detailedKeyPoints: "Puntos clave y desarrollo de la discusión",
  conclusion: "Conclusión",
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
  loadFailed: "No se pudo consultar el resumen. Revisa tu conexión e inténtalo de nuevo.",
  requestFailed: "No se pudo solicitar el resumen. Revisa tu conexión e inténtalo de nuevo.",
  resultUnavailable: "La solicitud terminó, pero su resumen todavía no está disponible. Vuelve a consultar.",
  failureCause: (cause?: string | null) => {
    switch (cause) {
      case "context_exceeded": return "La transcripción supera la capacidad del modelo de resumen.";
      case "summary_invalid": return "El modelo no devolvió un resumen con fuentes válidas.";
      case "llm_unavailable": return "El modelo de resumen no está disponible o agotó el tiempo de espera.";
      case "provider_auth": return "El proveedor rechazó la clave. Revísala en Motores y modelos.";
      case "provider_quota": return "Tu cuenta con el proveedor no tiene cuota.";
      case "provider_rate_limited": return "El proveedor limitó las peticiones. Inténtalo de nuevo en unos minutos.";
      case "provider_timeout": return "El proveedor tardó demasiado.";
      case "provider_unavailable": return "No pudimos conectar con el proveedor.";
      case "provider_bad_request": return "El proveedor no aceptó la petición.";
      case "provider_invalid_output": return "El modelo no devolvió un resumen válido.";
      case "provider_context_exceeded":
      case "audio_too_large": return "La reunión es demasiado larga para ese modelo.";
      case "provider_unsupported": return "Ese proveedor no sirve para generar resúmenes.";
      case "consent_missing": return "Falta aceptar el aviso de privacidad. Acéptalo en Motores y modelos.";
      case "origin_mismatch": return "La dirección no coincide con la de la clave guardada.";
      case "secret_unavailable": return "No pudimos leer la clave guardada.";
      default: return "La generación falló sin una causa reconocida. Puedes reintentar.";
    }
  },
} as const;
