/** Test helper: answers `/api/v1/engines` for screens that embed the engine selector but are not about it.
 * An empty setup: every process local, no providers, no local models, every engine running. */
export function answerEnginesApi(pathname: string): Response | null {
  if (!pathname.includes("/api/v1/engines")) return null;
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
  const process = (capability: string) => ({
    capability, provider_id: null, provider_kind: null, provider_label: null, model: "local:default",
    local_fallback: true, configured: false, version: 0, updated_at: null, notice_version: null,
  });
  if (pathname.endsWith("/capabilities")) {
    return json({ notice_versions: { transcription: 1, diarization: 1, summary: 1 }, kinds: [] });
  }
  if (pathname.endsWith("/processes")) return json(["transcription", "diarization", "summary"].map(process));
  if (pathname.endsWith("/providers")) return json([]);
  if (pathname.endsWith("/local/hardware")) {
    return json({ arch: "arm64", system: "Darwin", memory_gib: 16, cores: 8, metal: true, disk_free_bytes: 100e9 });
  }
  if (pathname.endsWith("/local/models")) return json({ catalog_version: 1, models: [], recommendations: {}, active_job: null, active: {}, adoption: null });
  if (pathname.endsWith("/status")) {
    return json({ engines: ["asr", "diar", "llm"].map((id) => ({ id, port: 8000, state: "running" })), secret_store: null });
  }
  return json([]);
}
