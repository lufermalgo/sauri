// Vista_Tiempo_De_Habla — Req. 10.1-10.7
import React from "react";
import type { EstadoDeVista, EntradaTiempoDeHabla } from "../core/types";
import { formatearMarcaDeTiempo } from "../core/tiempo";
import { inicialesDeEtiqueta, colorDeAvatar } from "../core/hablantes";
import { ordenarTiempoDeHabla } from "../core/orden";
import { COLOR_TOKENS, SPACING_TOKENS, RADIUS_TOKENS, TYPOGRAPHY_TOKENS } from "../core/design/tokens";

export interface VistaTiempoDeHablaProps {
  estado: EstadoDeVista;
  entradas: EntradaTiempoDeHabla[];
  onReintentar: () => void;
}

export function VistaTiempoDeHabla({ estado, entradas, onReintentar }: VistaTiempoDeHablaProps) {
  const ordenadas = ordenarTiempoDeHabla(entradas);

  return (
    <section aria-label="Tiempo de habla" style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp2 }}>
      <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textoLg, margin: 0 }}>Tiempo de habla</h2>

      {estado === "cargando" && <p>Cargando tiempo de habla...</p>}

      {estado === "error" && (
        <div>
          <p style={{ color: COLOR_TOKENS.error }}>No se pudo cargar el tiempo de habla.</p>
          <button type="button" onClick={onReintentar}>
            Reintentar
          </button>
        </div>
      )}

      {estado === "vacio" && <p>El tiempo de habla no está disponible para esta nota.</p>}

      {estado === "con_datos" && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp2 }}>
          {ordenadas.map((entrada) => (
            <li
              key={entrada.hablante.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: SPACING_TOKENS.esp3,
                padding: SPACING_TOKENS.esp2,
                borderRadius: RADIUS_TOKENS.radioMd,
                backgroundColor: COLOR_TOKENS.superficie,
              }}
            >
              <div
                aria-hidden
                style={{
                  flexShrink: 0,
                  width: "28px",
                  height: "28px",
                  borderRadius: "50%",
                  backgroundColor: colorDeAvatar(entrada.hablante.orden),
                  color: COLOR_TOKENS.texto,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: TYPOGRAPHY_TOKENS.textoSm,
                  fontWeight: TYPOGRAPHY_TOKENS.pesoSemibold,
                }}
              >
                {inicialesDeEtiqueta(entrada.hablante.etiqueta)}
              </div>
              <span style={{ fontWeight: TYPOGRAPHY_TOKENS.pesoMedio }}>{entrada.hablante.etiqueta}</span>
              <span style={{ marginLeft: "auto", color: COLOR_TOKENS.textoTenue, fontSize: TYPOGRAPHY_TOKENS.textoSm }}>
                {formatearMarcaDeTiempo(entrada.tiempoMs)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
