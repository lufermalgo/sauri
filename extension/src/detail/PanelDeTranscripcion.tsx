// Panel_De_Transcripcion e Intervencion — Req. 6.4, 6.6, 8.1-8.10, 14.3
import React, { useEffect, useRef } from "react";
import type { EstadoDeVista, IntervencionDTO } from "../core/types";
import { formatearMarcaDeTiempo } from "../core/tiempo";
import { inicialesDeEtiqueta, colorDeAvatar } from "../core/hablantes";
import { ETIQUETA_HABLANTE_NO_IDENTIFICADO } from "../core/intervenciones";
import { COLOR_TOKENS, SPACING_TOKENS, RADIUS_TOKENS, TYPOGRAPHY_TOKENS } from "../core/design/tokens";

export interface PanelDeTranscripcionProps {
  estado: EstadoDeVista;
  intervenciones: IntervencionDTO[];
  turnoIdsCoincidentes?: string[];
  primeraCoincidenciaId?: string | null;
  onReintentar: () => void;
}

export function PanelDeTranscripcion({
  estado,
  intervenciones,
  turnoIdsCoincidentes = [],
  primeraCoincidenciaId = null,
  onReintentar,
}: PanelDeTranscripcionProps) {
  const refsPorTurno = useRef<Map<string, HTMLLIElement>>(new Map());

  useEffect(() => {
    if (!primeraCoincidenciaId) return;
    refsPorTurno.current.get(primeraCoincidenciaId)?.scrollIntoView({ block: "nearest" });
  }, [primeraCoincidenciaId]);

  return (
    <section aria-label="Transcripción" style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp2 }}>
      <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textoLg, margin: 0 }}>Transcripción</h2>

      {estado === "cargando" && <p>Cargando transcripción...</p>}

      {estado === "error" && (
        <div>
          <p style={{ color: COLOR_TOKENS.error }}>No se pudo cargar la transcripción.</p>
          <button type="button" onClick={onReintentar}>
            Reintentar
          </button>
        </div>
      )}

      {estado === "vacio" && <p>La transcripción no está disponible para esta nota.</p>}

      {estado === "con_datos" && (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: SPACING_TOKENS.esp3,
            maxHeight: "480px",
            overflowY: "auto",
          }}
        >
          {intervenciones.map((intervencion) => {
            const etiqueta = intervencion.hablante?.etiqueta ?? ETIQUETA_HABLANTE_NO_IDENTIFICADO;
            const color = intervencion.hablante ? colorDeAvatar(intervencion.hablante.orden) : COLOR_TOKENS.textoTenue;
            const resaltada = turnoIdsCoincidentes.includes(intervencion.turnoId);

            return (
              <li
                key={intervencion.turnoId}
                ref={(el) => {
                  if (el) refsPorTurno.current.set(intervencion.turnoId, el);
                  else refsPorTurno.current.delete(intervencion.turnoId);
                }}
                data-highlighted={resaltada}
                style={{
                  display: "flex",
                  gap: SPACING_TOKENS.esp3,
                  padding: SPACING_TOKENS.esp2,
                  borderRadius: RADIUS_TOKENS.radioMd,
                  backgroundColor: resaltada ? COLOR_TOKENS.superficieAlterna : "transparent",
                }}
              >
                <div
                  aria-hidden
                  style={{
                    flexShrink: 0,
                    width: "32px",
                    height: "32px",
                    borderRadius: "50%",
                    backgroundColor: color,
                    color: COLOR_TOKENS.texto,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: TYPOGRAPHY_TOKENS.textoSm,
                    fontWeight: TYPOGRAPHY_TOKENS.pesoSemibold,
                  }}
                >
                  {inicialesDeEtiqueta(etiqueta)}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ display: "flex", gap: SPACING_TOKENS.esp2, alignItems: "baseline" }}>
                    <span style={{ fontWeight: TYPOGRAPHY_TOKENS.pesoMedio }}>{etiqueta}</span>
                    <span style={{ fontSize: TYPOGRAPHY_TOKENS.textoSm, color: COLOR_TOKENS.textoTenue }}>
                      {formatearMarcaDeTiempo(intervencion.inicioMs)}
                    </span>
                  </div>
                  <p style={{ margin: 0 }}>{intervencion.texto}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
