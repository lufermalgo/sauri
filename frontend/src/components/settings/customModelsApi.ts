// TEMP(U1): copy of what PR 1256 (feat/custom-model-hf) adds to `src/api.ts` and `@sauri/shared-types`, with the
// same names and shapes. When PR 1256 is in main: delete this file, import the functions from "../../api" and the
// types from "@sauri/shared-types", and read `custom` / `origin` straight from `LocalModel` in localModelState.ts.
import type { LocalJob, LocalModel } from "@sauri/shared-types";
import { EnginesApiError, TOKEN_KEY, isLocalMode } from "../../api";

export interface LocalModelOrigin {
  repo: string;
  revision: string;
  file: string;
}

export type CustomModelProcess = "transcription" | "summary";

export interface CustomModelFile {
  path: string;
  size: number;
  sha256: string;
}

export interface CustomResolveResponse {
  repo: string;
  revision: string;
  license: string | null;
  files: CustomModelFile[];
}

export interface CustomInstallRequest {
  process: CustomModelProcess;
  repo: string;
  revision: string;
  file: string;
}

/** `LocalModel` with the two fields PR 1256 adds to it. */
export type LocalModelWithOrigin = LocalModel & { custom?: boolean; origin?: LocalModelOrigin };

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Minimal stand-in for `enginesRequest` in api.ts (not exported there). */
async function post<T>(path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = isLocalMode() ? null : localStorage.getItem(TOKEN_KEY);
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${BASE_URL}/api/v1/engines${path}`, { method: "POST", headers, body: JSON.stringify(body) });
  if (!response.ok) {
    let code: string | null = null;
    let figures: Record<string, unknown> = {};
    try {
      const { detail, ...rest } = (await response.json()) as { detail?: unknown } & Record<string, unknown>;
      if (typeof detail === "string") code = detail;
      figures = rest;
    } catch {
      // The body is not JSON: the status alone describes the failure.
    }
    throw new EnginesApiError(response.status, code, figures);
  }
  return (await response.json()) as T;
}

export function resolveCustomModel(process: CustomModelProcess, source: string): Promise<CustomResolveResponse> {
  return post("/local/custom/resolve", { process, source });
}

export function installCustomModel(request: CustomInstallRequest): Promise<LocalJob> {
  const { process, repo, revision, file } = request;
  return post("/local/custom/install", { process, repo, revision, file });
}
