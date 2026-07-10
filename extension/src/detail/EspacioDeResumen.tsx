// Espacio_De_Resumen — región estructural reservada, sin generación de IA (Req. 7.2, 7.3)
import React from "react";
import { COLOR_TOKENS, SPACING_TOKENS, RADIUS_TOKENS, TYPOGRAPHY_TOKENS } from "../core/design/tokens";

export function EspacioDeResumen() {
  return (
    <section
      aria-label="Resumen"
      style={{
        padding: SPACING_TOKENS.esp4,
        borderRadius: RADIUS_TOKENS.radioMd,
        backgroundColor: COLOR_TOKENS.superficie,
        color: COLOR_TOKENS.textoTenue,
      }}
    >
      <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textoLg, margin: 0, color: COLOR_TOKENS.texto }}>Resumen</h2>
      <p style={{ margin: `${SPACING_TOKENS.esp2} 0 0` }}>Resumen disponible próximamente.</p>
    </section>
  );
}
