// Buscador_De_Transcripcion — Req. 9.1, 9.2, 9.3, 9.4, 9.5
import React, { useEffect, useMemo, useState } from "react";
import type { IntervencionDTO } from "../core/types";
import { coincidenciasDeTranscripcion, LIMITE_BUSQUEDA_TRANSCRIPCION, type ResultadoBusquedaTranscripcion } from "../core/busqueda";
import { SPACING_TOKENS, COLOR_TOKENS, RADIUS_TOKENS } from "../core/design/tokens";

export interface BuscadorDeTranscripcionProps {
  intervenciones: IntervencionDTO[];
  onResultado: (resultado: ResultadoBusquedaTranscripcion) => void;
}

export function BuscadorDeTranscripcion({ intervenciones, onResultado }: BuscadorDeTranscripcionProps) {
  const [texto, setTexto] = useState("");

  const resultado = useMemo(
    () => coincidenciasDeTranscripcion(intervenciones, texto),
    [intervenciones, texto]
  );

  useEffect(() => {
    onResultado(resultado);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resultado]);

  const sinCoincidencias = texto.trim().length > 0 && resultado.turnoIdsCoincidentes.length === 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp1 }}>
      <input
        type="text"
        aria-label="Buscar en la transcripción"
        placeholder="Buscar en la transcripción..."
        maxLength={LIMITE_BUSQUEDA_TRANSCRIPCION}
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        style={{
          padding: SPACING_TOKENS.esp2,
          borderRadius: RADIUS_TOKENS.radioSm,
          border: `1px solid ${COLOR_TOKENS.textoTenue}`,
        }}
      />
      {sinCoincidencias && (
        <p role="status" style={{ margin: 0, fontSize: "12px", color: COLOR_TOKENS.textoTenue }}>
          Sin coincidencias.
        </p>
      )}
    </div>
  );
}
