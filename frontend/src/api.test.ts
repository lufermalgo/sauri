// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { copy } from "./copy/es";

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
    removeItem: vi.fn(),
    clear: vi.fn(),
  });
  return fetchMock;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const uploadMethod = api as typeof api & {
  uploadRecording?: (audio: File, data: Record<string, unknown>) => Promise<unknown>;
};

describe("byte-based recording upload", () => {
  const file = new File(["synthetic audio"], "sample.webm", { type: "audio/webm" });
  const data: api.RecordingUploadData = {
    duration_seconds: 13,
    meeting_id: "meeting-1",
    idempotency_key: "retry-key-1",
    capture_origin: "web_upload",
    video_presence: "absent",
    title: "sample.webm",
  };

  function mockXHR() {
    mockFetch({});
    const xhr = new XMLHttpRequest();
    vi.spyOn(xhr, "open").mockImplementation(() => {});
    vi.spyOn(xhr, "setRequestHeader").mockImplementation(() => {});
    vi.spyOn(xhr, "send").mockImplementation(() => {});
    const constructor = vi.fn(() => xhr);
    vi.stubGlobal("XMLHttpRequest", constructor);
    return { xhr, constructor };
  }

  function reply(xhr: XMLHttpRequest, body: string, status = 200) {
    Object.defineProperty(xhr, "status", { value: status });
    Object.defineProperty(xhr, "responseText", { value: body });
    xhr.dispatchEvent(new Event("load"));
  }

  it("posts authenticated multipart and reports only actual XHR upload progress before confirmation", async () => {
    const { xhr } = mockXHR();
    const progress = vi.fn();
    const resolved = vi.fn();
    const request = api.uploadWithProgress(file, data, progress).then(resolved);

    expect(xhr.open).toHaveBeenCalledWith("POST", expect.stringContaining("/api/v1/ingestion/upload"));
    expect(xhr.setRequestHeader).toHaveBeenCalledTimes(1);
    expect(xhr.setRequestHeader).toHaveBeenCalledWith("Authorization", "Bearer synthetic-token");
    const body = vi.mocked(xhr.send).mock.calls[0][0] as FormData;
    expect(body.get("audio")).toBe(file);
    expect(body.get("data")).toBe(JSON.stringify(data));
    expect(progress).not.toHaveBeenCalled();

    xhr.upload.dispatchEvent(new ProgressEvent("progress", { loaded: 128, total: 512, lengthComputable: true }));
    expect(progress).toHaveBeenLastCalledWith({ loaded: 128, total: 512 });
    xhr.upload.dispatchEvent(new ProgressEvent("progress", { loaded: 512, total: 512, lengthComputable: true }));
    await Promise.resolve();
    expect(resolved).not.toHaveBeenCalled();

    reply(xhr, JSON.stringify({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" }));
    await request;
    expect(resolved).toHaveBeenCalledWith({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" });
  });

  it("does not invent a total when upload length is unknown", async () => {
    const { xhr } = mockXHR();
    const progress = vi.fn();
    const request = api.uploadWithProgress(file, data, progress);
    xhr.upload.dispatchEvent(new ProgressEvent("progress", { loaded: 128 }));
    expect(progress).toHaveBeenCalledWith({ loaded: 128, total: null });
    reply(xhr, JSON.stringify({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" }));
    await request;
  });

  it.each([
    { event: "error", message: copy.upload.errors.network },
    { event: "timeout", message: copy.upload.errors.timeout },
    { event: "abort", message: copy.upload.errors.aborted },
  ])("rejects $event without exposing server data", async ({ event, message }) => {
    const { xhr } = mockXHR();
    const request = api.uploadWithProgress(file, data, vi.fn());
    xhr.dispatchEvent(new Event(event));
    await expect(request).rejects.toThrow(message);
  });

  it.each([413, 422, 500])("rejects HTTP %s with a clear retryable error", async (status) => {
    const { xhr } = mockXHR();
    const request = api.uploadWithProgress(file, data, vi.fn());
    reply(xhr, "private server diagnostic", status);
    await expect(request).rejects.toThrow(copy.upload.errors.http(status));
  });

  it("invalidates unauthorized sessions like the fetch adapter", async () => {
    const { xhr } = mockXHR();
    const unauthorized = vi.fn();
    window.addEventListener("sauri:unauthorized", unauthorized, { once: true });
    const request = api.uploadWithProgress(file, data, vi.fn());
    reply(xhr, "{}", 401);
    await expect(request).rejects.toThrow(copy.upload.errors.http(401));
    expect(localStorage.removeItem).toHaveBeenCalledWith("sauri_token");
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it.each([
    "not JSON", "null", "{}",
    '{"recording_id":"recording-1","state":"transcribing"}',
    '{"meeting_id":42,"recording_id":"recording-1","state":"transcribing"}',
    '{"meeting_id":"","recording_id":"recording-1","state":"transcribing"}',
    '{"meeting_id":"meeting-1","recording_id":"","state":"transcribing"}',
    '{"meeting_id":"meeting-1","recording_id":"recording-1","state":42}',
])("rejects invalid confirmation %s", async (body) => {
    const { xhr } = mockXHR();
    const request = api.uploadWithProgress(file, data, vi.fn());
    reply(xhr, body);
    await expect(request).rejects.toThrow(copy.upload.errors.invalidResponse);
  });

  it("does not start a request without authentication", async () => {
    const { constructor } = mockXHR();
    vi.mocked(localStorage.getItem).mockReturnValue(null);
    await expect(api.uploadWithProgress(file, data, vi.fn())).rejects.toThrow(copy.upload.errors.unauthenticated);
    expect(constructor).not.toHaveBeenCalled();
  });
});

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
        { id: "segment-2", text: "Second phrase", start_ms: 1200, end_ms: 2200, sequence: 2 },
        { id: "segment-1", text: "First phrase", start_ms: 0, end_ms: 1100, sequence: 1 },
        { id: "segment-untimed", text: "Untimed text", start_ms: null, end_ms: null, sequence: 3 },
        { id: "segment-invalid", text: "Invalid interval", start_ms: 2400, end_ms: 2300, sequence: 4 },
      ],
    });

    const transcript = await api.getTranscript("meeting-1");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/meetings/meeting-1/transcript"),
      expect.any(Object),
    );
    expect(transcript.segments).toEqual([
      { id: "segment-2", text: "Second phrase", startMs: 1200, endMs: 2200, sequence: 2 },
      { id: "segment-1", text: "First phrase", startMs: 0, endMs: 1100, sequence: 1 },
      { id: "segment-untimed", text: "Untimed text", startMs: null, endMs: null, sequence: 3 },
      { id: "segment-invalid", text: "Invalid interval", startMs: null, endMs: null, sequence: 4 },
    ]);
    expect(transcript.segments[2].text).toBe("Untimed text");
    expect(transcript.segments[2].startMs).toBeNull();
    expect(transcript.segments[3].text).toBe("Invalid interval");
    expect(transcript.segments[3].endMs).toBeNull();
    expect(transcript.turns).toEqual([
      {
        id: "segment-2",
        transcriptId: "transcript-1",
        text: "Second phrase",
        startMs: 1200,
        endMs: 2200,
        sequence: 2,
      },
      {
        id: "segment-1",
        transcriptId: "transcript-1",
        text: "First phrase",
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

const reviewBody = {
  review_id: "review-synthetic",
  revision_id: 4,
  status: "pending",
  items: [
    { speaker_id: "sp-8", current_label: "Speaker 8", attribution_state: "uncertain", disposition: null, version: 3 },
    { speaker_id: "sp-9", current_label: "Ana", attribution_state: "attributed", disposition: "named", version: 2 },
  ],
  labels_by_speaker_id: { "sp-8": "Speaker 8", "sp-9": "Ana" },
};

const reviewModel = {
  reviewId: "review-synthetic",
  revisionId: "4",
  status: "pending",
  items: [
    { speakerId: "sp-8", currentLabel: "Speaker 8", attributionState: "uncertain", disposition: null, expectedVersion: 3 },
    { speakerId: "sp-9", currentLabel: "Ana", attributionState: "attributed", disposition: "named", expectedVersion: 2 },
  ],
  labelsBySpeakerId: { "sp-8": "Speaker 8", "sp-9": "Ana" },
};

describe("speaker review API adapter", () => {
  it("normalizes the review response, including every speaker and the chosen labels", async () => {
    const fetchMock = mockFetch(reviewBody);

    await expect(api.getSpeakerReview("meeting-synthetic")).resolves.toEqual(reviewModel);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/meetings\/meeting-synthetic\/speaker-review$/);
  });

  it("defaults labels to an empty map when the response has none", async () => {
    mockFetch({ ...reviewBody, labels_by_speaker_id: undefined });

    await expect(api.getSpeakerReview("meeting-synthetic")).resolves.toMatchObject({ labelsBySpeakerId: {} });
  });

  it("sends a disposition as PUT with version and idempotency key and returns the full review", async () => {
    const fetchMock = mockFetch(reviewBody);

    await expect(api.submitSpeakerDisposition("meeting/1", "4", "sp-9", {
      disposition: "named", label: "Ana", expectedVersion: 1, idempotencyKey: "key-synthetic",
    })).resolves.toEqual(reviewModel);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/meetings\/meeting%2F1\/speaker-review\/revisions\/4\/speakers\/sp-9$/);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({
      disposition: "named", label: "Ana", expected_version: 1, idempotency_key: "key-synthetic",
    });
  });

  it("omits the label of a confirmation", async () => {
    const fetchMock = mockFetch(reviewBody);

    await api.submitSpeakerDisposition("m-1", "4", "sp-8", {
      disposition: "confirmed", expectedVersion: 3, idempotencyKey: "key-synthetic",
    });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      disposition: "confirmed", expected_version: 3, idempotency_key: "key-synthetic",
    });
  });

  it.each([
    [409, "conflict", copy.speakerReview.conflict],
    [404, "not_found", copy.speakerReview.notFound],
  ] as const)("maps HTTP %i to a %s review error", async (status, reason, message) => {
    mockFetch({ detail: "synthetic" }, status);

    const failure = api.submitSpeakerDisposition("m-1", "4", "sp-8", {
      disposition: "confirmed", expectedVersion: 3, idempotencyKey: "key-synthetic",
    });
    await expect(failure).rejects.toBeInstanceOf(api.SpeakerReviewRequestError);
    await expect(failure).rejects.toMatchObject({ reason, message });
  });

  it("maps a missing review to not found", async () => {
    mockFetch({ detail: "synthetic" }, 404);

    await expect(api.getSpeakerReview("m-1")).rejects.toMatchObject({ reason: "not_found" });
  });

  it("invalidates the session when a review request returns 401", async () => {
    mockFetch({ detail: "Unauthorized" }, 401);
    const removeItem = vi.fn();
    vi.stubGlobal("localStorage", { getItem: vi.fn().mockReturnValue("synthetic-token"), setItem: vi.fn(), removeItem });

    await expect(api.getSpeakerReview("m-1")).rejects.toThrow("Error 401");
    expect(removeItem).toHaveBeenCalledWith("sauri_token");
  });

  it("creates a distinct idempotency key per action", () => {
    expect(api.newIdempotencyKey()).not.toBe(api.newIdempotencyKey());
  });

  it("no longer exposes the derived excerpt route", () => {
    expect("playSpeakerExcerpt" in api).toBe(false);
  });
});

describe("meeting list API adapter", () => {
  it("clears the stored token when a protected request returns 401", async () => {
    const fetchMock = mockFetch({ detail: "Unauthorized" }, 401);
    const removeItem = vi.fn();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn().mockReturnValue("synthetic-token"),
      setItem: vi.fn(),
      removeItem,
    });

    await expect(api.listMeetings()).rejects.toThrow("Error 401");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(removeItem).toHaveBeenCalledTimes(1);
    expect(removeItem).toHaveBeenCalledWith("sauri_token");
  });

  it("maps the backend snake_case meeting payload into the shared UI type", async () => {
    mockFetch([{
      meeting_id: "fb02f350-0000-4000-8000-000000000001",
      meet_link: null,
      origin: "manual",
      process_state: "completed",
      failure_cause: null,
      created_at: "2026-10-28T17:45:00Z",
      title: "Synthetic processed meeting",
      duration_seconds: 1860,
      speaker_count: 3,
      summary_topic: "Synthetic topic",
      thumbnail_url: "https://storage.invalid/thumbnail.jpg?sig=x",
      media_kind: "video",
    }]);

    await expect(api.listMeetings()).resolves.toEqual([{
      id: "fb02f350-0000-4000-8000-000000000001",
      meetLink: null,
      origin: "manual",
      processState: "completed",
      failureCause: null,
      createdAt: "2026-10-28T17:45:00Z",
      title: "Synthetic processed meeting",
      durationSeconds: 1860,
      speakerCount: 3,
      summaryTopic: "Synthetic topic",
      thumbnailUrl: "https://storage.invalid/thumbnail.jpg?sig=x",
      mediaKind: "video",
    }]);
  });

  it("maps absent or null summary fields to null", async () => {
    mockFetch([
      {
        meeting_id: "m-1", meet_link: null, origin: "manual", process_state: "queued",
        failure_cause: null, created_at: null, title: "Legacy payload",
      },
      {
        meeting_id: "m-2", meet_link: null, origin: "manual", process_state: "queued",
        failure_cause: null, created_at: null, title: "Explicit nulls",
        duration_seconds: null, speaker_count: null, summary_topic: null,
      },
    ]);

    const items = await api.listMeetings();
    for (const item of items) {
      expect(item.durationSeconds).toBeNull();
      expect(item.speakerCount).toBeNull();
      expect(item.summaryTopic).toBeNull();
      expect(item.thumbnailUrl).toBeNull();
      expect(item.mediaKind).toBeNull();
    }
  });
});

describe("meeting summary API adapters", () => {
  it("maps draft citations and keeps legacy point text without invented sources", async () => {
    const fetchMock = mockFetch({
      summary_id: "summary-1", meeting_id: "meeting-1", template_id: "template-1",
      template_name: "General", template_version: 3, topic: "Synthetic topic",
      key_points: [
        { text: "Synthetic point", sources: [{ passage_id: "P0001", start_ms: 1234, end_ms: 5678 }] },
        "Legacy point",
      ],
      review_state: "draft", generation: 2, created_at: "created", updated_at: "updated",
    });
    await expect(api.getMeetingSummary("meeting / 1")).resolves.toEqual({
      summaryId: "summary-1", meetingId: "meeting-1", templateId: "template-1",
      templateName: "General", templateVersion: 3, topic: "Synthetic topic",
      schemaVersion: 1,
      keyPoints: [
        { text: "Synthetic point", sources: [{ passageId: "P0001", startMs: 1234, endMs: 5678 }] },
        "Legacy point",
      ],
      conclusion: null,
      reviewState: "draft", generation: 2, createdAt: "created", updatedAt: "updated",
    });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/meetings/meeting%20%2F%201/summary"), {
      method: "GET", headers: { Authorization: "Bearer synthetic-token", "Content-Type": "application/json" },
    });
  });

  it("maps structured v2 blocks, nested items and the conclusion", async () => {
    mockFetch({
      summary_id: "summary-2", meeting_id: "meeting-1", template_id: "template-1",
      template_name: "General", template_version: 4, topic: "Synthetic paragraph", schema_version: 2,
      key_points: [{
        title: "Synthetic block",
        items: [{ text: "Synthetic item", sub_items: ["Synthetic detail"] }, { text: "Plain item" }],
        sources: [{ passage_id: "P0002", start_ms: 10, end_ms: 20 }],
      }],
      conclusion: "Synthetic conclusion",
      review_state: "draft", generation: 1, created_at: "created", updated_at: "updated",
    });
    await expect(api.getMeetingSummary("meeting-1")).resolves.toMatchObject({
      schemaVersion: 2, topic: "Synthetic paragraph", conclusion: "Synthetic conclusion",
      keyPoints: [{
        title: "Synthetic block",
        items: [{ text: "Synthetic item", subItems: ["Synthetic detail"] }, { text: "Plain item", subItems: [] }],
        sources: [{ passageId: "P0002", startMs: 10, endMs: 20 }],
      }],
    });
  });

  it.each(["pending", "running", "succeeded", "failed"])("maps latest request state %s and optional failure cause", async (status) => {
    const fetchMock = mockFetch({ event_id: "event-1", generation: 3, status, failure_cause: "summary_invalid" });
    await expect(api.getLatestSummaryRequest("meeting / 1")).resolves.toEqual({
      eventId: "event-1", generation: 3, status, failureCause: "summary_invalid",
    });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/meeting%20%2F%201/summary-requests/latest"),
      expect.objectContaining({ method: "GET", headers: expect.objectContaining({ Authorization: "Bearer synthetic-token" }) }));
  });

  it("maps the optional request and start times and tolerates their absence", async () => {
    mockFetch({
      event_id: "event-1", generation: 3, status: "running",
      requested_at: "2026-11-16T10:00:00Z", started_at: "2026-11-16T10:00:05Z",
    });
    await expect(api.getLatestSummaryRequest("meeting-1")).resolves.toEqual({
      eventId: "event-1", generation: 3, status: "running",
      requestedAt: "2026-11-16T10:00:00Z", startedAt: "2026-11-16T10:00:05Z",
    });
    mockFetch({ event_id: "event-2", generation: 1, status: "succeeded", requested_at: null });
    await expect(api.getLatestSummaryRequest("meeting-1")).resolves.toEqual({
      eventId: "event-2", generation: 1, status: "succeeded", requestedAt: null,
    });
  });

  it("posts JSON using the default template and maps the accepted request", async () => {
    const fetchMock = mockFetch({ event_id: "event-1", generation: 3, status: "pending" }, 202);
    await expect(api.requestMeetingSummary("meeting / 1")).resolves.toEqual({
      eventId: "event-1", generation: 3, status: "pending", failureCause: undefined,
    });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/meeting%20%2F%201/summary-requests"), {
      method: "POST", body: "{}", headers: { Authorization: "Bearer synthetic-token", "Content-Type": "application/json" },
    });
  });

  it.each([api.getMeetingSummary, api.getLatestSummaryRequest])("returns null only for a missing artifact or request", async (get) => {
    mockFetch({ detail: "Not found" }, 404);
    await expect(get("meeting-1")).resolves.toBeNull();
    mockFetch({ detail: "private diagnostic" }, 500);
    await expect(get("meeting-1")).rejects.toThrow("Error 500");
  });

  it.each([api.getMeetingSummary, api.getLatestSummaryRequest, api.requestMeetingSummary])(
    "invalidates unauthorized sessions and does not expose server diagnostics", async (call) => {
      mockFetch({ detail: "private diagnostic" }, 401);
      const unauthorized = vi.spyOn(window, "dispatchEvent");
      await expect(call("meeting-1")).rejects.toThrow("Error 401");
      expect(localStorage.removeItem).toHaveBeenCalledWith("sauri_token");
      expect(unauthorized.mock.calls[0][0].type).toBe("sauri:unauthorized");
    },
  );
});

