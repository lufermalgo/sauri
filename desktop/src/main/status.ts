// GET /api/v1/local/status → {ready, processing, version, mode}, asked the way the portal asks it.
import http from "node:http";

export interface LocalStatus {
  ready: boolean;
  processing: number;
  version: string;
  mode: string;
}

export function parseStatus(raw: unknown): LocalStatus | null {
  if (typeof raw !== "object" || raw === null) return null;
  const value = raw as Record<string, unknown>;
  if (typeof value.ready !== "boolean" || typeof value.processing !== "number" || value.processing < 0) return null;
  return {
    ready: value.ready,
    processing: Math.floor(value.processing),
    version: typeof value.version === "string" ? value.version : "",
    mode: typeof value.mode === "string" ? value.mode : "",
  };
}

/**
 * The local guard accepts the status route from the portal's own origin (`Sec-Fetch-Site: same-origin` with the
 * exact Host); the app also sends the local cookie. Null when the API does not answer.
 */
export function fetchLocalStatus(port: number, token: string, timeoutMs = 3000): Promise<LocalStatus | null> {
  return new Promise((resolve) => {
    const request = http.get(
      {
        host: "127.0.0.1",
        port,
        path: "/api/v1/local/status",
        headers: { Host: `localhost:${port}`, "Sec-Fetch-Site": "same-origin", Cookie: `sauri_local=${token}` },
        timeout: timeoutMs,
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer) => chunks.push(chunk));
        response.on("end", () => {
          if (response.statusCode !== 200) return resolve(null);
          try {
            resolve(parseStatus(JSON.parse(Buffer.concat(chunks).toString("utf8"))));
          } catch {
            resolve(null);
          }
        });
      },
    );
    request.on("timeout", () => request.destroy());
    request.on("error", () => resolve(null));
  });
}
