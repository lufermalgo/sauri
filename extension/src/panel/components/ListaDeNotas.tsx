// Lista_De_Notas, Tarjeta_De_Nota, Buscador_De_Notas, Filtro_De_Notas — Req. 4, 5, 6.1
import React, { useEffect, useMemo, useState } from "react";
import { proyectarTarjetas } from "../../core/notas";
import { ordenarNotas } from "../../core/orden";
import { filtrarNotas } from "../../core/busqueda";
import type { NotaDTO, EstadoDeVista, FiltroDeNotas } from "../../core/types";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS, RADIUS_TOKENS } from "../../core/design/tokens";

export interface ListaDeNotasProps {
  estado: EstadoDeVista;
  notas: NotaDTO[];
  onReintentar: () => void;
  onAbrirNota: (reunionId: string) => void;
}

const DEBOUNCE_MS = 300;

export function ListaDeNotas({ estado, notas, onReintentar, onAbrirNota }: ListaDeNotasProps) {
  const [textoInput, setTextoInput] = useState("");
  const [textoDebounced, setTextoDebounced] = useState("");
  const [filtro, setFiltro] = useState<FiltroDeNotas>({});

  useEffect(() => {
    const timer = setTimeout(() => setTextoDebounced(textoInput), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [textoInput]);

  const notasFiltradas = useMemo(
    () => ordenarNotas(filtrarNotas(notas, textoDebounced, filtro)),
    [notas, textoDebounced, filtro]
  );
  const tarjetas = useMemo(() => proyectarTarjetas(notasFiltradas), [notasFiltradas]);

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp2, padding: SPACING_TOKENS.esp4 }}>
      <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textoLg, margin: 0 }}>Mis Notas</h2>

      <input
        type="text"
        placeholder="Buscar notas..."
        maxLength={100}
        value={textoInput}
        onChange={(e) => setTextoInput(e.target.value)}
        style={{
          padding: SPACING_TOKENS.esp2,
          borderRadius: RADIUS_TOKENS.radioSm,
          border: `1px solid ${COLOR_TOKENS.textoTenue}`,
        }}
      />

      <select
        aria-label="Filtro de notas por estado"
        value={filtro.estadoProceso ?? ""}
        onChange={(e) =>
          setFiltro((f) => ({ ...f, estadoProceso: e.target.value || undefined }))
        }
      >
        <option value="">Todos los estados</option>
        <option value="en_cola">En cola</option>
        <option value="grabando">Grabando</option>
        <option value="transcribiendo">Transcribiendo</option>
        <option value="completado">Completado</option>
        <option value="fallido">Fallido</option>
      </select>

      {estado === "cargando" && <p>Cargando...</p>}

      {estado === "error" && (
        <div>
          <p style={{ color: COLOR_TOKENS.error }}>No se pudo cargar el historial de notas.</p>
          <button type="button" onClick={onReintentar}>
            Reintentar
          </button>
        </div>
      )}

      {estado === "vacio" && <p>Aún no tienes notas. Crea tu primera nota para empezar.</p>}

      {estado === "con_datos" && tarjetas.length === 0 && (
        <p>No se encontraron notas que coincidan con la búsqueda.</p>
      )}

      {estado === "con_datos" && tarjetas.length > 0 && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp2 }}>
          {tarjetas.map((tarjeta) => (
            <li key={tarjeta.reunionId}>
              <button
                type="button"
                onClick={() => onAbrirNota(tarjeta.reunionId)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  background: COLOR_TOKENS.superficie,
                  border: "none",
                  borderRadius: RADIUS_TOKENS.radioMd,
                  padding: SPACING_TOKENS.esp3,
                  color: COLOR_TOKENS.texto,
                  cursor: "pointer",
                }}
              >
                <div style={{ fontWeight: TYPOGRAPHY_TOKENS.pesoMedio }}>{tarjeta.tituloMostrado}</div>
                <div style={{ fontSize: TYPOGRAPHY_TOKENS.textoSm, color: COLOR_TOKENS.textoTenue }}>
                  {tarjeta.fechaMostrada}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
