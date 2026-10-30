import { useEffect, useRef, useState } from "react";
import { uploadRecording } from "../api";
import type { RecordingUploadData } from "../api";

interface EbmlElement {
  id: number;
  dataStart: number;
  dataEnd: number;
}

const MAX_WEBM_TRACKS_BYTES = 64 * 1024;
const MAX_WEBM_ELEMENT_READS = 256;
const EBML_HEADER = [0x1a, 0x45, 0xdf, 0xa3];

interface EbmlReadBudget {
  remaining: number;
}

function readEbmlElement(bytes: Uint8Array, offset: number, parentEnd = bytes.length): EbmlElement | null {
  if (offset >= bytes.length) return null;
  let idLength = 1;
  let marker = 0x80;
  while (idLength <= 4 && (bytes[offset] & marker) === 0) {
    idLength += 1;
    marker >>= 1;
  }
  if (idLength > 4 || offset + idLength >= bytes.length) return null;
  let id = 0;
  for (let index = 0; index < idLength; index += 1) id = (id * 256) + bytes[offset + index];

  const sizeOffset = offset + idLength;
  let sizeLength = 1;
  marker = 0x80;
  while (sizeLength <= 8 && (bytes[sizeOffset] & marker) === 0) {
    sizeLength += 1;
    marker >>= 1;
  }
  if (sizeLength > 8 || sizeOffset + sizeLength > bytes.length) return null;
  const firstSizeByte = bytes[sizeOffset] & (marker - 1);
  let size = firstSizeByte;
  let unknownSize = firstSizeByte === marker - 1;
  for (let index = 1; index < sizeLength; index += 1) {
    size = (size * 256) + bytes[sizeOffset + index];
    unknownSize &&= bytes[sizeOffset + index] === 0xff;
  }
  const dataStart = sizeOffset + sizeLength;
  const dataEnd = unknownSize ? parentEnd : dataStart + size;
  if (!Number.isSafeInteger(dataEnd) || dataEnd > parentEnd) return null;
  return { id, dataStart, dataEnd };
}

function findEbmlChild(bytes: Uint8Array, parent: EbmlElement, childId: number): EbmlElement | null {
  for (let offset = parent.dataStart; offset < parent.dataEnd;) {
    const child = readEbmlElement(bytes, offset);
    if (!child || child.dataEnd > parent.dataEnd) return null;
    if (child.id === childId) return child;
    offset = child.dataEnd;
  }
  return null;
}

async function readFileRange(file: File, start: number, end: number): Promise<Uint8Array> {
  const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => reader.result instanceof ArrayBuffer ? resolve(reader.result) : reject(new Error("Unable to read recording data."));
    reader.onerror = () => reject(reader.error ?? new Error("Unable to read recording data."));
    reader.readAsArrayBuffer(file.slice(start, end));
  });
  return new Uint8Array(buffer);
}

async function readWebmElementAt(file: File, offset: number, parentEnd: number, budget: EbmlReadBudget): Promise<EbmlElement | null> {
  if (budget.remaining <= 0) return null;
  budget.remaining -= 1;
  const bytes = await readFileRange(file, offset, Math.min(offset + 12, parentEnd));
  const element = readEbmlElement(bytes, 0, parentEnd - offset);
  return element ? { id: element.id, dataStart: offset + element.dataStart, dataEnd: offset + element.dataEnd } : null;
}

async function inspectWebmTracks(file: File, signature: Uint8Array): Promise<{ hasAudio: boolean; hasVideo: boolean } | null> {
  if (!hasWebmSignature(signature)) return null;

  const budget = { remaining: MAX_WEBM_ELEMENT_READS };
  const header = await readWebmElementAt(file, 0, file.size, budget);
  if (!header || header.id !== 0x1a45dfa3 || header.dataEnd <= EBML_HEADER.length) return null;

  let segment: EbmlElement | null = null;
  for (let offset = header.dataEnd; offset < file.size;) {
    const element = await readWebmElementAt(file, offset, file.size, budget);
    if (!element) return null;
    if (element.id === 0x18538067) {
      segment = element;
      break;
    }
    if (element.dataEnd <= offset) return null;
    offset = element.dataEnd;
  }
  if (!segment) return null;

  let tracks: EbmlElement | null = null;
  for (let offset = segment.dataStart; offset < segment.dataEnd;) {
    const child = await readWebmElementAt(file, offset, segment.dataEnd, budget);
    if (!child) return null;
    if (child.id === 0x1654ae6b) {
      tracks = child;
      break;
    }
    if (child.dataEnd <= offset) return null;
    offset = child.dataEnd;
  }
  if (!tracks || tracks.dataEnd - tracks.dataStart > MAX_WEBM_TRACKS_BYTES) return null;

  const bytes = await readFileRange(file, tracks.dataStart, tracks.dataEnd);
  const localTracks = { ...tracks, dataStart: 0, dataEnd: bytes.length };
  let hasAudio = false;
  let hasVideo = false;
  for (let offset = localTracks.dataStart; offset < localTracks.dataEnd;) {
    const entry = readEbmlElement(bytes, offset, localTracks.dataEnd);
    if (!entry || entry.dataEnd <= offset) return null;
    if (entry.id === 0xae) {
      const type = findEbmlChild(bytes, entry, 0x83);
      if (type && type.dataEnd > type.dataStart) {
        const trackType = bytes[type.dataStart];
        hasVideo ||= trackType === 1;
        hasAudio ||= trackType === 2;
      }
    }
    offset = entry.dataEnd;
  }
  return hasAudio || hasVideo ? { hasAudio, hasVideo } : null;
}