describe("attributed transcript and meeting state adapters", () => {
  it("maps word turns without reusing segment attribution or dropping ambiguous and unassigned text", async () => {
    mockFetch({
      transcript_id: "transcript-1", meeting_id: "meeting-1", language: "es", provider: "local",
      supports_turns: true, created_at: "2026-11-14T12:00:00Z", presentation: "words",
      segments: [{ id: "old-segment", text: "Legacy text", start_ms: 0, end_ms: 90000, sequence: 1 }],
      turns: [
        { sequence: 1, speaker_id: "speaker-a", speaker_label: "Speaker A", start_ms: 65432, end_ms: 68000,
          text: "Synthetic first turn", word_count: 3, has_ambiguous: false },
        { sequence: 2, speaker_id: null, speaker_label: null, start_ms: 68000, end_ms: 70000,
          text: "Synthetic uncertain turn", word_count: 3, has_ambiguous: true },
      ],
    });
    const result = await api.getTranscript("meeting-1");
    expect(result.presentation).toBe("words");
    expect(result.turns).toEqual([
      { id: "transcript-1:turn:1", transcriptId: "transcript-1", sequence: 1, speakerId: "speaker-a",
        speakerLabel: "Speaker A", startMs: 65432, endMs: 68000, text: "Synthetic first turn",
        wordCount: 3, hasAmbiguous: false },
      { id: "transcript-1:turn:2", transcriptId: "transcript-1", sequence: 2, speakerId: null,
        speakerLabel: null, startMs: 68000, endMs: 70000, text: "Synthetic uncertain turn",
        wordCount: 3, hasAmbiguous: true },
    ]);
    expect(result.segments[0].id).toBe("old-segment");
  });

  it("keeps segments mode on its existing mapping even if unrelated turns are supplied", async () => {
    mockFetch({
      transcript_id: "t-1", meeting_id: "m-1", language: "es", provider: "local",
      supports_turns: true, created_at: "2026-11-14T12:00:00Z", presentation: "segments",
      segments: [{ id: "s-1", text: "Synthetic segment", start_ms: 1000, end_ms: 2000, sequence: 1 }],
      turns: [{ text: "Do not use" }],
    });
    const result = await api.getTranscript("m-1");
    expect(result.presentation).toBe("segments");
    expect(result.turns).toEqual([
      { id: "s-1", transcriptId: "t-1", sequence: 1, startMs: 1000, endMs: 2000, text: "Synthetic segment" },
    ]);
  });

  it("maps failure_cause without inferring retry support", async () => {
    const fetchMock = mockFetch({ meeting_id: "m / 1", process_state: "failed", failure_cause: "engine_failure" });
    await expect(api.getMeeting("m / 1")).resolves.toEqual({
      meetingId: "m / 1", processState: "failed", failureCause: "engine_failure",
    });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/meetings/m%20%2F%201"),
      expect.objectContaining({ method: "GET" }));
  });
});

