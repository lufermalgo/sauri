/** Pure, provider-neutral decision; persistence must claim the result atomically. */
export type CompletionTrigger = "stop" | "captured-tab-close" | "meeting-ended";

/** Where a capture came from: a Google Meet tab, a Teams tab, or any other web tab. */
export type CaptureProvider = "meet" | "teams" | "tab";

export interface CaptureHandle {
  provider: CaptureProvider;
  capturedTabId: number;
  sessionId: string;
}

/** The UI projection may request Stop, but only a matching durable handle owns media. */
export function matchesCaptureHandle(saved: CaptureHandle, projected: CaptureHandle): boolean {
  return saved.provider === projected.provider &&
    saved.capturedTabId === projected.capturedTabId &&
    saved.sessionId === projected.sessionId;
}

export interface CompletionClaim {
  sessionId: string;
  provider: CaptureProvider;
  completionClaimed: boolean;
}

export function applyCompletionEvent<T extends CompletionClaim>(state: T, event: CompletionTrigger): { state: T; shouldFinalize: boolean } {
  if (event === "meeting-ended" || state.completionClaimed) {
    return { state, shouldFinalize: false };
  }
  return { state: { ...state, completionClaimed: true }, shouldFinalize: true };
}
