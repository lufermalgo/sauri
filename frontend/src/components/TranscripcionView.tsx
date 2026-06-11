import React, { useEffect, useState } from "react";
import type { Transcripcion, TurnoDeHabla } from "@sauri/shared-types";
import { obtenerTranscripcion } from "../api";

interface TranscripcionViewProps {
  reunionId: string;
  onBack: () => void;
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

export function TranscripcionView({ reunionId, onBack }: TranscripcionViewProps) {
  const [data, setData] = useState<(Transcripcion & { turnos: TurnoDeHabla[] }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    obtenerTranscripcion(reunionId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Error al cargar transcripción");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [reunionId]);

  if (loading) return <p>Cargando transcripción...</p>;
  if (error) return <p role="alert" style={{ color: "red" }}>{error}</p>;
  if (!data) return <p>No se encontró la transcripción.</p>;

  return (
    <section>
      <button onClick={onBack}>← Volver a la lista</button>
      <h2>Transcripción</h2>
      <p>
        Idioma: {data.idioma} | Proveedor: {data.proveedor} |
        Turnos: {data.soportaTurnos ? "Sí" : "No"}
      </p>
      {data.turnos.length === 0 ? (
        <p>Sin segmentos de transcripción.</p>
      ) : (
        <ol>
          {data.turnos.map((turno) => (
            <li key={turno.id}>
              <span style={{ color: "#6b7280", marginRight: "0.5rem" }}>
                [{formatTimestamp(turno.inicioMs)} – {formatTimestamp(turno.finMs)}]
              </span>
              {turno.texto}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
