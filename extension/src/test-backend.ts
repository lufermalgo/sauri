// Test helpers for the local app's discovery (core/backend.ts).
export const DESKTOP_URL = "http://localhost:41750";
export const LEGACY_URL = "http://localhost:8000";

/** A signed /health answer of the current app. */
export const sauriHealth = () => new Response(JSON.stringify({ status: "ok", service: "sauri", version: "0.2.0" }));

/** Whether a fetched URL is a discovery probe rather than an API call. */
export const isHealth = (url: unknown) => String(url).endsWith("/health");
