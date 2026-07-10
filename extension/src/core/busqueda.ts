// Filtros de búsqueda — Req. 5, 9
import type { NotaDTO, IntervencionDTO, FiltroDeNotas } from "./types";

export const LIMITE_BUSQUEDA_NOTAS = 100;
export const LIMITE_BUSQUEDA_TRANSCRIPCION = 200;

function normalizar(texto: string): string {
  return texto.trim().toLowerCase();
}

/** Filtra Notas por conjunción de texto de título y criterio (Req. 5.1, 5.2, 5.3, 5.4, 5.6, 5.7) */
export function filtrarNotas(
  notas: NotaDTO[],
  texto: string,
  filtro: FiltroDeNotas
): NotaDTO[] {
  const textoAcotado = (texto ?? "").slice(0, LIMITE_BUSQUEDA_NOTAS);
  const textoNorm = normalizar(textoAcotado);
  const busquedaActiva = textoNorm.length > 0;

  return notas.filter((nota) => {
    if (busquedaActiva) {
      const tituloNorm = normalizar(nota.titulo ?? "");
      if (!tituloNorm.includes(textoNorm)) return false;
    }
    if (filtro.estadoProceso && nota.estadoProceso !== filtro.estadoProceso) return false;
    if (filtro.desde && nota.creadaEn && new Date(nota.creadaEn) < new Date(filtro.desde)) return false;
    if (filtro.hasta && nota.creadaEn && new Date(nota.creadaEn) > new Date(filtro.hasta)) return false;
    return true;
  });
}

export interface ResultadoBusquedaTranscripcion {
  intervenciones: IntervencionDTO[];
  turnoIdsCoincidentes: string[];
  primeraCoincidenciaId: string | null;
}

/** Busca coincidencias dentro de las Intervenciones sin alterar orden/conjunto (Req. 9.1, 9.2, 9.3, 9.4, 9.5) */
export function coincidenciasDeTranscripcion(
  intervenciones: IntervencionDTO[],
  texto: string
): ResultadoBusquedaTranscripcion {
  const textoAcotado = (texto ?? "").slice(0, LIMITE_BUSQUEDA_TRANSCRIPCION);
  const textoNorm = textoAcotado.trim().toLowerCase();

  if (textoNorm.length === 0) {
    return { intervenciones, turnoIdsCoincidentes: [], primeraCoincidenciaId: null };
  }

  const coincidentes = intervenciones.filter((i) => i.texto.toLowerCase().includes(textoNorm));
  let primeraCoincidenciaId: string | null = null;
  if (coincidentes.length > 0) {
    const primera = coincidentes.reduce((min, i) => (i.inicioMs < min.inicioMs ? i : min));
    primeraCoincidenciaId = primera.turnoId;
  }

  return {
    intervenciones,
    turnoIdsCoincidentes: coincidentes.map((i) => i.turnoId),
    primeraCoincidenciaId,
  };
}
