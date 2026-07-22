// ViewState derivation — Req. 12.3, 12.5, 12.6, 12.7
import type { RemoteRequest, ViewState } from "./types";

/** Derives the ViewState from the phase of a RemoteRequest (Req. 12.3, 12.5-12.7) */
export function deriveViewState<T>(request: RemoteRequest<T>): ViewState {
  switch (request.phase) {
    case "initial":
    case "in_progress":
      return "loading";
    case "success":
      return (request.data?.length ?? 0) > 0 ? "withData" : "empty";
    case "failure":
      return "error";
    default:
      return "error";
  }
}