describe("renameMeeting and deleteMeeting", () => {
  it("PATCHes the encoded URL with the title and maps the response", async () => {
    const fetchMock = mockFetch({ meeting_id: "m / 1", title: "New title" });
    await expect(api.renameMeeting("m / 1", "New title")).resolves.toEqual({
      meetingId: "m / 1",
      title: "New title",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/meetings/m%20%2F%201"),
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "New title" }),
        headers: expect.objectContaining({ Authorization: "Bearer synthetic-token" }),
      }),
    );
  });

  it("rejects rename on 404 and 422", async () => {
    mockFetch({}, 404);
    await expect(api.renameMeeting("m-1", "x")).rejects.toThrow("Error 404");
    mockFetch({}, 422);
    await expect(api.renameMeeting("m-1", "")).rejects.toThrow("Error 422");
  });

  it("DELETEs the encoded URL and resolves on 204 without reading a body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => {
        throw new Error("no body");
      },
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("localStorage", {
      getItem: vi.fn().mockReturnValue("synthetic-token"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
    });
    await expect(api.deleteMeeting("m / 1")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/meetings/m%20%2F%201"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("rejects delete on 404", async () => {
    mockFetch({}, 404);
    await expect(api.deleteMeeting("m-1")).rejects.toThrow("Error 404");
  });
});

