// Cálculo del Tiempo_De_Habla — Req. 10.1, 10.2
import type { TurnoDeHablaDTO, AsignacionDeHablanteDTO, HablanteDTO, EntradaTiempoDeHabla } from "./types";

/** Suma (fin_ms - inicio_ms) por Hablante; incluye hablantes con tiempo 0 (Req. 10.1, 10.2) */
export function calcularTiempoDeHabla(
  turnos: TurnoDeHablaDTO[],
  asignaciones: AsignacionDeHablanteDTO[],
  hablantes: HablanteDTO[]
): EntradaTiempoDeHabla[] {
  const turnosPorId = new Map(turnos.map((t) => [t.id, t]));

  return hablantes.map((hablante) => {
    const turnoIds = asignaciones
      .filter((a) => a.hablanteId === hablante.id)
      .map((a) => a.turnoId);

    const tiempoMs = turnoIds.reduce((acc, turnoId) => {
      const turno = turnosPorId.get(turnoId);
      if (!turno) return acc;
      return acc + (turno.finMs - turno.inicioMs);
    }, 0);

    return { hablante, tiempoMs };
  });
}
