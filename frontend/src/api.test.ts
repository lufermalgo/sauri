// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";

const manifestMethod = api as typeof api & {
  getPlaybackManifest?: (meetingId: string) => Promise<PlaybackManifest>;
};

const diarizationMethod = api as typeof api & {
  getDiarization?: (meetingId: string) => Promise<{
    speakers: Array<{ id: string; label: string; sequence: number }>;
    assignments: Array<{ turn_id: string; speaker_id: string }>;
  }>;
};

interface PlaybackSource {
  source_id: string;
  url: string;
  mime_type: string | null;
  quality_label?: string;
  width?: number | null;
  height?: number | null;
  video_offset_ms?: number;
}

interface PlaybackManifest {
  meeting_id: string;
  duration_seconds: number;
  video_presence: "muxed" | "separate" | "absent" | "unknown";
  audio_source: PlaybackSource;
  muxed_video_source: PlaybackSource | null;
  video_sources: PlaybackSource[];
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

function mockFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(response(body, status));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("localStorage", {
    getItem: vi.fn().mockReturnValue("synthetic-token"),
    setItem: vi.fn(),
    clear: vi.fn(),
  });
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const uploadMethod = api as typeof api & {
  uploadRecording?: (audio: File, data: Record<string, unknown>) => Promise<unknown>;
};

describe("authenticated multipart upload API adapter", () => {
  it("sends the audio file and serialized metadata with bearer auth and a browser multipart boundary", async () => {
    expect(typeof uploadMethod.uploadRecording).toBe("function");
    const fetchMock = mockFetch({ recording_id: "recording-1", state: "transcribing" });
    const audio = new File(["synthetic audio"], "sample.webm", { type: "audio/webm" });
    const data = {
      duration_seconds: 13,
      meeting_id: "meeting-1",
      idempotency_key: "retry-key-1",
      capture_origin: "web_upload",
      video_presence: "absent",
    };

    await uploadMethod.uploadRecording!(audio, data);

    const [requestUrl, request] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/ingestion/upload");
    expect(request.method).toBe("POST");
    expect(request.headers).toEqual({ Authorization: "Bearer synthetic-token" });
    expect(request.headers).not.toHaveProperty("Content-Type");
    expect(request.body).toBeInstanceOf(FormData);
    const formData = request.body as FormData;
    expect(formData.get("audio")).toBe(audio);
    expect(formData.get("data")).toBe(JSON.stringify(data));
    expect(data).toMatchObject({ capture_origin: "web_upload", video_presence: "absent" });
    expect(data).not.toHaveProperty("meet_link");
    expect(data).not.toHaveProperty("title");
  });

  it("preserves meeting and idempotency identifiers for a retry", async () => {
    expect(typeof uploadMethod.uploadRecording).toBe("function");
    const fetchMock = mockFetch({ recording_id: "recording-1", state: "transcribing" });
    const audio = new File(["synthetic audio"], "sample.webm", { type: "audio/webm" });
    const data = { duration_seconds: 13, meeting_id: "meeting-1", idempotency_key: "retry-key-1" };

    await uploadMethod.uploadRecording!(audio, data);
    await uploadMethod.uploadRecording!(audio, data);

    const bodies = fetchMock.mock.calls.map(([, request]) => request.body as FormData);
    expect(bodies).toHaveLength(2);
    expect(bodies.map((body) => JSON.parse(String(body.get("data"))))).toEqual([data, data]);
  });
});

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

const loginMethod = api as typeof api & {
  login?: (email: string, password: string) => Promise<LoginResponse>;
};

describe("login API adapter", () => {
  it("posts JSON credentials and decodes the login response without persisting it", async () => {
    const loginResponse: LoginResponse = {
      access_token: "synthetic-access-token",
      token_type: "bearer",
      expires_in: 3600,
    };
    const fetchMock = mockFetch(loginResponse);
    const storageSetItem = vi.mocked(localStorage.setItem);

    expect(typeof loginMethod.login).toBe("function");
    await expect(loginMethod.login!("synthetic@example.invalid", "synthetic-password"))
      .resolves.toEqual(loginResponse);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [requestUrl, request] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestUrl).toContain("/api/v1/auth/login");
    expect(request.method).toBe("POST");
    expect(request.headers).toEqual({ "Content-Type": "application/json" });
    expect(request.body).toBe(JSON.stringify({
      email: "synthetic@example.invalid",
      password: "synthetic-password",
    }));
    expect(storageSetItem).not.toHaveBeenCalled();
  });

  it("rejects non-success responses without persisting credentials or response data", async () => {
    const loginResponse = {
      access_token: "synthetic-access-token",
      token_type: "bearer",
      expires_in: 3600,
    };
    mockFetch(loginResponse, 401);
    const storageSetItem = vi.mocked(localStorage.setItem);

    expect(typeof loginMethod.login).toBe("function");
    await expect(loginMethod.login!("synthetic@example.invalid", "synthetic-password"))
      .rejects.toThrow("Error 401");

    expect(storageSetItem).not.toHaveBeenCalled();
    expect(storageSetItem).not.toHaveBeenCalledWith("sauri_token", expect.anything());
    expect(storageSetItem).not.toHaveBeenCalledWith(expect.anything(), "synthetic-password");
  });

  it("rejects network failures without persisting credentials", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Network unavailable"));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(),
      setItem: vi.fn(),
      clear: vi.fn(),
    });
    const storageSetItem = vi.mocked(localStorage.setItem);

