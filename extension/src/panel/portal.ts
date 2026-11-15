export function portalDestination(meetingId?: string): string {
  const url = new URL(import.meta.env.VITE_SAURI_PORTAL_URL ?? "http://localhost:5173");
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("Invalid Sauri portal origin");
  }
  if (meetingId) url.searchParams.set("meetingId", meetingId);
  return url.href;
}
