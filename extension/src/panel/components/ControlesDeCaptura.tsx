// Controles_De_Captura — Req. 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10
import React from "react";
import { formatearMarcaDeTiempo } from "../../core/tiempo";
import type { EstadoDeCaptura } from "../../core/types";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS, RADIUS_TOKENS } from "../../core/design/tokens";

export interface MicOption {
  deviceId: string | null;
  label: string;
}

export interface ControlesDeCapturaProps {
  estadoDeCaptura: EstadoDeCaptura;
  microfonos: MicOption[];
  microfonoSeleccionado?: MicOption;
  onSeleccionarMicrofono?: (mic: MicOption) => void;
  onToggleCaptura: () => void;
  onAbrirAjustes: () => void;
  tiempoTranscurridoMs: number;
  errorInicio?: string | null;
  errorMicrofono?: string | null;
}

const FUENTES_DE_AUDIO = ["Pantalla + audio"];

/** Convierte el cronómetro de la grabación en curso a "MM:SS" (Req. 3.9), reutilizando formatearMarcaDeTiempo. */
function formatearCronometro(tiempoTranscurridoMs: number): string {
  return formatearMarcaDeTiempo(tiempoTranscurridoMs);
}

export function ControlesDeCaptura({
  estadoDeCaptura,
  microfonos,
  microfonoSeleccionado,
  onSeleccionarMicrofono,
  onToggleCaptura,
  onAbrirAjustes,
  tiempoTranscurridoMs,
  errorInicio,
  errorMicrofono,
}: ControlesDeCapturaProps) {
  const grabando = estadoDeCaptura === "grabando";

  return (
    <section
      style={{
        display: "flex",
        flexDirection: "column",
        gap: SPACING_TOKENS.esp2,
        padding: `0 ${SPACING_TOKENS.esp4}`,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column" }}>
        <label style={{ fontSize: TYPOGRAPHY_TOKENS.textoSm }}>Fuente de audio</label>
        <select defaultValue={FUENTES_DE_AUDIO[0]} aria-label="Selector de fuente de audio">
          {FUENTES_DE_AUDIO.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        <label style={{ fontSize: TYPOGRAPHY_TOKENS.textoSm }}>Micrófono</label>
        {microfonos.length === 0 ? (
          <p
            role={errorMicrofono ? "alert" : undefined}
            style={{
              color: errorMicrofono ? COLOR_TOKENS.error : COLOR_TOKENS.textoTenue,
              fontSize: TYPOGRAPHY_TOKENS.textoSm,
              margin: 0,
            }}
          >
            {errorMicrofono ?? "Sin micrófonos disponibles"}
          </p>
        ) : (
          <select
            aria-label="Selector de micrófono"
            value={microfonoSeleccionado?.deviceId ?? ""}
            onChange={(e) => {
              const seleccion = microfonos.find((m) => (m.deviceId ?? "") === e.target.value);
              if (seleccion && onSeleccionarMicrofono) onSeleccionarMicrofono(seleccion);
            }}
          >
            {microfonos.map((m) => (
              <option key={m.deviceId ?? "none"} value={m.deviceId ?? ""}>
                {m.label}
              </option>
            ))}
          </select>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: SPACING_TOKENS.esp2 }}>
        <button
          type="button"
          role="switch"
          aria-checked={grabando}
          onClick={onToggleCaptura}
          disabled={estadoDeCaptura === "deteniendo"}
          style={{
            backgroundColor: grabando ? COLOR_TOKENS.grabando : COLOR_TOKENS.superficieAlterna,
            color: COLOR_TOKENS.texto,
            border: "none",
            borderRadius: RADIUS_TOKENS.radioMd,
            padding: `${SPACING_TOKENS.esp2} ${SPACING_TOKENS.esp3}`,
            cursor: "pointer",
          }}
        >
          {grabando ? "Detener" : "Grabar"}
        </button>

        {grabando && (
          <span
            aria-live="polite"
            style={{ display: "flex", alignItems: "center", gap: "4px", color: COLOR_TOKENS.grabando, fontWeight: TYPOGRAPHY_TOKENS.pesoSemibold }}
          >
            <span aria-hidden="true">●</span>
            <span>{formatearCronometro(tiempoTranscurridoMs)}</span>
          </span>
        )}

        <button
          type="button"
          onClick={onAbrirAjustes}
          style={{
            marginLeft: "auto",
            background: "none",
            border: `1px solid ${COLOR_TOKENS.textoTenue}`,
            borderRadius: RADIUS_TOKENS.radioSm,
            color: COLOR_TOKENS.texto,
            padding: `${SPACING_TOKENS.esp1} ${SPACING_TOKENS.esp2}`,
            cursor: "pointer",
          }}
        >
          Ajustes
        </button>
      </div>

      {errorInicio && (
        <p role="alert" style={{ color: COLOR_TOKENS.error, fontSize: TYPOGRAPHY_TOKENS.textoSm, margin: 0 }}>
          {errorInicio}
        </p>
      )}
    </section>
  );
}