describe("summary templates API client", () => {
  const wireTemplate = {
    id: "t1",
    name: "Resultados clave",
    instructions: "Instructions",
    owner_user_id: "u1",
    category_id: "c1",
    version: 3,
    is_default: true,
    provenance: "Note",
    created_at: "2026-11-01T10:00:00+00:00",
    updated_at: "2026-11-02T10:00:00+00:00",
  };
  const mapped = {
    id: "t1",
    name: "Resultados clave",
    instructions: "Instructions",
    categoryId: "c1",
    version: 3,
    isDefault: true,
    provenance: "Note",
    createdAt: "2026-11-01T10:00:00+00:00",
    updatedAt: "2026-11-02T10:00:00+00:00",
  };

  it("lists and gets templates, mapping the wire fields and defaulting a missing provenance", async () => {
    const fetchMock = mockFetch([wireTemplate, { ...wireTemplate, id: "t2", provenance: undefined }]);
    const listed = await api.listTemplates();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/v1\/templates$/),
      expect.objectContaining({ method: "GET" }),
    );
    expect(listed[0]).toEqual(mapped);
    expect(listed[1].provenance).toBeNull();

    mockFetch(wireTemplate);
    expect(await api.getTemplate("t 1")).toEqual(mapped);
  });

  it("encodes the id when getting one template", async () => {
    const fetchMock = mockFetch(wireTemplate);
    await api.getTemplate("t / 1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/templates\/t%20%2F%201$/);
  });

  it("creates a template with the snake_case body", async () => {
    const fetchMock = mockFetch(wireTemplate);
    await api.createTemplate({ name: "N", instructions: "I", categoryId: null });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/templates$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ name: "N", instructions: "I", category_id: null });
  });

  it("PATCHes only the supplied fields, keeping an explicit null category", async () => {
    const fetchMock = mockFetch(wireTemplate);
    await api.updateTemplate("t1", { categoryId: null });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/templates\/t1$/);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ category_id: null });

    await api.updateTemplate("t1", { name: "N", instructions: "I" });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ name: "N", instructions: "I" });
  });

  it("lists and creates categories", async () => {
    mockFetch([{ id: "c1", name: "Comercial", created_at: "2026-11-01T10:00:00+00:00" }]);
    expect(await api.listTemplateCategories()).toEqual([
      { id: "c1", name: "Comercial", createdAt: "2026-11-01T10:00:00+00:00" },
    ]);

    const fetchMock = mockFetch({ id: "c2", name: "Soporte", created_at: "2026-11-03T10:00:00+00:00" });
    expect(await api.createTemplateCategory("Soporte")).toEqual({
      id: "c2", name: "Soporte", createdAt: "2026-11-03T10:00:00+00:00",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/templates\/categories$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ name: "Soporte" });
  });

  it("PUTs the default template and resolves on 204 without reading a body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => {
        throw new Error("no body");
      },
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("localStorage", {
      getItem: vi.fn().mockReturnValue("synthetic-token"),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
    });
    await expect(api.setDefaultTemplate("t1")).resolves.toBeUndefined();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/templates\/default$/);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ template_id: "t1" });
  });

  it("rejects with the status and ends the session on 401", async () => {
    mockFetch({}, 422);
    await expect(api.setDefaultTemplate("t1")).rejects.toThrow("Error 422");

    mockFetch({}, 401);
    const unauthorized = vi.fn();
    window.addEventListener("sauri:unauthorized", unauthorized, { once: true });
    await expect(api.listTemplates()).rejects.toThrow("Error 401");
    expect(unauthorized).toHaveBeenCalledTimes(1);
    expect(localStorage.removeItem).toHaveBeenCalledWith("sauri_token");

    mockFetch({}, 401);
    const unauthorizedAgain = vi.fn();
    window.addEventListener("sauri:unauthorized", unauthorizedAgain, { once: true });
    await expect(api.setDefaultTemplate("t1")).rejects.toThrow("Error 401");
    expect(unauthorizedAgain).toHaveBeenCalledTimes(1);
  });
});
