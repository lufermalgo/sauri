// Tipos compartidos del núcleo (extension/src/core). Sin dependencias de DOM/red.

export type EstadoDeCaptura = "inactiva" | "grabando" | "deteniendo";
export type EventoCaptura = "iniciar" | "detener" | "finalizada" | "fallo_inicio";

export type EstadoDeVista = "cargando" | "con_datos" | "vacio" | "error";

export interface SolicitudRemota<T> {
  fase: "inicial" | "en_curso" | "exito" | "fallo";
  datos: T[] | null;
  previos: T[] | null;
}

export interface NotaDTO {
  reunionId: string;
  titulo: string | null;
  estadoProceso: string;
  creadaEn: string | null;
}

export interface TarjetaDeNota {
  reunionId: string;
  tituloMostrado: string;
  fechaMostrada: string;
  estadoProceso: string;
  creadaEn: string | null;
}

export interface FiltroDeNotas {
  estadoProceso?: string;
  desde?: string; // ISO-8601
  hasta?: string; // ISO-8601
}

export interface TurnoDeHablaDTO {
  id: string;
  texto: string;
  inicioMs: number;
  finMs: number;
  orden: number;
}

export interface TranscripcionDTO {
  transcripcionId: string;
  reunionId: string;
  segmentos: TurnoDeHablaDTO[];
}

export interface HablanteDTO {
  id: string;
  etiqueta: string;
  orden: number;
}

export interface AsignacionDeHablanteDTO {
  turnoId: string;
  hablanteId: string;
}

export interface DiarizacionDTO {
  diarizacionId: string;
  reunionId: string;
  estadoDiarizacion: string;
  numHablantes: number;
  hablantes: HablanteDTO[];
  asignaciones: AsignacionDeHablanteDTO[];
}

export interface IntervencionDTO {
  turnoId: string;
  texto: string;
  inicioMs: number;
  finMs: number;
  orden: number;
  hablante: HablanteDTO | null;
}

export interface EntradaTiempoDeHabla {
  hablante: HablanteDTO;
  tiempoMs: number;
}

export interface IntentoDeAutenticacion {
  exito: boolean;
  enMs: number;
}
