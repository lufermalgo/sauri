// Transport policy shared by every call to the backend (Req. 13.5).

export class InsecureTransportError extends Error {
  constructor(url: string) {
    super(`The backend must be used over HTTPS (or http://localhost in development): ${url}`);
    this.name = "InsecureTransportError";
  }
}

/** Requires https:// except on http://localhost or 127.0.0.1 (development) — Req. 13.5 */
export function validateTransport(backendUrl: string): void {
  const url = new URL(backendUrl);
  const isLocalhost = url.hostname === "localhost" || url.hostname === "127.0.0.1";
  if (url.protocol === "https:") return;
  if (url.protocol === "http:" && isLocalhost) return;
  throw new InsecureTransportError(backendUrl);
}
