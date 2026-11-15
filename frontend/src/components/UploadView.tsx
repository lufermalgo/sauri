import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { uploadWithProgress } from "../api";
import type { RecordingUploadData, UploadProgress } from "../api";
import { copy } from "../copy/es";
import { Button, Card, ProgressBar } from "./ui";
import "../styles/upload.css";

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

function UploadIcon() {
  return (
    <svg className="upload-icon" viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor"
      strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M12 16V5" />
      <path d="m7 10 5-5 5 5" />
      <path d="M5 19h14" />
    </svg>
  );
}

export function UploadView({ onUploaded, onBack }: UploadViewProps) {
  const [recording, setRecording] = useState<SelectedRecording | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
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

  // Single entry point for both the file input and drag-and-drop.
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

  function handleDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    if (!uploading) setDragging(true);
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragging(false);
    if (uploading) return;
    selectFile(event.dataTransfer.files[0]);
  }

  async function submitUpload() {
    if (!recording?.data || uploading) return;
    setUploading(true);
    setError(null);
    setProgress({ loaded: 0, total: null });
    try {
      const result = await uploadWithProgress(recording.file, recording.data, (next) => {
        if (mounted.current) setProgress(next);
      });
      // The server confirms which meeting was created; trust it over the local id.
      if (mounted.current) onUploaded(result.meeting_id);
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : copy.upload.errors.failed);
    } finally {
      if (mounted.current) setUploading(false);
    }
  }

  const percent = progress?.total ? Math.floor(progress.loaded * 100 / progress.total) : undefined;
  const canRetry = Boolean(error && recording?.data && !uploading);

  return (
    <section className="upload-view" aria-labelledby="upload-heading">
      <header className="upload-header">
        <Button variant="ghost" className="upload-back" onClick={onBack} disabled={uploading}>
          {`← ${copy.upload.back}`}
        </Button>
        <h1 id="upload-heading" className="upload-title">{copy.upload.heading}</h1>
        <p className="upload-intro">{copy.upload.intro}</p>
      </header>

      <Card
        className={`upload-dropzone${dragging ? " upload-dropzone--active" : ""}`}
        onDragOver={handleDragOver}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        data-testid="upload-dropzone"
      >
        <span className="upload-dropzone-icon"><UploadIcon /></span>
        <p className="upload-dropzone-title">{copy.upload.dropTitle}</p>
        <p className="upload-dropzone-hint">{copy.upload.dropHint}</p>
        <label className="ui-button ui-button--primary upload-pick">
          {copy.upload.fileLabel}
          <input
            className="upload-file-input"
            type="file"
            accept="audio/*,video/*"
            disabled={uploading}
            onChange={(event) => selectFile(event.currentTarget.files?.[0])}
          />
        </label>
      </Card>

      {recording && (
        <Card className="upload-selected" aria-label={copy.upload.selectedFileHeading}>
          <div className="upload-file">
            <p className="upload-file-name">{recording.file.name}</p>
            <p className="upload-file-size">{copy.upload.sizeMb(recording.file.size)}</p>
          </div>
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
                title: recording.file.name,
              } });
              setError(null);
            }}
            onError={() => setError(copy.upload.errors.unreadableRecording)}
          />
          {!recording.data && !error && <p role="status" className="upload-note">{copy.upload.readingMetadata}</p>}
          <div className="upload-actions">
            <Button variant="ghost" onClick={() => selectFile(undefined)} disabled={uploading}>
              {copy.upload.remove}
            </Button>
            {!canRetry && (
              <Button variant="primary" onClick={submitUpload} disabled={!recording.data || uploading}>
                {uploading ? copy.upload.uploading : copy.upload.submit}
              </Button>
            )}
          </div>
        </Card>
      )}

      {progress && uploading && (
        <Card className="upload-progress">
          <ProgressBar label={copy.upload.progressLabel} max={100} value={percent} />
          <p role="status" className="upload-note">
            {percent === 100
              ? copy.upload.awaitingConfirmation
              : percent === undefined ? copy.upload.bytesSent(progress.loaded) : copy.upload.percentUploaded(percent)}
          </p>
        </Card>
      )}

      {error && (
        <Card className="upload-error" role="alert">
          <p className="upload-error-title">{copy.upload.errorHeading}</p>
          <p className="upload-error-message">{error}</p>
          {canRetry && <Button variant="primary" onClick={submitUpload}>{copy.upload.retry}</Button>}
        </Card>
      )}
    </section>
  );
}
