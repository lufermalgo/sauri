import { getPlaybackManifest, type PlaybackManifest, type PlaybackSource } from "./api";
import { meeting as text } from "./copy/meeting";
import { titleToFilename } from "./download-filename";

/** Where the file ended up: written to disk, or handed to the browser in another tab. */
export type MediaDownloadOutcome = "saved" | "opened" | "cancelled";

export class NoMediaError extends Error {
  constructor() {
    super("no media source");
  }
}

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

const EXTENSION_BY_MIME: Record<string, string> = {
  "video/webm": "webm", "video/mp4": "mp4", "video/quicktime": "mov", "video/x-matroska": "mkv",
  "audio/webm": "webm", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "m4a", "audio/mpeg": "mp3",
  "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/ogg": "ogg",
  "audio/opus": "opus",
};

const GENERIC_EXTENSION = "bin";

/** File extension for a source: from its mime type, else from its URL path, else a generic one. */
export function mediaExtension(source: PlaybackSource): string {
  const mime = source.mime_type?.split(";")[0].trim().toLowerCase();
  if (mime && EXTENSION_BY_MIME[mime]) return EXTENSION_BY_MIME[mime];
  try {
    const fromPath = /\.([a-z0-9]{2,5})$/i.exec(new URL(source.url).pathname)?.[1];
    if (fromPath) return fromPath.toLowerCase();
  } catch {
    // An unparsable URL cannot name the file; the generic extension applies.
  }
  return GENERIC_EXTENSION;
}

/** `<title>.<ext>`, or an id-based name when the title leaves nothing usable. */
export function mediaFilename(meetingId: string, title: string | null | undefined, source: PlaybackSource): string {
  const extension = mediaExtension(source);
  return titleToFilename(title, extension) ?? text.mediaFilename(meetingId, extension);
}

interface WritableFileHandle {
  createWritable(): Promise<WritableStream<Uint8Array>>;
}

type SaveFilePicker = (options: { suggestedName: string }) => Promise<WritableFileHandle>;

function savePicker(): SaveFilePicker | null {
  const picker = (window as unknown as { showSaveFilePicker?: SaveFilePicker }).showSaveFilePicker;
  return typeof picker === "function" ? picker.bind(window) : null;
}

/**
 * Last resort: the signed link is cross-origin and carries no `Content-Disposition`, so the `download`
 * attribute is ignored and the browser shows the file in a new tab instead of saving it.
 */
function openInNewTab(url: string, filename: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  document.body.append(link);
  link.click();
  link.remove();
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Reports whole-percent steps while the body flows through, or `null` when the size is unknown. */
function countingStream(total: number | null, onProgress: (percent: number | null) => void): TransformStream<Uint8Array, Uint8Array> {
  let received = 0;
  let last: number | null = total ? -1 : null;
  return new TransformStream({
    transform(chunk, controller) {
      received += chunk.byteLength;
      const percent = total ? Math.min(100, Math.floor((received / total) * 100)) : null;
      if (percent !== last) { last = percent; onProgress(percent); }
      controller.enqueue(chunk);
    },
  });
}

/**
 * Saves one signed media link to disk without holding the file in memory (recordings can be several GB):
 * the response body is piped straight into a file the user chose with the File System Access API
 * (Chromium over HTTPS or localhost). Needs the object store to allow the portal origin (CORS); when
 * the browser has no picker, the link is not readable by script, or the picker cannot open, the link
 * opens in a new tab instead and the user saves it from there.
 */
export async function saveSignedMedia(
  url: string, filename: string, onProgress: (percent: number | null) => void = () => undefined,
): Promise<MediaDownloadOutcome> {
  const picker = savePicker();
  if (!picker) { openInNewTab(url, filename); return "opened"; }

  let response: Response;
  try {
    response = await fetch(url);
    if (!response.ok || !response.body) throw new Error(`Error ${response.status}`);
  } catch {
    // Typically the object store refuses the portal origin: the plain link still works.
    openInNewTab(url, filename);
    return "opened";
  }

  let handle: WritableFileHandle;
  try {
    handle = await picker({ suggestedName: filename });
  } catch (error) {
    void response.body.cancel();
    if (isAbort(error)) return "cancelled";
    openInNewTab(url, filename);
    return "opened";
  }

  const length = Number(response.headers.get("content-length"));
  onProgress(length > 0 ? 0 : null);
  const writable = await handle.createWritable();
  await response.body
    .pipeThrough(countingStream(length > 0 ? length : null, onProgress))
    .pipeTo(writable);
  return "saved";
}

/**
 * Downloads a recording's video (or its audio when it has no video) as `<title>.<ext>`. It always asks
 * for a fresh manifest: signed links expire, and one loaded with the page may be long dead.
 */
export async function downloadMeetingMedia(
  meetingId: string, title: string | null | undefined, onProgress?: (percent: number | null) => void,
): Promise<MediaDownloadOutcome> {
  const choice = pickMediaSource(await getPlaybackManifest(meetingId));
  if (!choice) throw new NoMediaError();
  return saveSignedMedia(choice.source.url, mediaFilename(meetingId, title, choice.source), onProgress);
}
