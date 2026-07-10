// Prueba por ejemplo: Buscador_De_Transcripcion (Req. 9.1-9.5)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BuscadorDeTranscripcion } from "./BuscadorDeTranscripcion";
import type { IntervencionDTO } from "../core/types";

const intervenciones: IntervencionDTO[] = [
  { turnoId: "t1", texto: "Hablemos del presupuesto", inicioMs: 0, finMs: 1000, orden: 0, hablante: null },
  { turnoId: "t2", texto: "El PRESUPUESTO ya se aprobó", inicioMs: 2000, finMs: 3000, orden: 0, hablante: null },
];

describe("BuscadorDeTranscripcion", () => {
  it("reporta coincidencias case-insensitive y la primera por inicio_ms (Req. 9.1, 9.2)", async () => {
    const onResultado = vi.fn();
    render(<BuscadorDeTranscripcion intervenciones={intervenciones} onResultado={onResultado} />);
    fireEvent.change(screen.getByLabelText(/buscar en la transcripción/i), { target: { value: "presupuesto" } });

    await waitFor(() => {
      const ultimaLlamada = onResultado.mock.calls.at(-1)?.[0];
      expect(ultimaLlamada.turnoIdsCoincidentes).toEqual(["t1", "t2"]);
      expect(ultimaLlamada.primeraCoincidenciaId).toBe("t1");
    });
  });

  it("limpia los resaltados y conserva el orden original con texto en blanco (Req. 9.3)", async () => {
    const onResultado = vi.fn();
    render(<BuscadorDeTranscripcion intervenciones={intervenciones} onResultado={onResultado} />);
    fireEvent.change(screen.getByLabelText(/buscar en la transcripción/i), { target: { value: "   " } });

    await waitFor(() => {
      const ultimaLlamada = onResultado.mock.calls.at(-1)?.[0];
      expect(ultimaLlamada.turnoIdsCoincidentes).toEqual([]);
      expect(ultimaLlamada.intervenciones).toEqual(intervenciones);
    });
  });

  it("indica ausencia de coincidencias sin alterar las Intervenciones (Req. 9.4)", async () => {
    render(<BuscadorDeTranscripcion intervenciones={intervenciones} onResultado={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/buscar en la transcripción/i), { target: { value: "inexistente" } });
    await waitFor(() => expect(screen.getByText(/sin coincidencias/i)).toBeInTheDocument());
  });

  it("limita el texto de búsqueda a 200 caracteres (Req. 9.5)", () => {
    render(<BuscadorDeTranscripcion intervenciones={intervenciones} onResultado={vi.fn()} />);
    expect(screen.getByLabelText(/buscar en la transcripción/i)).toHaveAttribute("maxLength", "200");
  });
});
