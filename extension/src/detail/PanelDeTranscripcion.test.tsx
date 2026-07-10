// Prueba por ejemplo: Panel_De_Transcripcion (Req. 6.4, 6.6, 8.1-8.10, 14.3)
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PanelDeTranscripcion } from "./PanelDeTranscripcion";
import type { IntervencionDTO } from "../core/types";

const intervenciones: IntervencionDTO[] = [
  {
    turnoId: "t2",
    texto: "Segunda intervención",
    inicioMs: 5000,
    finMs: 8000,
    orden: 0,
    hablante: { id: "h1", etiqueta: "Ana Pérez", orden: 1 },
  },
  {
    turnoId: "t1",
    texto: "Primera intervención",
    inicioMs: 0,
    finMs: 4000,
    orden: 0,
    hablante: null,
  },
];

describe("PanelDeTranscripcion", () => {
  it("presenta una Intervencion por Turno con etiqueta, avatar, marca de tiempo y texto (Req. 8.1, 8.3, 8.5)", () => {
    render(<PanelDeTranscripcion estado="con_datos" intervenciones={intervenciones} onReintentar={vi.fn()} />);
    expect(screen.getByText("Segunda intervención")).toBeInTheDocument();
    expect(screen.getByText("Ana Pérez")).toBeInTheDocument();
    expect(screen.getByText("00:05")).toBeInTheDocument();
  });

  it("muestra el marcador de hablante no identificado cuando no hay Asignacion_De_Hablante (Req. 8.7)", () => {
    render(<PanelDeTranscripcion estado="con_datos" intervenciones={intervenciones} onReintentar={vi.fn()} />);
    expect(screen.getByText("Hablante no identificado")).toBeInTheDocument();
  });

  it("Estado_De_Vista cargando (Req. 8.9, 14.3)", () => {
    render(<PanelDeTranscripcion estado="cargando" intervenciones={[]} onReintentar={vi.fn()} />);
    expect(screen.getByText(/cargando/i)).toBeInTheDocument();
  });

  it("Estado_De_Vista vacio cuando la Reunion no tiene Transcripcion (Req. 8.8)", () => {
    render(<PanelDeTranscripcion estado="vacio" intervenciones={[]} onReintentar={vi.fn()} />);
    expect(screen.getByText(/no está disponible/i)).toBeInTheDocument();
  });

  it("Estado_De_Vista error con acción de reintento (Req. 8.10)", () => {
    const onReintentar = vi.fn();
    render(<PanelDeTranscripcion estado="error" intervenciones={[]} onReintentar={onReintentar} />);
    screen.getByRole("button", { name: /reintentar/i }).click();
    expect(onReintentar).toHaveBeenCalled();
  });

  it("habilita el desplazamiento vertical sobre la secuencia de Intervenciones (Req. 8.6)", () => {
    const { container } = render(
      <PanelDeTranscripcion estado="con_datos" intervenciones={intervenciones} onReintentar={vi.fn()} />
    );
    const lista = container.querySelector("ul");
    expect(lista).toHaveStyle({ overflowY: "auto" });
  });
});
