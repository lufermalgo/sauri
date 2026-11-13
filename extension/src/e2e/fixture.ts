// E2E-only offscreen media-owner boundary. Never bundled in a production build.
// Its sender has no tab, like the actual offscreen recorder; no auth/HTTP is mocked.
chrome.runtime.onMessage.addListener((message, _sender, respond) => {
  if (message.type === "stop-recording") { respond({ ok: true }); return false; }
  return false;
});
chrome.runtime.onConnect.addListener(port => {
  if (port.name !== "e2e-media-owner") return;
  port.onMessage.addListener(async ({ id, payload }: { id: number; payload: { type: string; sessionId?: string; size?: number; mimeType?: string } }) => {
    try { port.postMessage({ id, response: await chrome.runtime.sendMessage(payload) }); }
    catch (error) { port.postMessage({ id, error: String(error) }); }
  });
});
