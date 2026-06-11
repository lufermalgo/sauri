import React, { useEffect, useState } from "react";
import { EstadoProceso } from "@sauri/shared-types";
import type { Reunion } from "@sauri/shared-types";
import { listarReuniones } from "../api";

const ESTADO_COLORS: Record<EstadoProceso, string> = {
  [EstadoProceso.EnCola]: "#6b7280",
  [EstadoProceso.Uniendose]: "#f59e0b",
  [EstadoProceso.Grabando]: "#ef4444",
  [EstadoProceso.Transcribiendo]: "#3b82f6",
  [EstadoProceso.Completado]: "#22c55e",
  [EstadoProceso.Fallido]: "#dc2626",
};

interface ReunionListProps {
  refreshKey: number;
  onSelectReunion: (reunion: Reunion) => void;
}

export function ReunionList({ refreshKey, onSelectReunion }: ReunionListProps) {
  const [reuniones, setReuniones] = useState<Reunion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    listarReuniones()
      .then((data) => {
        if (!cancelled) setReuniones(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Error al cargar reuniones");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [refreshKey]);

  if (loading) return <p>Cargando reuniones...</p>;
  if (error) return <p role="alert" style={{ color: "red" }}>{error}</p>;
  if (reuniones.length === 0) return <p>No hay reuniones registradas.</p>;

  return (
    <section>
      <h2>Reuniones</h2>
      <table>
        <thead>
          <tr>
            <th>Enlace</th>
            <th>Estado</th>
            <th>Causa de fallo</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {reuniones.map((r) => (
            <tr key={r.id}>
              <td>{r.enlaceMeet}</td>
              <td>
                <span
                  style={{
                    color: ESTADO_COLORS[r.estadoProceso],
                    fontWeight: "bold",
                  }}
                >
                  {r.estadoProceso}
                </span>
              </td>
              <td>{r.causaFallo ?? "—"}</td>
              <td>
                {r.estadoProceso === EstadoProceso.Completado && (
                  <button onClick={() => onSelectReunion(r)}>
                    Ver transcripción
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
