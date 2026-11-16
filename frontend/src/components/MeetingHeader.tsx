import { useRef, useState } from "react";
import { deleteMeeting, renameMeeting } from "../api";
import { meeting as text } from "../copy/meeting";
import { navigate } from "../router";
import { stageLabel, type DetectedStage } from "../processing-estimate";
import { Button, ConfirmDialog, StatusBadge, TextField, Menu, MenuItem } from "./ui";
import { MeetingDownloads, type MeetingDownloadsProps } from "./MeetingDownloads";
import "../styles/meeting.css";

interface MeetingHeaderProps extends MeetingDownloadsProps {
  title: string | null;
  createdAt: string | null;
  onBack: () => void;
  /** Stage derived once by the page, the same one the processing stepper shows. */
  stage?: DetectedStage;
  processState?: string;
  speakerCount?: number;
}

export function MeetingHeader({ title, createdAt, onBack, stage, processState, speakerCount, ...downloads }: MeetingHeaderProps) {
  const duration = downloads.manifest?.duration_seconds;
  const totalSeconds = duration === undefined ? null : Math.max(0, Math.floor(duration));
  const durationLabel = totalSeconds === null ? null : totalSeconds >= 3600
    ? `${Math.floor(totalSeconds / 3600)}:${String(Math.floor(totalSeconds / 60) % 60).padStart(2, "0")}:${String(totalSeconds % 60).padStart(2, "0")}`
    : `${String(Math.floor(totalSeconds / 60)).padStart(2, "0")}:${String(totalSeconds % 60).padStart(2, "0")}`;
  const [renamedTitle, setRenamedTitle] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const currentTitle = renamedTitle ?? title ?? text.untitled;
  const validTitle = draft.trim().length > 0 && draft.trim().length <= 512;

  async function save() {
    if (!validTitle || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await renameMeeting(downloads.meetingId, draft.trim());
      setRenamedTitle(result.title);
      setEditing(false);
    } catch {
      setError(text.renameFailed);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  async function remove() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      await deleteMeeting(downloads.meetingId);
      navigate({ name: "library" });
    } catch {
      setError(text.deleteFailed);
    } finally {
      pending.current = false;
      setBusy(false);
      setConfirming(false);
    }
  }

  return <header className="meeting-header" aria-busy={busy || undefined}>
    <a className="meeting-back" href="/" onClick={event => {
      if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button === 0) {
        event.preventDefault();
        onBack();
      }
    }}>{text.back}</a>
    <div className="meeting-heading-row">
      <div className="meeting-heading">
        {editing ? <form className="meeting-rename" onSubmit={event => { event.preventDefault(); void save(); }}>
          <TextField label={text.titleLabel} value={draft} autoFocus disabled={busy}
            onChange={event => setDraft(event.target.value)} />
          <div className="meeting-actions">
            <Button variant="primary" type="submit" disabled={!validTitle || busy}>{text.save}</Button>
            <Button variant="ghost" disabled={busy} onClick={() => { setEditing(false); setError(null); }}>{text.cancel}</Button>
          </div>
        </form> : <h1>{currentTitle}</h1>}
        <div className="meeting-details">
        {stage && <StatusBadge tone={stage === "done" ? "success" : stage === "failed" ? "error" : "progress"}>
          {stageLabel(stage, processState)}
        </StatusBadge>}
        {createdAt && <time className="meeting-date" dateTime={createdAt}>
          {new Date(createdAt).toLocaleDateString("es", { day: "numeric", month: "long", year: "numeric" })}
        </time>}
        {durationLabel !== null && <span className="meeting-duration">{durationLabel}</span>}
        {speakerCount !== undefined && <span>{text.speakerCount(speakerCount)}</span>}
        </div>
      </div>
      <div className="meeting-actions">
        <MeetingDownloads {...downloads} />
        {!editing && <Button variant="secondary" disabled={busy} onClick={() => {
          setDraft(renamedTitle ?? title ?? ""); setEditing(true); setError(null);
        }}>{text.rename}</Button>}
        <Menu label={text.moreActions}>
          <MenuItem tone="danger" disabled={busy || editing}
            onSelect={() => { setConfirming(true); setError(null); }}>{text.deleteRecording}</MenuItem>
        </Menu>
      </div>
    </div>
    {busy && <p role="status">{confirming ? text.deleting : text.saving}</p>}
    {error && <p role="alert" className="meeting-error">{error}</p>}
    {confirming && <ConfirmDialog title={text.deleteTitle} body={text.deleteBody}
      confirmLabel={text.delete} cancelLabel={text.cancel} onConfirm={() => { void remove(); }}
      onCancel={() => { if (!pending.current) setConfirming(false); }} />}
  </header>;
}
