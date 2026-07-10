// Máquina de Estado_De_Captura — Req. 2.4, 2.5, 3.3, 3.4, 3.5
import type { EstadoDeCaptura, EventoCaptura } from "./types";

const TRANSICIONES: Record<EstadoDeCaptura, Partial<Record<EventoCaptura, EstadoDeCaptura>>> = {
  inactiva: { iniciar: "grabando" },
  grabando: { detener: "deteniendo" },
  deteniendo: { finalizada: "inactiva" },
};

/** Aplica un evento al Estado_De_Captura; conserva el estado si la transición no es válida (Req. 2.4, 3.3, 3.4, 3.5) */
export function aplicarEventoCaptura(
  estado: EstadoDeCaptura,
  evento: EventoCaptura
): EstadoDeCaptura {
  return TRANSICIONES[estado][evento] ?? estado;
}

/** El Boton_Nueva_Nota está habilitado sii el Estado_De_Captura es "inactiva" (Req. 2.5) */
export function botonNuevaNotaHabilitado(estado: EstadoDeCaptura): boolean {
  return estado === "inactiva";
}
