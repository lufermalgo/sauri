import { requireBackendUrl } from "../core/local-pairing";

/** The portal served by the local app (or a configured development portal), optionally on one meeting. */
export async function portalDestination(meetingId?: string): Promise<string> {
  const url = new URL(import.meta.env.VITE_SAURI_PORTAL_URL ?? await requireBackendUrl());
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("Invalid Sauri portal origin");
  }
  if (meetingId) url.searchParams.set("meetingId", meetingId);
  return url.href;
}
