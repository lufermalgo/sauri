import { getMediaDownloadLink, type PlaybackManifest, type PlaybackSource } from "./api";

export interface MediaChoice {
  source: PlaybackSource;
  /** The recording has no video: the audio track is what gets downloaded. */
  audioOnly: boolean;
}

/** The file a recording's download offers: its video (muxed or separate), or its audio when it has no video. */
export function pickMediaSource(manifest: PlaybackManifest | null | undefined): MediaChoice | null {
  if (!manifest) return null;
  const audioOnly = manifest.video_presence === "absent" || manifest.video_presence === "unknown";
  const source = audioOnly ? manifest.audio_source
    : manifest.video_presence === "muxed" ? manifest.muxed_video_source : manifest.video_sources[0];
  return source?.url ? { source, audioOnly } : null;
}

/**
 * Saves a recording's video (or its audio when it has no video). The API hands out a short-lived signed
 * link whose response carries `Content-Disposition: attachment` with the meeting title as file name, so the
 * browser saves the file by itself, in every browser, without leaving the page. The link is requested on
 * each click: it expires within minutes.
 */
export async function downloadMeetingMedia(meetingId: string): Promise<void> {
  const { url } = await getMediaDownloadLink(meetingId);
  const link = document.createElement("a");
  link.href = url;
  link.rel = "noopener noreferrer";
  document.body.append(link);
  link.click();
  link.remove();
}
