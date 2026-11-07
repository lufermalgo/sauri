import { useEffect, useRef, useState } from "react";
import { getMeeting, getSpeakerReview, getTranscript, uploadRecording } from "../api";
import type { MeetingTranscript, RecordingUploadData, SpeakerReview } from "../api";

interface EbmlElement {
  id: number;
  dataStart: number;
  dataEnd: number;
}

const MAX_WEBM_TRACKS_BYTES = 64 * 1024;
const MAX_WEBM_ELEMENT_READS = 256;
const EBML_HEADER = [0x1a, 0x45, 0xdf, 0xa3];
const PROCESSING_POLL_INTERVAL_MS = 2000;

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

function formatTimestamp(milliseconds: number): string {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
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
  const [meetingProcessState, setMeetingProcessState] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<MeetingTranscript | null>(null);
  const [speakerReview, setSpeakerReview] = useState<SpeakerReview | null>(null);
  const [diagnostic, setDiagnostic] = useState({
    validation: "not checked",
    request: "not sent",
    httpStatus: "not available",
    error: "none",
  });
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  const selectedMeetingId = recording?.meetingId;

  useEffect(() => {
    if (uploadState !== "uploaded" || !selectedMeetingId) return;
    const meetingId = selectedMeetingId;

    let active = true;
    let timeout: number | undefined;

    async function observeProcessing() {
      try {
        const meeting = await getMeeting(meetingId);
        if (!active) return;
        setMeetingProcessState(meeting.processState);

        if (meeting.processState === "completed") {
          const [completedTranscript, completedReview] = await Promise.all([
            getTranscript(meetingId),
            getSpeakerReview(meetingId),
          ]);
          if (active) {
            setTranscript(completedTranscript);
            setSpeakerReview(completedReview);
          }
          return;
        }

        if (meeting.processState !== "failed") {
          timeout = window.setTimeout(observeProcessing, PROCESSING_POLL_INTERVAL_MS);
        }
      } catch {
        if (active) timeout = window.setTimeout(observeProcessing, PROCESSING_POLL_INTERVAL_MS);
      }
    }

    void observeProcessing();
    return () => {
      active = false;
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [selectedMeetingId, uploadState]);

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
    setMeetingProcessState(null);
    setTranscript(null);
    setSpeakerReview(null);
    setDiagnostic({
      validation: "not checked",
      request: "not sent",
      httpStatus: "not available",
      error: "none",
    });
    setCopyStatus(null);
  }

  function handleMetadata(event: React.SyntheticEvent<HTMLMediaElement>) {
    const duration = event.currentTarget.duration;
    if (recording) releaseObjectUrl(recording.objectUrl);
    if (!Number.isFinite(duration) || duration < 0) {
      setRecording((current) => current ? { ...current, durationSeconds: null } : current);
      setDiagnostic((current) => ({ ...current, validation: "duration unavailable" }));
      return;
    }
    setRecording((current) => current ? { ...current, durationSeconds: Math.ceil(duration) } : current);
    setDiagnostic((current) => ({ ...current, validation: "passed" }));
  }

  async function submitUpload() {
    if (!recording || uploadState === "uploading") return;
    if (recording.durationSeconds === null) {
      const message = "Upload blocked: recording duration is unavailable. Wait for media metadata to load or choose another file.";
      setUploadError(message);
      setDiagnostic({
        validation: "duration unavailable",
        request: "not sent",
        httpStatus: "not available",
        error: "duration unavailable",
      });
      return;
    }
    setUploadError(null);
    setDiagnostic({ validation: "passed", request: "in progress", httpStatus: "not available", error: "none" });
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
      setDiagnostic({ validation: "passed", request: "accepted", httpStatus: "success", error: "none" });
      releaseObjectUrl(recording.objectUrl);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Upload failed. Check that the file type matches its audio/video tracks and try again.";
      const statusMatch = errorMessage.match(/^Error (\d{3})$/);
      setUploadState("failed");
      setUploadError(errorMessage);
      const validationFailed = errorMessage.startsWith("Could not verify") || errorMessage.startsWith("The recording contains");
      setDiagnostic({
        validation: validationFailed ? "failed" : "passed",
        request: statusMatch ? "failed" : "failed or not sent",
        httpStatus: statusMatch?.[1] ?? "not available",
        error: statusMatch ? "HTTP error" : "upload or validation error",
      });
    }
  }

  async function copyDiagnostic() {
    if (!recording) return;
    const report = {
      file: { name: recording.file.name, type: recording.file.type, sizeBytes: recording.file.size },
      validation: diagnostic.validation,
      request: diagnostic.request,
      httpStatus: diagnostic.httpStatus,
      error: diagnostic.error,
    };
    try {
      await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
      setCopyStatus("Diagnostic copied.");
    } catch {
      setCopyStatus("Could not copy diagnostic. Check clipboard permissions.");
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
      {recording && <button type="button" onClick={copyDiagnostic}>Copy diagnostic</button>}
      {copyStatus && <p role="status">{copyStatus}</p>}
      {recording && uploadState !== "uploaded" && (
        <button type="button" onClick={submitUpload} disabled={uploadState === "uploading"}>
          {uploadState === "failed" ? "Retry upload" : uploadState === "uploading" ? "Uploading…" : "Upload"}
        </button>
      )}
      {uploadState === "failed" && <p role="status">Upload failed. You can retry.</p>}
      {uploadError && <p role="alert">{uploadError}</p>}
      {uploadState === "uploaded" && !transcript && (
        <p role="status">
          {meetingProcessState === "failed"
            ? "Processing failed."
            : `Processing${meetingProcessState ? `: ${meetingProcessState}` : "…"}`}
        </p>
      )}
      {transcript && speakerReview && (
        <>
          <section aria-labelledby="test-transcript-heading">
            <h3 id="test-transcript-heading">Transcript</h3>
            <ol>
              {transcript.segments.map((segment) => (
                <li key={segment.id}>
                  {segment.startMs !== null && <time>{formatTimestamp(segment.startMs)}</time>}
                  {segment.speakerLabel && <strong>{segment.speakerLabel}</strong>}
                  <p>{segment.text}</p>
                </li>
              ))}
            </ol>
          </section>
          <section aria-labelledby="test-speaker-review-heading">
            <h3 id="test-speaker-review-heading">Speaker review</h3>
            <p>{speakerReview.status === "complete" ? "Review complete" : "Review pending"}</p>
            <ul>
              {speakerReview.items.map((item) => <li key={item.speakerId}>{item.currentLabel}</li>)}
            </ul>
          </section>
        </>
      )}
    </section>
  );
}
