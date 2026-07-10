// Prueba por ejemplo: composición del Side_Panel y layout responsivo (Req. 1.3, 1.4, 1.5, 1.6)
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SidePanelApp } from "./SidePanelApp";

function mockChrome(sesionVigente: boolean) {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      session: {
        get: vi.fn(async () => ({ sauriState: { status: "idle" } })),
      },
      sync: {
        get: vi.fn(async () => (sesionVigente ? { authToken: "token-x" } : {})),
        set: vi.fn(async () => {}),
        remove: vi.fn(async () => {}),
      },
      onChanged: { addListener: vi.fn(), removeListener: vi.fn() },
    },
    runtime: { sendMessage: vi.fn() },
  };
  global.fetch = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
}

describe("SidePanelApp", () => {
  beforeEach(() => {
    vi.stubGlobal("navigator", {
      mediaDevices: { enumerateDevices: vi.fn(async () => []) },
    });
  });

  it("bloquea la Lista_De_Notas sin Sesion_De_Usuario vigente (Req. 13.2)", async () => {
    mockChrome(false);
    render(<SidePanelApp />);
    await waitFor(() => expect(screen.getByRole("button", { name: /iniciar sesión/i })).toBeInTheDocument());
    expect(screen.queryByText("Mis Notas")).not.toBeInTheDocument();
  });

  it("renderiza Encabezado + Controles + Lista con sesión vigente (Req. 1.4)", async () => {
    mockChrome(true);
    render(<SidePanelApp />);
    await waitFor(() => expect(screen.getByText("REC Notas")).toBeInTheDocument());
    expect(screen.getByText("Mis Notas")).toBeInTheDocument();
    expect(screen.getByText("Pantalla + audio")).toBeInTheDocument();
  });
});
