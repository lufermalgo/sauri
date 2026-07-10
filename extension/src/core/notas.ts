// Título, fecha y proyección de Notas — Req. 4.2, 4.3, 4.4, 4.5, 7.5
import type { NotaDTO, TarjetaDeNota } from "./types";

export const PLACEHOLDER_TITULO = "Nota sin título";

/** Devuelve el título original si es no-blanco, o un placeholder (Req. 4.4, 7.5) */
export function tituloParaMostrar(titulo: string | null | undefined): string {
  if (titulo === null || titulo === undefined) return PLACEHOLDER_TITULO;
  if (titulo.trim().length === 0) return PLACEHOLDER_TITULO;
  return titulo;
}

/** Formatea una fecha ISO-8601 como "D/M, HH:MM" (Req. 4.5) */
export function formatearFechaNota(creadaEn: string): string {
  const fecha = new Date(creadaEn);
  const dia = fecha.getDate();
  const mes = fecha.getMonth() + 1;
  const horas = String(fecha.getHours()).padStart(2, "0");
  const minutos = String(fecha.getMinutes()).padStart(2, "0");
  return `${dia}/${mes}, ${horas}:${minutos}`;
}

/** Proyecta Notas a Tarjetas (1:1 por reunionId) — Req. 4.2, 4.3 */
export function proyectarTarjetas(notas: NotaDTO[]): TarjetaDeNota[] {
  return notas.map((nota) => ({
    reunionId: nota.reunionId,
    tituloMostrado: tituloParaMostrar(nota.titulo),
    fechaMostrada: nota.creadaEn ? formatearFechaNota(nota.creadaEn) : "--/--, --:--",
    estadoProceso: nota.estadoProceso,
    creadaEn: nota.creadaEn,
  }));
}
