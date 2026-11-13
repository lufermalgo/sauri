/** Pure, provider-neutral decision; persistence must claim the result atomically. */
export type CompletionTrigger = "stop" | "captured-tab-close" | "meeting-ended";

export interface CaptureHandle {
  provider: "meet" | "teams";
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
  provider: "meet" | "teams";
  completionClaimed: boolean;
}

export function applyCompletionEvent<T extends CompletionClaim>(state: T, event: CompletionTrigger): { state: T; shouldFinalize: boolean } {
  if (event === "meeting-ended" || state.completionClaimed) {
    return { state, shouldFinalize: false };
  }
  return { state: { ...state, completionClaimed: true }, shouldFinalize: true };
}
