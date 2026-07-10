// Ordenamientos deterministas — Req. 4.6, 8.2, 10.4
import type { NotaDTO, IntervencionDTO, EntradaTiempoDeHabla } from "./types";

/** Notas: desc. por creadaEn, desempate asc. por reunionId (Req. 4.6) */
export function ordenarNotas(notas: NotaDTO[]): NotaDTO[] {
  return [...notas].sort((a, b) => {
    const fa = a.creadaEn ? new Date(a.creadaEn).getTime() : 0;
    const fb = b.creadaEn ? new Date(b.creadaEn).getTime() : 0;
    if (fa !== fb) return fb - fa;
    return a.reunionId < b.reunionId ? -1 : a.reunionId > b.reunionId ? 1 : 0;
  });
}

/** Intervenciones: asc. por (inicio_ms, orden) (Req. 8.2) */
export function ordenarIntervenciones(intervenciones: IntervencionDTO[]): IntervencionDTO[] {
  return [...intervenciones].sort((a, b) => {
    if (a.inicioMs !== b.inicioMs) return a.inicioMs - b.inicioMs;
    return a.orden - b.orden;
  });
}

/** Vista_Tiempo_De_Habla: desc. por tiempoMs, desempate asc. por orden (Req. 10.4) */
export function ordenarTiempoDeHabla(entradas: EntradaTiempoDeHabla[]): EntradaTiempoDeHabla[] {
  return [...entradas].sort((a, b) => {
    if (a.tiempoMs !== b.tiempoMs) return b.tiempoMs - a.tiempoMs;
    return a.hablante.orden - b.hablante.orden;
  });
}
