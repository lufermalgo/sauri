// Pruebas de integración del Cliente_De_API (RED antes de la implementación)
// Requisitos: 13.1, 13.3, 13.4, 13.5, 14.1, 14.4, 14.5, 4.9, 6.6

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

function mockChromeStorage(initial: Record<string, unknown> = {}) {
  const store: Record<string, unknown> = { ...initial };
  const listeners: Array<(changes: unknown, area: string) => void> = [];
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      sync: {
        get: vi.fn(async (key: string) => ({ [key]: store[key] })),
        set: vi.fn(async (obj: Record<string, unknown>) => {
          Object.assign(store, obj);
        }),
        remove: vi.fn(async (key: string) => {
          delete store[key];
        }),
      },
      onChanged: { addListener: (fn: (c: unknown, a: string) => void) => listeners.push(fn) },
    },
  };
  return store;
}

describe("Cliente_De_API — header de autorización y almacenamiento (Req. 13.1, 13.3, 14.1)", () => {
  beforeEach(() => {
    mockChromeStorage({ authToken: "token-abc" });
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify([]), { status: 200 })
    ) as unknown as typeof fetch;
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("adjunta Authorization: Bearer {sesion} leída de chrome.storage en cada solicitud", async () => {
    const { listarReuniones } = await import("./client");
    await listarReuniones("http://localhost:8000");
    expect(fetch).toHaveBeenCalled();
    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = callArgs[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer token-abc");
  });
});

describe("Cliente_De_API — manejo de 401 (Req. 13.4)", () => {
  it("descarta la sesión almacenada cuando el backend responde 401", async () => {
    const store = mockChromeStorage({ authToken: "token-expirado" });
    global.fetch = vi.fn(async () => new Response("", { status: 401 })) as unknown as typeof fetch;

    const { listarReuniones } = await import("./client");
    await expect(listarReuniones("http://localhost:8000")).rejects.toThrow();
    expect(store.authToken).toBeUndefined();
  });
});

describe("Cliente_De_API — timeout y reintento (Req. 14.4, 14.5, 4.9, 6.6)", () => {
  beforeEach(() => {
    mockChromeStorage({ authToken: "token-abc" });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("aborta la solicitud tras 10s vía AbortController", async () => {
    vi.useFakeTimers();
    global.fetch = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        })
    ) as unknown as typeof fetch;

    const { listarReuniones } = await import("./client");
    const promise = listarReuniones("http://localhost:8000");
    const expectacion = expect(promise).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(10_000);
    await expectacion;
    vi.useRealTimers();
  });

  it("el reintento vuelve a emitir la solicitud", async () => {
    let llamadas = 0;
    global.fetch = vi.fn(async () => {
      llamadas += 1;
      return new Response(JSON.stringify([]), { status: 200 });
    }) as unknown as typeof fetch;

    const { listarReuniones } = await import("./client");
    await listarReuniones("http://localhost:8000");
    await listarReuniones("http://localhost:8000");
    expect(llamadas).toBe(2);
  });
});

describe("Cliente_De_API — 404 distinguido de un fallo real (Req. 7.6, 8.8, 10.5)", () => {
  beforeEach(() => {
    mockChromeStorage({ authToken: "token-abc" });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("lanza ErrorNoEncontrado cuando el backend responde 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { obtenerTranscripcion, ErrorNoEncontrado } = await import("./client");
    await expect(obtenerTranscripcion("r1", "http://localhost:8000")).rejects.toBeInstanceOf(ErrorNoEncontrado);
  });
});

describe("Cliente_De_API — renombrarReunion / eliminarReunion (Mis_Notas → administrar)", () => {
  beforeEach(() => {
    mockChromeStorage({ authToken: "token-abc" });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("renombrarReunion hace PATCH con el nuevo título en el body", async () => {
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ reunion_id: "r1", titulo: "Nuevo título" }), { status: 200 })
    ) as unknown as typeof fetch;

    const { renombrarReunion } = await import("./client");
    await renombrarReunion("r1", "Nuevo título", "http://localhost:8000");

    expect(fetch).toHaveBeenCalled();
    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(callArgs[0]).toBe("http://localhost:8000/api/v1/reuniones/r1");
    const init = callArgs[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ titulo: "Nuevo título" });
  });

  it("renombrarReunion lanza ErrorNoEncontrado en 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { renombrarReunion, ErrorNoEncontrado } = await import("./client");
    await expect(renombrarReunion("r1", "X", "http://localhost:8000")).rejects.toBeInstanceOf(
      ErrorNoEncontrado
    );
  });

  it("eliminarReunion hace DELETE y no falla al parsear el 204 sin cuerpo", async () => {
    global.fetch = vi.fn(async () => new Response(null, { status: 204 })) as unknown as typeof fetch;
    const { eliminarReunion } = await import("./client");
    await expect(eliminarReunion("r1", "http://localhost:8000")).resolves.toBeUndefined();

    const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(callArgs[0]).toBe("http://localhost:8000/api/v1/reuniones/r1");
    const init = callArgs[1] as RequestInit;
    expect(init.method).toBe("DELETE");
  });

  it("eliminarReunion lanza ErrorNoEncontrado en 404", async () => {
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;
    const { eliminarReunion, ErrorNoEncontrado } = await import("./client");
    await expect(eliminarReunion("r1", "http://localhost:8000")).rejects.toBeInstanceOf(
      ErrorNoEncontrado
    );
  });
});

describe("Cliente_De_API — transporte cifrado (Req. 13.5)", () => {
  beforeEach(() => {
    mockChromeStorage({ authToken: "token-abc" });
  });

  it("rechaza un backendUrl http:// que no sea localhost", async () => {
    const { listarReuniones } = await import("./client");
    await expect(listarReuniones("http://api.sauri.example.com")).rejects.toThrow();
  });

  it("admite http://localhost", async () => {
    global.fetch = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
    const { listarReuniones } = await import("./client");
    await expect(listarReuniones("http://localhost:8000")).resolves.toEqual([]);
  });

  it("admite https:// en producción", async () => {
    global.fetch = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
    const { listarReuniones } = await import("./client");
    await expect(listarReuniones("https://api.sauri.example.com")).resolves.toEqual([]);
  });
});
