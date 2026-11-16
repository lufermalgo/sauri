// Feature: chrome-side-panel, Property 17: CaptureState state machine
// Feature: chrome-side-panel, Property 18: New Note button enablement based on CaptureState

import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { applyCaptureEvent, canCaptureCurrentTab, isMeetUrl, newNoteButtonEnabled, videoPresenceFromStream } from "./capture";
import type { CaptureState, CaptureEvent } from "./types";

const STATES: CaptureState[] = ["idle", "recording", "stopping"];
const EVENTS: CaptureEvent[] = ["start", "stop", "finished", "start_failure"];

const VALID_TRANSITIONS: Record<string, CaptureState> = {
  "idle:start": "recording",
  "recording:stop": "stopping",
  "stopping:finished": "idle",
};

describe("applyCaptureEvent", () => {
  it("Property 17: valid transitions per the table; otherwise keeps the state (Req. 2.4, 3.3, 3.4, 3.5)", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...STATES),
        fc.constantFrom(...EVENTS),
        (state, event) => {
          const result = applyCaptureEvent(state, event);
          const key = `${state}:${event}`;
          if (VALID_TRANSITIONS[key]) {
            expect(result).toBe(VALID_TRANSITIONS[key]);
          } else {
            expect(result).toBe(state);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe("capture source evidence", () => {
  it("reports observed video tracks before constructing the interleaved upload", () => {
    const captureSource = readFileSync("src/offscreen.ts", "utf8");
    const uploadSource = readFileSync("src/background.ts", "utf8");
    const trackEvidenceIndex = captureSource.indexOf("videoPresenceFromStream");
    const recorderConstructionIndex = captureSource.indexOf("new MediaRecorder");
    const evidenceMessageIndex = captureSource.indexOf("videoPresence:", trackEvidenceIndex);
    const uploadEvidenceIndex = uploadSource.indexOf("video_presence:");
    const formConstructionIndex = uploadSource.indexOf("new FormData()");

    expect(trackEvidenceIndex).toBeGreaterThanOrEqual(0);
    expect(recorderConstructionIndex).toBeGreaterThan(trackEvidenceIndex);
    expect(evidenceMessageIndex).toBeGreaterThan(trackEvidenceIndex);
    expect(uploadEvidenceIndex).toBeGreaterThanOrEqual(0);
    expect(formConstructionIndex).toBeGreaterThan(uploadEvidenceIndex);
    expect(uploadSource).toContain('formData.append("audio", blob, "recording.webm")');
  });
});

describe("videoPresenceFromStream", () => {
  it("reports muxed video only when a video track was actually observed", () => {
    const withVideo = { getVideoTracks: () => [{ kind: "video" }] } as unknown as MediaStream;
    const withoutVideo = { getVideoTracks: () => [] } as unknown as MediaStream;

    expect(videoPresenceFromStream(withVideo)).toBe("muxed");
    expect(videoPresenceFromStream(withoutVideo)).toBe("absent");
  });

  it("does not infer video presence from MIME type or capture mode", () => {
    const audioOnlyStream = { getVideoTracks: () => [] } as unknown as MediaStream;

    expect(videoPresenceFromStream(audioOnlyStream)).toBe("absent");
  });
});

describe("newNoteButtonEnabled", () => {
  it("Property 18: disabled iff recording/stopping (Req. 2.5)", () => {
    fc.assert(
      fc.property(fc.constantFrom(...STATES), (state) => {
        const enabled = newNoteButtonEnabled(state);
        expect(enabled).toBe(state === "idle");
      }),
      { numRuns: 100 }
    );
  });
});

describe("canCaptureCurrentTab", () => {
  it.each([
    "https://meet.google.com/abc-defg-hij",
    "https://example.com/watch?v=1",
    "https://zoom.us/wc/join/123",
    "https://teams.microsoft.com/v2/",
    "http://localhost:3000/lecture",
    "https://chrome.google.com/other",
  ])("accepts the ordinary web tab %s whatever the site", url => {
    expect(canCaptureCurrentTab(url)).toBe(true);
  });

  it.each([
    undefined, "", "not a url", "chrome://extensions", "chrome-extension://abc/page.html", "about:blank",
    "file:///Users/me/talk.html", "data:text/html,hi", "view-source:https://example.com", "blob:https://example.com/1",
    "https://chromewebstore.google.com/detail/x", "https://chrome.google.com/webstore/detail/x",
  ])("rejects the technically uncapturable %s", url => {
    expect(canCaptureCurrentTab(url)).toBe(false);
  });
});

describe("isMeetUrl", () => {
  it("recognizes Google Meet tabs only", () => {
    expect(isMeetUrl("https://meet.google.com/abc-defg-hij")).toBe(true);
    for (const url of [undefined, "", "http://meet.google.com/x", "https://meet.google.com.evil.example/", "https://example.com/meet.google.com/"]) {
      expect(isMeetUrl(url)).toBe(false);
    }
  });
});
