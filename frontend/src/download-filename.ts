const MAX_BASE_LENGTH = 120;
// Characters invalid on Windows, macOS or Linux file systems, plus control characters.
const INVALID_CHARS = /[\\/:*?"<>|\u0000-\u001f\u007f-\u009f]/g;
const MEDIA_EXTENSION = /\.(webm|mp4|m4a|mp3|wav|mov|mkv|ogg|opus)$/i;
const RESERVED_WINDOWS_NAME = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i;

function trimEdges(value: string): string {
  return value.replace(/^[\s.]+|[\s.]+$/g, "");
}

/**
 * Builds a safe download file name "<title>.<extension>" from a meeting title.
 * Returns null when nothing usable is left, so the caller can use its own fallback.
 */
export function titleToFilename(title: string | null | undefined, extension: string): string | null {
  if (!title) return null;
  const spaced = title.normalize("NFC").replace(INVALID_CHARS, " ").replace(/\s+/g, " ").trim();
  // Uploaded recordings are titled with their original file name: drop its media extension.
  let base = trimEdges(spaced.replace(MEDIA_EXTENSION, ""));
  // Cut by code points so a surrogate pair is never split.
  base = trimEdges(Array.from(base).slice(0, MAX_BASE_LENGTH).join(""));
  if (!base) return null;
  // Windows reserves these names even when an extension follows them.
  if (RESERVED_WINDOWS_NAME.test(base.split(".")[0].trim())) base = `_${base}`;
  return `${base}.${extension}`;
}
