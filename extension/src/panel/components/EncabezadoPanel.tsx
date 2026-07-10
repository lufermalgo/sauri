// Encabezado_Panel — Req. 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
import React from "react";
import { botonNuevaNotaHabilitado } from "../../core/captura";
import type { EstadoDeCaptura } from "../../core/types";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS, RADIUS_TOKENS } from "../../core/design/tokens";

export interface EncabezadoPanelProps {
  estadoDeCaptura: EstadoDeCaptura;
  onNuevaNota: () => void;
  errorInicio?: string | null;
}

export function EncabezadoPanel({ estadoDeCaptura, onNuevaNota, errorInicio }: EncabezadoPanelProps) {
  const habilitado = botonNuevaNotaHabilitado(estadoDeCaptura);

  return (
    <header
      style={{
        display: "flex",
        flexDirection: "column",
        gap: SPACING_TOKENS.esp2,
        padding: SPACING_TOKENS.esp4,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1
          style={{
            fontSize: TYPOGRAPHY_TOKENS.textoXl,
            fontWeight: TYPOGRAPHY_TOKENS.pesoSemibold,
            margin: 0,
          }}
        >
          REC Notas
        </h1>
        <button
          type="button"
          onClick={onNuevaNota}
          disabled={!habilitado}
          style={{
            backgroundColor: habilitado ? COLOR_TOKENS.primario : COLOR_TOKENS.textoTenue,
            color: COLOR_TOKENS.texto,
            border: "none",
            borderRadius: RADIUS_TOKENS.radioMd,
            padding: `${SPACING_TOKENS.esp2} ${SPACING_TOKENS.esp3}`,
            fontSize: TYPOGRAPHY_TOKENS.textoSm,
            fontWeight: TYPOGRAPHY_TOKENS.pesoMedio,
            cursor: habilitado ? "pointer" : "not-allowed",
          }}
        >
          + Nueva nota REC
        </button>
      </div>
      {errorInicio && (
        <p role="alert" style={{ color: COLOR_TOKENS.error, fontSize: TYPOGRAPHY_TOKENS.textoSm, margin: 0 }}>
          {errorInicio}
        </p>
      )}
    </header>
  );
}
