// @vitest-environment jsdom
/**
 * Tests de componentes del frontend: vista de transcripción.
 *
 * Feature: meeting-capture-transcription
 * Task: 15.2 — Validates: Requirements 9.1, 9.2, 4.5
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import type { Transcripcion, TurnoDeHabla } from "@sauri/shared-types";

import { TranscripcionView } from "./TranscripcionView";
import * as api from "../api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function transcripcion(
  turnos: TurnoDeHabla[]
): Transcripcion & { turnos: TurnoDeHabla[] } {
  return {
    id: "t-1",
    reunionId: "r-1",
    idioma: "es-CO",
    proveedor: "local",
    soportaTurnos: true,
    creadaEn: new Date().toISOString(),
    turnos,
  };
}

function turno(overrides: Partial<TurnoDeHabla> = {}): TurnoDeHabla {
  return {
    id: "turno-1",
    transcripcionId: "t-1",
    texto: "Hola, buenas tardes.",
    inicioMs: 0,
    finMs: 1500,
    orden: 1,
    ...overrides,
  };
}

describe("TranscripcionView — render de la vista de transcripción", () => {
  it("muestra idioma, proveedor y los turnos con sus marcas de tiempo", async () => {
    vi.spyOn(api, "obtenerTranscripcion").mockResolvedValue(
      transcripcion([
        turno({ id: "t1", texto: "Hola", inicioMs: 0, finMs: 1000, orden: 1 }),
        turno({ id: "t2", texto: "¿Cómo estás?", inicioMs: 1000, finMs: 2500, orden: 2 }),
      ])
    );

    render(<TranscripcionView reunionId="r-1" onBack={vi.fn()} />);

    await waitFor(() => screen.getByText(/Transcripción/));

    expect(screen.getByText(/es-CO/)).toBeDefined();
    expect(screen.getByText(/local/)).toBeDefined();
    expect(screen.getByText("Hola")).toBeDefined();
    expect(screen.getByText("¿Cómo estás?")).toBeDefined();
    expect(screen.getByText(/00:00.*00:01/)).toBeDefined();
  });

  it("sin segmentos, muestra el mensaje de transcripción vacía", async () => {
    vi.spyOn(api, "obtenerTranscripcion").mockResolvedValue(transcripcion([]));

    render(<TranscripcionView reunionId="r-1" onBack={vi.fn()} />);

    await waitFor(() => screen.getByText("Sin segmentos de transcripción."));
  });

  it("el botón 'Volver a la lista' invoca onBack", async () => {
    vi.spyOn(api, "obtenerTranscripcion").mockResolvedValue(transcripcion([turno()]));
    const onBack = vi.fn();

    render(<TranscripcionView reunionId="r-1" onBack={onBack} />);
    await waitFor(() => screen.getByText(/Transcripción/));

    fireEvent.click(screen.getByRole("button", { name: /Volver a la lista/i }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("flujo no autenticado: error del API se muestra como alerta", async () => {
    vi.spyOn(api, "obtenerTranscripcion").mockRejectedValue(
      new Error("No autenticado: token no encontrado")
    );

    render(<TranscripcionView reunionId="r-1" onBack={vi.fn()} />);

    const alerta = await waitFor(() => screen.getByRole("alert"));
    expect(alerta.textContent).toMatch(/No autenticado/);
  });
});
