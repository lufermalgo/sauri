import { useEffect, useRef, useState } from "react";
import { uploadWithProgress } from "../api";
import type { RecordingUploadData, UploadProgress } from "../api";
import { copy } from "../copy/es";

interface SelectedRecording {
  file: File;
  objectUrl: string;
  meetingId: string;
  idempotencyKey: string;
  data: RecordingUploadData | null;
}

interface UploadViewProps {
  onUploaded: (meetingId: string) => void;
  onBack: () => void;
}

export function UploadView({ onUploaded, onBack }: UploadViewProps) {
  const [recording, setRecording] = useState<SelectedRecording | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const objectUrl = recording?.objectUrl;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }, [objectUrl]);

  function selectFile(file: File | undefined) {
    setRecording(file ? {
      file,
      objectUrl: URL.createObjectURL(file),
      meetingId: crypto.randomUUID(),
      idempotencyKey: crypto.randomUUID(),
      data: null,
    } : null);
    setProgress(null);
    setError(null);
  }

  async function submitUpload() {
    if (!recording?.data || uploading) return;
    setUploading(true);
    setError(null);
    setProgress({ loaded: 0, total: null });
    try {
      await uploadWithProgress(recording.file, recording.data, (next) => {
        if (mounted.current) setProgress(next);
      });
      // The ingestion response identifies the recording, not the meeting.
      if (mounted.current) onUploaded(recording.data.meeting_id);
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : copy.upload.errors.failed);
    } finally {
      if (mounted.current) setUploading(false);
    }
  }

  const percent = progress?.total ? Math.floor(progress.loaded * 100 / progress.total) : undefined;

  return (
    <section aria-labelledby="upload-heading">
      <button type="button" onClick={onBack} disabled={uploading}>{copy.upload.back}</button>
      <h2 id="upload-heading">{copy.upload.title}</h2>
      <label>
        {copy.upload.fileLabel}
        <input
          type="file"
          accept="audio/*,video/*"
          disabled={uploading}
          onChange={(event) => selectFile(event.currentTarget.files?.[0])}
        />
      </label>
      {recording && (
        <>
          <p>{recording.file.name}</p>
          <video
            key={recording.objectUrl}
            src={recording.objectUrl}
            preload="metadata"
            hidden
            onLoadedMetadata={(event) => {
              const media = event.currentTarget;
              if (!Number.isFinite(media.duration) || media.duration <= 0) {
                setError(copy.upload.errors.invalidDuration);
                return;
              }
              setRecording({ ...recording, data: {
                duration_seconds: Math.ceil(media.duration),
                meeting_id: recording.meetingId,
                idempotency_key: recording.idempotencyKey,
                capture_origin: "web_upload",
                video_presence: media.videoWidth > 0 ? "muxed" : "absent",
              } });
              setError(null);
            }}
            onError={() => setError(copy.upload.errors.unreadableRecording)}
          />
          {!recording.data && !error && <p role="status">{copy.upload.readingMetadata}</p>}
        </>
      )}
      <button type="button" onClick={submitUpload} disabled={!recording?.data || uploading}>
        {uploading ? copy.upload.uploading : error && recording?.data ? copy.upload.retry : copy.upload.submit}
      </button>
      {progress && uploading && (
        <>
          <progress aria-label={copy.upload.progressLabel} max={100} value={percent} />
          <p role="status">
            {percent === 100
              ? copy.upload.awaitingConfirmation
              : percent === undefined ? copy.upload.bytesSent(progress.loaded) : copy.upload.percentUploaded(percent)}
          </p>
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
