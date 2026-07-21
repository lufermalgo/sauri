// Composición de la Vista_De_Detalle — Req. 6.1-6.6, 7.1-7.6, 14.3
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { EspacioDeResumen } from "./EspacioDeResumen";
import { PanelDeTranscripcion } from "./PanelDeTranscripcion";
import { BuscadorDeTranscripcion } from "./BuscadorDeTranscripcion";
import { VistaTiempoDeHabla } from "./VistaTiempoDeHabla";
import { leerReunionId } from "../core/detailUrl";
import { derivarEstadoDeVista } from "../core/vista";
import {
  obtenerTranscripcion,
  obtenerDiarizacion,
  obtenerReunion,
  BACKEND_URL_DEFECTO,
  ErrorNoEncontrado,
} from "../core/api/client";
import { atribuirHablante } from "../core/intervenciones";
import { ordenarIntervenciones } from "../core/orden";
import { calcularTiempoDeHabla } from "../core/speakerTime";
import { tituloParaMostrar } from "../core/notas";
import type {
  SolicitudRemota,
  TurnoDeHablaDTO,
  HablanteDTO,
  AsignacionDeHablanteDTO,
} from "../core/types";
import type { ResultadoBusquedaTranscripcion } from "../core/busqueda";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS } from "../core/design/tokens";
import "../core/design/tokens.css";

const SOLICITUD_INICIAL = { fase: "inicial", datos: null, previos: null } as const;
// Referencias vacías estables: evitan que `?? []` cree un array nuevo en cada
// render, lo que rompería la memoización aguas abajo y produciría un bucle
// de renders (efecto -> setState -> render -> nueva referencia -> efecto...).
const SIN_TURNOS: TurnoDeHablaDTO[] = [];
const SIN_HABLANTES: HablanteDTO[] = [];

// Mientras la Reunion sigue procesándose (en_cola/uniendose/grabando/
// transcribiendo), la transcripción/diarización aún no existen (404) sin que
// eso signifique "no disponible" — sólo significa "todavía no". Se reintenta
// en silencio (sin pasar por el estado "cargando") hasta un estado terminal.
const ESTADOS_TERMINALES = new Set(["completado", "fallido"]);
const INTERVALO_POLLING_MS = 3000;
const MAX_INTENTOS_POLLING = 20; // ~60s

