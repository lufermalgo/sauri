// Mapeo de Turnos a Intervenciones y atribución de Hablante — Req. 8.1, 8.3, 8.5, 8.7, 14.2
import type {
  TranscripcionDTO,
  TurnoDeHablaDTO,
  AsignacionDeHablanteDTO,
  HablanteDTO,
  IntervencionDTO,
} from "./types";

export const ETIQUETA_HABLANTE_NO_IDENTIFICADO = "Hablante no identificado";

/** Une un Turno con su Hablante asignado (o null si no hay asignación) — Req. 8.3, 8.7 */
export function atribuirHablante(
  turno: TurnoDeHablaDTO,
  asignaciones: AsignacionDeHablanteDTO[],
  hablantes: HablanteDTO[]
): IntervencionDTO {
  const asignacion = asignaciones.find((a) => a.turnoId === turno.id);
  const hablante = asignacion
    ? hablantes.find((h) => h.id === asignacion.hablanteId) ?? null
    : null;

  return {
    turnoId: turno.id,
    texto: turno.texto,
    inicioMs: turno.inicioMs,
    finMs: turno.finMs,
    orden: turno.orden,
    hablante,
  };
}

/** Mapea todos los Turnos de una Transcripcion a Intervenciones (sin atribución) — Req. 8.1, 8.5, 14.2 */
export function mapearIntervenciones(transcripcion: TranscripcionDTO): IntervencionDTO[] {
  return transcripcion.segmentos.map((turno) => ({
    turnoId: turno.id,
    texto: turno.texto,
    inicioMs: turno.inicioMs,
    finMs: turno.finMs,
    orden: turno.orden,
    hablante: null,
  }));
}
