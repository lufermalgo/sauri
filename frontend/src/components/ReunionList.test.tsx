// @vitest-environment jsdom
/**
 * Tests de componentes del frontend: lista de reuniones con estados.
 *
 * Feature: meeting-capture-transcription
 * Task: 15.2 — Validates: Requirements 9.1, 9.2, 4.5
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { CausaFallo, EstadoProceso, OrigenReunion } from "@sauri/shared-types";
import type { Reunion } from "@sauri/shared-types";

import { ReunionList } from "./ReunionList";
import * as api from "../api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function reunion(overrides: Partial<Reunion> = {}): Reunion {
  return {
    id: "r-1",
    enlaceMeet: "https://meet.google.com/abc-defg-hij",
    origen: OrigenReunion.Enlace,
    estadoProceso: EstadoProceso.EnCola,
    causaFallo: undefined,
    creadaPor: "test-user",
    creadaEn: new Date().toISOString(),
    ...overrides,
  };
}

describe("ReunionList — render de lista con estados", () => {
  it("muestra cada Reunion con su Estado_De_Proceso", async () => {
    vi.spyOn(api, "listarReuniones").mockResolvedValue([
      reunion({ id: "r-1", estadoProceso: EstadoProceso.EnCola }),
      reunion({ id: "r-2", estadoProceso: EstadoProceso.Completado }),
      reunion({
        id: "r-3",
        estadoProceso: EstadoProceso.Fallido,
        causaFallo: CausaFallo.FalloDelMotor,
      }),
    ]);

    render(<ReunionList refreshKey={0} onSelectReunion={vi.fn()} />);

    await waitFor(() => screen.getByText("Reuniones"));

    expect(screen.getAllByText(EstadoProceso.EnCola).length).toBeGreaterThan(0);
    expect(screen.getAllByText(EstadoProceso.Completado).length).toBeGreaterThan(0);
    expect(screen.getAllByText(EstadoProceso.Fallido).length).toBeGreaterThan(0);
    expect(screen.getByText(CausaFallo.FalloDelMotor)).toBeDefined();
  });

  it("solo muestra el botón 'Ver transcripción' para reuniones completadas", async () => {
    vi.spyOn(api, "listarReuniones").mockResolvedValue([
      reunion({ id: "r-1", estadoProceso: EstadoProceso.Grabando }),
      reunion({ id: "r-2", estadoProceso: EstadoProceso.Completado }),
    ]);

    render(<ReunionList refreshKey={0} onSelectReunion={vi.fn()} />);
    await waitFor(() => screen.getByText("Reuniones"));

    const botones = screen.getAllByRole("button", { name: /Ver transcripción/i });
    expect(botones).toHaveLength(1);
  });

  it("sin reuniones, muestra el mensaje vacío", async () => {
    vi.spyOn(api, "listarReuniones").mockResolvedValue([]);

    render(<ReunionList refreshKey={0} onSelectReunion={vi.fn()} />);
    await waitFor(() => screen.getByText("No hay reuniones registradas."));
  });

  it("flujo no autenticado: error del API se muestra como alerta", async () => {
    vi.spyOn(api, "listarReuniones").mockRejectedValue(
      new Error("No autenticado: token no encontrado")
    );

    render(<ReunionList refreshKey={0} onSelectReunion={vi.fn()} />);

    const alerta = await waitFor(() => screen.getByRole("alert"));
    expect(alerta.textContent).toMatch(/No autenticado/);
  });
});