function hasWebmSignature(signature: Uint8Array): boolean {
  return EBML_HEADER.every((byte, index) => signature[index] === byte);
}

interface SelectedRecording {
  file: File;
  objectUrl: string;
  meetingId: string;
  idempotencyKey: string;
  durationSeconds: number | null;
}

export function SpeakerRecognitionTestScreen() {
  const [recording, setRecording] = useState<SelectedRecording | null>(null);
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "failed" | "uploaded">("idle");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  function releaseObjectUrl(objectUrl: string) {
    if (objectUrlRef.current === objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrlRef.current = null;
    }
  }

  function selectRecording(file: File | undefined) {
    if (!file) return;
    if (objectUrlRef.current) releaseObjectUrl(objectUrlRef.current);
    const objectUrl = URL.createObjectURL(file);
    objectUrlRef.current = objectUrl;
    setRecording({
      file,
      objectUrl,
      meetingId: crypto.randomUUID(),
      idempotencyKey: crypto.randomUUID(),
      durationSeconds: null,
    });
    setUploadState("idle");
    setUploadError(null);
  }

  function handleMetadata(event: React.SyntheticEvent<HTMLMediaElement>) {
    const duration = event.currentTarget.duration;
    if (recording) releaseObjectUrl(recording.objectUrl);
    if (!Number.isFinite(duration) || duration < 0) {
      setRecording((current) => current ? { ...current, durationSeconds: null } : current);
      return;
    }
    setRecording((current) => current ? { ...current, durationSeconds: Math.ceil(duration) } : current);
  }

  async function submitUpload() {
    if (!recording || recording.durationSeconds === null || uploadState === "uploading") return;
    setUploadError(null);
    setUploadState("uploading");
    try {
      const declaredVideo = recording.file.type.startsWith("video/");
      const signature = await readFileRange(recording.file, 0, Math.min(EBML_HEADER.length, recording.file.size));
      const isWebm = hasWebmSignature(signature);
      const hasMediaMimeType = recording.file.type.startsWith("audio/") || recording.file.type.startsWith("video/");
      if (!isWebm && (!hasMediaMimeType || recording.file.type.includes("webm"))) {
        throw new Error("Could not verify the recording format. Choose a valid audio or video recording and try again.");
      }
      const tracks = isWebm ? await inspectWebmTracks(recording.file, signature) : null;
      if (isWebm && !tracks) {
        throw new Error("Could not verify the WebM audio/video tracks. Choose a valid WebM recording and try again.");
      }
      if (tracks && hasMediaMimeType && (declaredVideo !== tracks.hasVideo || (!declaredVideo && !tracks.hasAudio))) {
        throw new Error(`The recording contains ${tracks.hasVideo ? "a video" : "no video"} track but its file type is declared as ${declaredVideo ? "video" : "audio"}. Choose a file whose type matches its media tracks.`);
      }
      const data: RecordingUploadData = {
        duration_seconds: recording.durationSeconds,
        meeting_id: recording.meetingId,
        idempotency_key: recording.idempotencyKey,
        capture_origin: "web_upload",
        video_presence: tracks ? (tracks.hasVideo ? "muxed" : "absent") : declaredVideo ? "muxed" : "absent",
      };
      await uploadRecording(recording.file, data);
      setUploadState("uploaded");
      releaseObjectUrl(recording.objectUrl);
    } catch (error) {
      setUploadState("failed");
      setUploadError(error instanceof Error ? error.message : "Upload failed. Check that the file type matches its audio/video tracks and try again.");
    }
  }

  return (
    <section aria-labelledby="speaker-test-heading">
      <h2 id="speaker-test-heading">Speaker recognition test</h2>
      <label>
        Recording
        <input
          type="file"
          accept="audio/*,video/*"
          onChange={(event) => selectRecording(event.currentTarget.files?.[0])}
        />
      </label>
      {recording && (recording.file.type.startsWith("video/") ? (
        <video
          src={recording.objectUrl}
          preload="metadata"
          onLoadedMetadata={handleMetadata}
          onError={() => releaseObjectUrl(recording.objectUrl)}
          aria-label="Selected recording metadata"
        />
      ) : (
        <audio
          src={recording.objectUrl}
          preload="metadata"
          onLoadedMetadata={handleMetadata}
          onError={() => releaseObjectUrl(recording.objectUrl)}
          aria-label="Selected recording metadata"
        />
      ))}
      {recording && uploadState !== "uploaded" && (
        <button type="button" onClick={submitUpload} disabled={uploadState === "uploading"}>
          {uploadState === "failed" ? "Retry upload" : uploadState === "uploading" ? "Uploading…" : "Upload"}
        </button>
      )}
      {uploadState === "failed" && <p role="status">Upload failed. You can retry.</p>}
      {uploadError && <p role="alert">{uploadError}</p>}
      {uploadState === "uploaded" && <p role="status">Upload received.</p>}
    </section>
  );
}
