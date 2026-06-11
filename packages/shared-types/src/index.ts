/**
 * @sauri/shared-types
 *
 * Tipos de dominio compartidos entre la extensión de Chrome y el frontend web.
 * Reflejan el modelo de datos definido en design.md.
 */

// --- Enums ---

/** Estado del ciclo de vida de la captura y transcripción de una Reunion. */
export enum EstadoProceso {
  EnCola = "en cola",
  Uniendose = "uniéndose",
  Grabando = "grabando",
  Transcribiendo = "transcribiendo",
  Completado = "completado",
  Fallido = "fallido",
}

/** Causa de fallo registrada cuando el estado es "fallido". */
export enum CausaFallo {
  NoPudoUnirse = "no pudo unirse",
  ReunionCancelada = "reunión cancelada",
  FalloDelMotor = "fallo del motor",
}

/** Origen del registro de la Reunion. */
export enum OrigenReunion {
  Enlace = "enlace",
  InvitacionCalendario = "invitacion_calendario",
  Manual = "manual",
}

/** Origen de la captura de la grabación. */
export enum OrigenCaptura {
  ExtensionChrome = "extension_chrome",
  BotServidor = "bot_servidor",
}

// --- Interfaces ---

/** Registro de una sesión de Google Meet en sauri. */
export interface Reunion {
  id: string;
  enlaceMeet: string;
  origen: OrigenReunion;
  idInvitacionCalendario?: string;
  horaInicioProgramada?: string;
  estadoProceso: EstadoProceso;
  causaFallo?: CausaFallo;
  creadaPor: string;
  creadaEn: string;
}

/** Contenedor de la grabación de una reunión (audio + video). */
export interface GrabacionDeSesion {
  id: string;
  reunionId: string;
  claveIdempotencia: string;
  origenCaptura: OrigenCaptura;
  audioRef: string;
  videoRef?: string;
  duracionSegundos: number;
  interrumpida: boolean;
  expiraEn?: string;
  finalizadaEn: string;
}

/** Documento de transcripción generado a partir de la pista de audio. */
export interface Transcripcion {
  id: string;
  reunionId: string;
  idioma: string;
  proveedor: string;
  soportaTurnos: boolean;
  expiraEn?: string;
  creadaEn: string;
}

/** Segmento temporal de habla dentro de una Transcripcion. */
export interface TurnoDeHabla {
  id: string;
  transcripcionId: string;
  texto: string;
  inicioMs: number;
  finMs: number;
  orden: number;
}
