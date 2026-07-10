// Marca_De_Tiempo_Formateada — Req. 11.1, 11.2, 11.3, 11.4, 11.5, 3.9, 8.3, 10.3

const PLACEHOLDER_NO_DISPONIBLE = "--:--";
const UNA_HORA_MS = 3_600_000;

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * Formatea una marca de tiempo en milisegundos según Req. 11:
 * - negativo/NaN/null/undefined → "--:--"
 * - [0, 3_600_000) → "MM:SS"
 * - >= 3_600_000 → "HH:MM:SS"
 */
export function formatearMarcaDeTiempo(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || typeof ms !== "number" || Number.isNaN(ms) || ms < 0) {
    return PLACEHOLDER_NO_DISPONIBLE;
  }

  const totalSeg = Math.floor(ms / 1000);
  const seg = totalSeg % 60;
  const min = Math.floor(totalSeg / 60) % 60;
  const horas = Math.floor(totalSeg / 3600);

  if (ms < UNA_HORA_MS) {
    return `${pad2(min)}:${pad2(seg)}`;
  }

  return `${pad2(horas)}:${pad2(min)}:${pad2(seg)}`;
}
