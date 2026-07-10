// @vitest-environment jsdom
/**
 * Tests del panel lateral (App.tsx): selector de resolución y cuenta regresiva.
 *
 * Feature: meeting-capture-transcription
 * Task: 14.8 — Validates: Requirements 2.1
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";

import { App } from "./App";

function stubChromeApi() {
  vi.stubGlobal("chrome", {
    storage: {
      session: {
        get: vi.fn(async () => ({
          sauriState: { status: "pending", meetingTitle: "Reunión de prueba" },
        })),
      },
      onChanged: {
        addListener: vi.fn(),
        removeListener: vi.fn(),
      },
    },
    runtime: {
      sendMessage: vi.fn(),
    },
  });
  vi.stubGlobal("navigator", {
    mediaDevices: {
      enumerateDevices: vi.fn(async () => []),
    },
  });
}

async function renderAndWaitForPendingState() {
  render(<App />);
  // Flush the microtasks from chrome.storage.session.get(...).then(...)
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("Panel — selector de resolución y cuenta regresiva", () => {
  beforeEach(() => {
    stubChromeApi();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("muestra las opciones de resolución con 720p seleccionada por defecto", async () => {
    await renderAndWaitForPendingState();
    expect(screen.getByText(/Reunión detectada/)).toBeDefined();

    const [resolutionSelect] = screen.getAllByRole("combobox") as HTMLSelectElement[];
    expect(resolutionSelect.value).toBe("720p");
    expect(screen.getByRole("option", { name: "480p" })).toBeDefined();
    expect(screen.getByRole("option", { name: "1080p" })).toBeDefined();
  });

  it("al cambiar la resolución, el valor seleccionado se actualiza", async () => {
    await renderAndWaitForPendingState();

    const [resolutionSelect] = screen.getAllByRole("combobox") as HTMLSelectElement[];
    fireEvent.change(resolutionSelect, { target: { value: "1080p" } });

    expect(resolutionSelect.value).toBe("1080p");
  });

  it("con cuenta regresiva configurada, muestra el conteo antes de iniciar la captura", async () => {
    await renderAndWaitForPendingState();

    const [, countdownSelect] = screen.getAllByRole("combobox") as HTMLSelectElement[];
    fireEvent.change(countdownSelect, { target: { value: "3 segundos" } });

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: /Grabar/i }));

    // El contador debe mostrarse inmediatamente
    expect(screen.getByText("3")).toBeDefined();

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("2")).toBeDefined();

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    // Tras completarse la cuenta regresiva, se envía el mensaje de inicio de captura
    expect((globalThis as any).chrome.runtime.sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: "start-capture" })
    );
  });

  it("sin cuenta regresiva ('Sin cuenta regresiva'), inicia la captura de inmediato", async () => {
    await renderAndWaitForPendingState();

    const [, countdownSelect] = screen.getAllByRole("combobox") as HTMLSelectElement[];
    fireEvent.change(countdownSelect, { target: { value: "Sin cuenta regresiva" } });

    fireEvent.click(screen.getByRole("button", { name: /Grabar/i }));

    expect((globalThis as any).chrome.runtime.sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: "start-capture" })
    );
  });
});
