// CaptureState state machine — Req. 2.4, 2.5, 3.3, 3.4, 3.5
import type { CaptureState, CaptureEvent } from "./types";

export function videoPresenceFromStream(stream: MediaStream): "muxed" | "absent" {
  return stream.getVideoTracks().length > 0 ? "muxed" : "absent";
}

const TRANSITIONS: Record<CaptureState, Partial<Record<CaptureEvent, CaptureState>>> = {
  idle: { start: "recording" },
  recording: { stop: "stopping" },
  stopping: { finished: "idle" },
};

/** Applies an event to the CaptureState; keeps the state if the transition is invalid (Req. 2.4, 3.3, 3.4, 3.5) */
export function applyCaptureEvent(
  state: CaptureState,
  event: CaptureEvent
): CaptureState {
  return TRANSITIONS[state][event] ?? state;
}

/** The New Note button is enabled iff CaptureState is "idle" (Req. 2.5) */
export function newNoteButtonEnabled(state: CaptureState): boolean {
  return state === "idle";
}

export function isMeetUrl(url?: string): boolean {
  return !!url?.startsWith("https://meet.google.com/");
}

/**
 * Technical limit only: ordinary http(s) tabs that Chrome lets an extension capture
 * and script. Browser pages, extension pages, local files and the Web Store are out.
 * No site (Meet or otherwise) is preferred or excluded here.
 */
export function canCaptureCurrentTab(url?: string): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol) &&
      parsed.hostname !== "chromewebstore.google.com" &&
      !(parsed.hostname === "chrome.google.com" && parsed.pathname.startsWith("/webstore"));
  } catch {
    return false;
  }
}
