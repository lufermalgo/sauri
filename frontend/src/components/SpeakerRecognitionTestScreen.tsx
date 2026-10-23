import { useEffect, useRef, useState } from "react";
import { uploadRecording } from "../api";
import type { RecordingUploadData } from "../api";

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
    const data: RecordingUploadData = {
      duration_seconds: recording.durationSeconds,
      meeting_id: recording.meetingId,
      idempotency_key: recording.idempotencyKey,
      capture_origin: "web_upload",
      video_presence: recording.file.type.startsWith("video/") ? "muxed" : "absent",
    };
    setUploadState("uploading");
    try {
      await uploadRecording(recording.file, data);
      setUploadState("uploaded");
      releaseObjectUrl(recording.objectUrl);
    } catch {
      setUploadState("failed");
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
      {uploadState === "uploaded" && <p role="status">Upload received.</p>}
    </section>
  );
}