    expect(typeof loginMethod.login).toBe("function");
    await expect(loginMethod.login!("synthetic@example.invalid", "synthetic-password"))
      .rejects.toThrow("Network unavailable");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(storageSetItem).not.toHaveBeenCalled();
  });
});

describe("speaker diarization API adapter", () => {
  it("returns persisted turn-to-speaker assignments for the authenticated meeting", async () => {
    expect(typeof diarizationMethod.getDiarization).toBe("function");
    const fixture = {
      speakers: [{ id: "speaker-synthetic", label: "Speaker 1", sequence: 1 }],
      assignments: [{ turn_id: "turn-synthetic", speaker_id: "speaker-synthetic" }],
    };
    const fetchMock = mockFetch(fixture);

    await expect(diarizationMethod.getDiarization!("meeting / synthetic")).resolves.toEqual(fixture);

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/meetings/meeting%20%2F%20synthetic/diarization"),
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer synthetic-token" }) }),
    );
  });
});

describe("meeting playback API adapter", () => {
  it("returns the typed manifest modes and authoritative source metadata without inference", async () => {
    expect(typeof manifestMethod.getPlaybackManifest).toBe("function");

    const signedAudio: PlaybackSource = {
      source_id: "audio-source",
      url: "https://storage.invalid/signed/audio?token=synthetic",
      mime_type: "audio/webm",
    };
    const signedVideo: PlaybackSource = {
      source_id: "video-source",
      url: "https://storage.invalid/signed/video?token=synthetic",
      mime_type: "video/webm",
      quality_label: "Original",
      width: 1280,
      height: 720,
      video_offset_ms: -250,
    };
    const fixtures: PlaybackManifest[] = [
      { meeting_id: "meeting-1", duration_seconds: 12, video_presence: "muxed", audio_source: signedAudio, muxed_video_source: signedAudio, video_sources: [] },
      { meeting_id: "meeting-1", duration_seconds: 12, video_presence: "separate", audio_source: signedAudio, muxed_video_source: null, video_sources: [signedVideo] },
      { meeting_id: "meeting-1", duration_seconds: 12, video_presence: "absent", audio_source: signedAudio, muxed_video_source: null, video_sources: [] },
      { meeting_id: "meeting-1", duration_seconds: 12, video_presence: "unknown", audio_source: { ...signedAudio, mime_type: null }, muxed_video_source: null, video_sources: [] },
    ];

    for (const fixture of fixtures) {
      const fetchMock = mockFetch(fixture);
      const result = await manifestMethod.getPlaybackManifest!("meeting-1");

      expect(result).toEqual(fixture);
      expect(result.video_presence).toBe(fixture.video_presence);
      expect(result.muxed_video_source).toEqual(fixture.muxed_video_source);
      expect(result.video_sources).toEqual(fixture.video_sources);
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/meetings/meeting-1/playback"),
        expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer synthetic-token" }) }),
      );
    }
  });

  it("maps ordered transcript segments to timed passages and retains untimed text without a playback interval", async () => {
    const fetchMock = mockFetch({
      transcript_id: "transcript-1",
      meeting_id: "meeting-1",
      language: "es-CO",
      provider: "local",
      supports_turns: true,
      created_at: "2026-10-19T12:00:00Z",
      segments: [
        { id: "segment-2", text: "Segunda frase", start_ms: 1200, end_ms: 2200, sequence: 2 }, // spanish-sample-data
        { id: "segment-1", text: "Primera frase", start_ms: 0, end_ms: 1100, sequence: 1 }, // spanish-sample-data
        { id: "segment-untimed", text: "Texto sin tiempo", start_ms: null, end_ms: null, sequence: 3 }, // spanish-sample-data
        { id: "segment-invalid", text: "Intervalo inválido", start_ms: 2400, end_ms: 2300, sequence: 4 }, // spanish-sample-data
      ],
    });

    const transcript = await api.getTranscript("meeting-1");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/meetings/meeting-1/transcript"),
      expect.any(Object),
    );
    expect(transcript.segments).toEqual([
      { id: "segment-2", text: "Segunda frase", startMs: 1200, endMs: 2200, sequence: 2 }, // spanish-sample-data
      { id: "segment-1", text: "Primera frase", startMs: 0, endMs: 1100, sequence: 1 }, // spanish-sample-data
      { id: "segment-untimed", text: "Texto sin tiempo", startMs: null, endMs: null, sequence: 3 }, // spanish-sample-data
      { id: "segment-invalid", text: "Intervalo inválido", startMs: null, endMs: null, sequence: 4 }, // spanish-sample-data
    ]);
    expect(transcript.segments[2].text).toBe("Texto sin tiempo"); // spanish-sample-data
    expect(transcript.segments[2].startMs).toBeNull();
    expect(transcript.segments[3].text).toBe("Intervalo inválido"); // spanish-sample-data
    expect(transcript.segments[3].endMs).toBeNull();
    expect(transcript.turns).toEqual([
      {
        id: "segment-2",
        transcriptId: "transcript-1",
        text: "Segunda frase",
        startMs: 1200,
        endMs: 2200,
        sequence: 2,
      },
      {
        id: "segment-1",
        transcriptId: "transcript-1",
        text: "Primera frase",
        startMs: 0,
        endMs: 1100,
        sequence: 1,
      },
    ]);
  });

  it("does not surface raw object-store references from failed API responses", async () => {
    const privateReference = "private-recordings/customer-42/raw-audio.webm";
    mockFetch({ detail: `Playback failed for ${privateReference}` }, 500);

    await expect(api.getTranscript("meeting-1")).rejects.toThrow();
    await expect(api.getTranscript("meeting-1")).rejects.not.toThrow(privateReference);
  });
});
