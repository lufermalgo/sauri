// Example-based test: Side_Panel composition and responsive layout (Req. 1.3, 1.4, 1.5, 1.6)
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SidePanelApp } from "./SidePanelApp";

function mockChrome(sessionActive: boolean) {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      session: {
        get: vi.fn(async () => ({ sauriState: { status: "idle" } })),
      },
      sync: {
        get: vi.fn(async () => (sessionActive ? { authToken: "token-x" } : {})),
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
      mediaDevices: {
        getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
        enumerateDevices: vi.fn(async () => []),
      },
    });
  });

  it("blocks the Notes_List without an active User_Session (Req. 13.2)", async () => {
    mockChrome(false);
    render(<SidePanelApp />);
    await waitFor(() => expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument());
    expect(screen.queryByText("Mis Notas")).not.toBeInTheDocument();
  });

  it("renders Header + Controls + List with an active session (Req. 1.4)", async () => {
    mockChrome(true);
    render(<SidePanelApp />);
    await waitFor(() => expect(screen.getByText("REC Notas")).toBeInTheDocument());
    expect(screen.getByText("Mis Notas")).toBeInTheDocument();
    expect(screen.getByText("Screen + audio")).toBeInTheDocument();
  });
});