export function DetailApp() {
  const reunionId = useMemo(() => leerReunionId(window.location.href), []);

  const [solicitudTranscripcion, setSolicitudTranscripcion] = useState<SolicitudRemota<TurnoDeHablaDTO>>(
    SOLICITUD_INICIAL
  );
  const [solicitudDiarizacion, setSolicitudDiarizacion] = useState<SolicitudRemota<HablanteDTO>>(
    SOLICITUD_INICIAL
  );
  const [asignaciones, setAsignaciones] = useState<AsignacionDeHablanteDTO[]>([]);
  const [resultadoBusqueda, setResultadoBusqueda] = useState<ResultadoBusquedaTranscripcion>({
    intervenciones: [],
    turnoIdsCoincidentes: [],
    primeraCoincidenciaId: null,
  });

  const cargarTranscripcion = useCallback(
    async (silencioso = false) => {
      if (!reunionId) return;
      if (!silencioso) {
        setSolicitudTranscripcion((prev) => ({ fase: "en_curso", datos: null, previos: prev.datos }));
      }
      try {
        const transcripcion = await obtenerTranscripcion(reunionId, BACKEND_URL_DEFECTO);
        setSolicitudTranscripcion({ fase: "exito", datos: transcripcion.segmentos, previos: null });
      } catch (err) {
        if (err instanceof ErrorNoEncontrado) {
          setSolicitudTranscripcion({ fase: "exito", datos: [], previos: null });
        } else {
          setSolicitudTranscripcion((prev) => ({ fase: "fallo", datos: null, previos: prev.datos }));
        }
      }
    },
    [reunionId]
  );

  const cargarDiarizacion = useCallback(
    async (silencioso = false) => {
      if (!reunionId) return;
      if (!silencioso) {
        setSolicitudDiarizacion((prev) => ({ fase: "en_curso", datos: null, previos: prev.datos }));
      }
      try {
        const diarizacion = await obtenerDiarizacion(reunionId, BACKEND_URL_DEFECTO);
        setSolicitudDiarizacion({ fase: "exito", datos: diarizacion.hablantes, previos: null });
        setAsignaciones(diarizacion.asignaciones);
      } catch (err) {
        if (err instanceof ErrorNoEncontrado) {
          setSolicitudDiarizacion({ fase: "exito", datos: [], previos: null });
          setAsignaciones([]);
        } else {
          setSolicitudDiarizacion((prev) => ({ fase: "fallo", datos: null, previos: prev.datos }));
        }
      }
    },
    [reunionId]
  );

  useEffect(() => {
    if (!reunionId) return;
    let cancelado = false;

    async function cicloPolling() {
      await cargarTranscripcion();
      await cargarDiarizacion();

      for (let intento = 0; intento < MAX_INTENTOS_POLLING && !cancelado; intento++) {
        const reunion = await obtenerReunion(reunionId!, BACKEND_URL_DEFECTO).catch(() => null);
        // Si la consulta de estado falla (nota inexistente, error de red), no
        // tiene sentido seguir reintentando por 60s — se detiene el polling.
        if (cancelado || !reunion || ESTADOS_TERMINALES.has(reunion.estadoProceso)) break;

        await new Promise((resolve) => setTimeout(resolve, INTERVALO_POLLING_MS));
        if (cancelado) break;
        await cargarTranscripcion(true);
        await cargarDiarizacion(true);
      }
    }

    cicloPolling();
    return () => {
      cancelado = true;
    };
  }, [reunionId, cargarTranscripcion, cargarDiarizacion]);

  const turnos = solicitudTranscripcion.datos ?? solicitudTranscripcion.previos ?? SIN_TURNOS;
  const hablantes = solicitudDiarizacion.datos ?? solicitudDiarizacion.previos ?? SIN_HABLANTES;

  const intervenciones = useMemo(
    () => ordenarIntervenciones(turnos.map((turno) => atribuirHablante(turno, asignaciones, hablantes))),
    [turnos, asignaciones, hablantes]
  );

  const entradasTiempoDeHabla = useMemo(
    () => calcularTiempoDeHabla(turnos, asignaciones, hablantes),
    [turnos, asignaciones, hablantes]
  );

  if (!reunionId) {
    return (
      <div style={{ padding: SPACING_TOKENS.esp5, color: COLOR_TOKENS.texto }}>
        <p style={{ color: COLOR_TOKENS.error }}>Esta nota no existe.</p>
      </div>
    );
  }

  const estadoTranscripcion = derivarEstadoDeVista(solicitudTranscripcion);
  const estadoDiarizacion = derivarEstadoDeVista(solicitudDiarizacion);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: SPACING_TOKENS.esp5,
        padding: SPACING_TOKENS.esp5,
        color: COLOR_TOKENS.texto,
        backgroundColor: COLOR_TOKENS.fondo,
        minHeight: "100vh",
      }}
    >
      <h1 style={{ fontSize: TYPOGRAPHY_TOKENS.textoXl, margin: 0 }}>{tituloParaMostrar(null)}</h1>

      <EspacioDeResumen />

      <div style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp3 }}>
        <BuscadorDeTranscripcion intervenciones={intervenciones} onResultado={setResultadoBusqueda} />
        <PanelDeTranscripcion
          estado={estadoTranscripcion}
          intervenciones={intervenciones}
          turnoIdsCoincidentes={resultadoBusqueda.turnoIdsCoincidentes}
          primeraCoincidenciaId={resultadoBusqueda.primeraCoincidenciaId}
          onReintentar={cargarTranscripcion}
        />
      </div>

      <VistaTiempoDeHabla
        estado={estadoDiarizacion}
        entradas={entradasTiempoDeHabla}
        onReintentar={cargarDiarizacion}
      />
    </div>
  );
}
