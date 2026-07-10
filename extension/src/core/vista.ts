// Derivación del Estado_De_Vista — Req. 12.3, 12.5, 12.6, 12.7
import type { SolicitudRemota, EstadoDeVista } from "./types";

/** Deriva el Estado_De_Vista a partir de la fase de una SolicitudRemota (Req. 12.3, 12.5-12.7) */
export function derivarEstadoDeVista<T>(solicitud: SolicitudRemota<T>): EstadoDeVista {
  switch (solicitud.fase) {
    case "inicial":
    case "en_curso":
      return "cargando";
    case "exito":
      return (solicitud.datos?.length ?? 0) > 0 ? "con_datos" : "vacio";
    case "fallo":
      return "error";
    default:
      return "error";
  }
}
