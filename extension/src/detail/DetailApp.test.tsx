// Integration test: navigation, layout, and Detail_View orchestration
// (Req. 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 14.3)
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { DetailApp } from "./DetailApp";

function mockChrome() {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      local: {
        setAccessLevel: vi.fn(async () => {}),
        get: vi.fn(async () => ({ sauriLocalToken: "token-x" })),
        set: vi.fn(async () => {}),
      },
      // The app was found on the desktop port earlier in this browser session.
      session: {
        get: vi.fn(async () => ({ sauriBackendUrl: "http://localhost:41750" })),
        set: vi.fn(async () => {}),
        remove: vi.fn(async () => {}),
      },
    },
  };
}

function setUrl(search: string) {
  window.history.pushState({}, "", `/detail.html${search}`);
}

describe("DetailApp — navigation and Meeting identifier (Req. 6.1, 6.2, 6.5)", () => {
  beforeEach(() => {
    mockChrome();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows View_State error without emitting requests when meetingId is invalid/absent (Req. 6.5)", async () => {
    setUrl("");
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;

    render(<DetailApp />);

    expect(await screen.findByText(/this note doesn't exist/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("DetailApp — simultaneous loading and structure (Req. 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 14.3)", () => {
  beforeEach(() => {
    mockChrome();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requests Transcript and Diarization and shows title, Summary_Space, and Transcript_Panel (Req. 6.3, 7.1)", async () => {
    setUrl("?meetingId=r1");
    global.fetch = vi.fn(async (url: string) => {
      if (url.includes("/transcript")) {
        return new Response(
          JSON.stringify({
            transcript_id: "tr1",
            meeting_id: "r1",
            segments: [{ id: "t1", text: "Hola equipo", start_ms: 0, end_ms: 1000, sequence: 0 }], // spanish-sample-data
          }),
          { status: 200 }
        );
      }
      if (url.includes("/diarization")) {
        return new Response(
          JSON.stringify({
            diarization_id: "d1",
            meeting_id: "r1",
            diarization_state: "completed",
            speaker_count: 1,
            speakers: [{ id: "h1", label: "Ana", sequence: 1 }], // spanish-sample-data
            assignments: [{ turn_id: "t1", speaker_id: "h1" }],
          }),
          { status: 200 }
        );
      }
      return new Response("", { status: 404 });
    }) as unknown as typeof fetch;

    render(<DetailApp />);

    expect(screen.getByText("Summary available soon.")).toBeInTheDocument();
    expect(screen.getByText("Untitled note")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Hola equipo")).toBeInTheDocument()); // spanish-sample-data
    expect(screen.getAllByText("Ana").length).toBeGreaterThan(0); // spanish-sample-data
  });

  it("keeps independent View_States: a diarization failure doesn't block showing the transcript", async () => {
    setUrl("?meetingId=r2");
    global.fetch = vi.fn(async (url: string) => {
      if (url.includes("/transcript")) {
        return new Response(
          JSON.stringify({
            transcript_id: "tr2",
            meeting_id: "r2",
            segments: [{ id: "t1", text: "Contenido disponible", start_ms: 0, end_ms: 1000, sequence: 0 }], // spanish-sample-data
          }),
          { status: 200 }
        );
      }
      if (url.includes("/diarization")) {
        return new Response("", { status: 500 });
      }
      return new Response("", { status: 404 });
    }) as unknown as typeof fetch;

    render(<DetailApp />);

    await waitFor(() => expect(screen.getByText("Contenido disponible")).toBeInTheDocument()); // spanish-sample-data
    expect(screen.getByText(/couldn't load speaking time/i)).toBeInTheDocument();
    expect(screen.getByText("Unidentified speaker")).toBeInTheDocument();
  });

  it("shows View_State empty in the Transcript_Panel when the Meeting has no Transcript (Req. 7.6, 8.8)", async () => {
    setUrl("?meetingId=r3");
    global.fetch = vi.fn(async () => new Response("", { status: 404 })) as unknown as typeof fetch;

    render(<DetailApp />);

    await waitFor(() =>
      expect(screen.getByText(/the transcript is not available for this note/i)).toBeInTheDocument()
    );
  });

  it("retries silently while the Meeting is still processing, and shows the transcript as soon as it's available", async () => {
    setUrl("?meetingId=r4");
    let transcriptAvailable = false;
    let processState = "transcribing";

    global.fetch = vi.fn(async (url: string) => {
      if (url.includes("/transcript")) {
        if (!transcriptAvailable) return new Response("", { status: 404 });
        return new Response(
          JSON.stringify({
            transcript_id: "tr4",
            meeting_id: "r4",
            segments: [{ id: "t1", text: "Texto que llega tarde", start_ms: 0, end_ms: 1000, sequence: 0 }], // spanish-sample-data
          }),
          { status: 200 }
        );
      }
      if (url.includes("/diarization")) return new Response("", { status: 404 });
      // GET /api/v1/meetings/{id} — processing state
      return new Response(JSON.stringify({ meeting_id: "r4", process_state: processState }), { status: 200 });
    }) as unknown as typeof fetch;

    render(<DetailApp />);

    // First attempt: still "transcribing", transcript not yet available.
    await waitFor(() =>
      expect(screen.getByText(/the transcript is not available for this note/i)).toBeInTheDocument()
    );

    // The meeting finishes processing between retries (real polling, every 3s).
    transcriptAvailable = true;
    processState = "completed";

    await waitFor(() => expect(screen.getByText("Texto que llega tarde")).toBeInTheDocument(), { // spanish-sample-data
      timeout: 6000,
    });
  }, 10000);
});
