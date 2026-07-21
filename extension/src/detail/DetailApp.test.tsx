// Prueba de integración: navegación, layout y orquestación de la Vista_De_Detalle
// (Req. 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 14.3)
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { DetailApp } from "./DetailApp";

function mockChrome() {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      sync: {
        get: vi.fn(async () => ({ authToken: "token-x" })),
        set: vi.fn(async () => {}),
        remove: vi.fn(async () => {}),
      },
    },
  };
}

function setUrl(search: string) {
  window.history.pushState({}, "", `/detail.html${search}`);
}

describe("DetailApp — navegación e identificador de Reunion (Req. 6.1, 6.2, 6.5)", () => {
  beforeEach(() => {
    mockChrome();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("presenta Estado_De_Vista error sin emitir solicitudes cuando el reunionId es inválido/ausente (Req. 6.5)", async () => {
    setUrl("");
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;

    render(<DetailApp />);

    expect(await screen.findByText(/esta nota no existe/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("DetailApp — carga y estructura simultánea (Req. 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 14.3)", () => {
  beforeEach(() => {
    mockChrome();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("solicita Transcripcion y Diarizacion y presenta título, Espacio_De_Resumen y Panel_De_Transcripcion (Req. 6.3, 7.1)", async () => {
    setUrl("?reunionId=r1");
    global.fetch = vi.fn(async (url: string) => {
      if (url.includes("/transcripcion")) {
        return new Response(
          JSON.stringify({
            transcripcion_id: "tr1",
            reunion_id: "r1",
            segmentos: [{ id: "t1", texto: "Hola equipo", inicio_ms: 0, fin_ms: 1000, orden: 0 }],
          }),
          { status: 200 }
        );
      }
      if (url.includes("/diarizacion")) {
        return new Response(
          JSON.stringify({
            diarizacion_id: "d1",
            reunion_id: "r1",
            estado_diarizacion: "completado",
            num_hablantes: 1,
            hablantes: [{ id: "h1", etiqueta: "Ana", orden: 1 }],
            asignaciones: [{ turno_id: "t1", hablante_id: "h1" }],
          }),
          { status: 200 }
        );
      }
      return new Response("", { status: 404 });
    }) as unknown as typeof fetch;

    render(<DetailApp />);

    expect(screen.getByText("Resumen disponible próximamente.")).toBeInTheDocument();
    expect(screen.getByText("Nota sin título")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Hola equipo")).toBeInTheDocument());
    expect(screen.getAllByText("Ana").length).toBeGreaterThan(0);
  });

  it("mantiene Estados_De_Vista independientes: el fallo de diarización no impide presentar la transcripción", async () => {
    setUrl("?reunionId=r2");
    global.fetch = vi.fn(async (url: string) => {
      if (url.includes("/transcripcion")) {
        return new Response(
          JSON.stringify({
            transcripcion_id: "tr2",
            reunion_id: "r2",
            segmentos: [{ id: "t1", texto: "Contenido disponible", inicio_ms: 0, fin_ms: 1000, orden: 0 }],
          }),
          { status: 200 }
        );
      }
      if (url.includes("/diarizacion")) {
        return new Response("", { status: 500 });
      }
      return new Response("", { status: 404 });
    }) as unknown as typeof fetch;

    render(<DetailApp />);

    await waitFor(() => expect(screen.getByText("Contenido disponible")).toBeInTheDocument());
    expect(screen.getByText(/no se pudo cargar el tiempo de habla/i)).toBeInTheDocument();
    expect(screen.getByText("Hablante no identificado")).toBeInTheDocument();
  });

  it("presenta Estado_De_Vista vacio en el Panel_De_Transcripcion cuando la Reunion no tiene Transcripcion (Req. 7.6, 8.8)", async () => {
    setUrl("?reunionId=r3");
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;

    render(<DetailApp />);

    await waitFor(() =>
      expect(screen.getByText(/la transcripción no está disponible para esta nota/i)).toBeInTheDocument()
    );
  });

  it("reintenta en silencio mientras la Reunion sigue procesándose, y muestra la transcripción apenas queda disponible", async () => {
    setUrl("?reunionId=r4");
    let transcripcionDisponible = false;
    let estadoProceso = "transcribiendo";

    global.fetch = vi.fn(async (url: string) => {
      if (url.includes("/transcripcion")) {
        if (!transcripcionDisponible) return new Response("", { status: 404 });
        return new Response(
          JSON.stringify({
            transcripcion_id: "tr4",
            reunion_id: "r4",
            segmentos: [{ id: "t1", texto: "Texto que llega tarde", inicio_ms: 0, fin_ms: 1000, orden: 0 }],
          }),
          { status: 200 }
        );
      }
      if (url.includes("/diarizacion")) return new Response("", { status: 404 });
      // GET /api/v1/reuniones/{id} — estado de procesamiento
      return new Response(JSON.stringify({ reunion_id: "r4", estado_proceso: estadoProceso }), { status: 200 });
    }) as unknown as typeof fetch;

    render(<DetailApp />);

    // Primer intento: aún "transcribiendo", sin transcripción disponible todavía.
    await waitFor(() =>
      expect(screen.getByText(/la transcripción no está disponible para esta nota/i)).toBeInTheDocument()
    );

    // La reunión termina de procesarse entre reintentos (polling real, cada 3s).
    transcripcionDisponible = true;
    estadoProceso = "completado";

    await waitFor(() => expect(screen.getByText("Texto que llega tarde")).toBeInTheDocument(), {
      timeout: 6000,
    });
  }, 10000);
});
