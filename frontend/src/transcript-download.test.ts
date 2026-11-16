// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { EmptyTranscriptError, downloadMeetingTranscript, saveTextFile, transcriptFilename } from "./transcript-download";
import { t } from "./i18n";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function stubDownloads() {
  const saved: Array<{ name: string; blob: Blob }> = [];
  let last: Blob | null = null;
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn((blob: Blob) => { last = blob; return "blob:x"; }),
    revokeObjectURL: vi.fn(),
  }));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.push({ name: this.download, blob: last as unknown as Blob });
  });
  return saved;
}

const emptyTranscript = {
  id: "t", meetingId: "m1", language: "es", provider: "x", supportsTurns: true, createdAt: "2026-10-28T17:45:00Z",
  segments: [], presentation: "words", turns: [],
} as unknown as api.MeetingTranscript;

describe("saveTextFile", () => {
  it("downloads UTF-8 text under the given name and leaves no link behind", () => {
    const saved = stubDownloads();
    saveTextFile("Notes.txt", "hola");
    expect(saved.map((file) => file.name)).toEqual(["Notes.txt"]);
    expect(saved[0].blob.type).toBe("text/plain;charset=utf-8");
    expect(document.querySelector("a[download]")).toBeNull();
  });
});

describe("transcriptFilename", () => {
  it("uses the title, falling back to a name from the id", () => {
    expect(transcriptFilename("m1", "Weekly: sync?")).toBe("Weekly sync.txt");
    expect(transcriptFilename("m1", "  ")).toBe(t("meeting:transcriptFilename", { id: "m1" }));
    expect(transcriptFilename("m1", null)).toBe(t("meeting:transcriptFilename", { id: "m1" }));
  });
});

describe("downloadMeetingTranscript", () => {
  it("refuses to save an empty transcript", async () => {
    const saved = stubDownloads();
    vi.spyOn(api, "getTranscript").mockResolvedValue(emptyTranscript);
    vi.spyOn(api, "getDiarization").mockRejectedValue(new Error("Error 404"));
    vi.spyOn(api, "getSpeakerReview").mockRejectedValue(new Error("Error 404"));
    await expect(downloadMeetingTranscript("m1", "Weekly")).rejects.toBeInstanceOf(EmptyTranscriptError);
    expect(saved).toHaveLength(0);
  });

  it("fails when speaker data fails for a reason other than missing", async () => {
    const saved = stubDownloads();
    vi.spyOn(api, "getTranscript").mockResolvedValue(emptyTranscript);
    vi.spyOn(api, "getDiarization").mockRejectedValue(new Error("Error 500"));
    vi.spyOn(api, "getSpeakerReview").mockRejectedValue(new Error("Error 404"));
    await expect(downloadMeetingTranscript("m1", "Weekly")).rejects.toThrow("Error 500");
    expect(saved).toHaveLength(0);
  });

  it("treats a speaker review that is not found as no review", async () => {
    stubDownloads();
    vi.spyOn(api, "getTranscript").mockResolvedValue(emptyTranscript);
    vi.spyOn(api, "getDiarization").mockResolvedValue({ speakers: [], assignments: [] } as unknown as api.MeetingDiarization);
    vi.spyOn(api, "getSpeakerReview").mockRejectedValue(Object.assign(new Error("gone"), { reason: "not_found" }));
    await expect(downloadMeetingTranscript("m1", "Weekly")).rejects.toBeInstanceOf(EmptyTranscriptError);
  });
});
