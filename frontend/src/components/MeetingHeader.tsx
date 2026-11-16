import { useEffect, useRef, useState } from "react";
import { deleteMeeting, renameMeeting } from "../api";
import { notifyLibraryChanged } from "../library-events";
import { meeting as text } from "../copy/meeting";
import { navigate } from "../router";
import { stageLabel, type DetectedStage } from "../processing-estimate";
import { ArrowLeft, Ellipsis, Pencil, Trash2, UsersRound } from "lucide-react";
import { Button, ConfirmDialog, Icon, Popover, StatusBadge, TextField, Menu, MenuItem } from "./ui";
import { MeetingDownloads, type MeetingDownloadsProps } from "./MeetingDownloads";
import "../styles/meeting.css";

interface MeetingHeaderProps extends MeetingDownloadsProps {
  title: string | null;
  createdAt: string | null;
  /** Stage derived once by the page, the same one the processing stepper shows. */
  stage?: DetectedStage;
  processState?: string;
  speakerCount?: number;
  /** Speaker-review entry point; omit it while there is no review to open. */
  speakerReview?: SpeakerReviewEntry;
  /** Back to the list; given only when the list is not shown beside this header (narrow screens). */
  onBack?: () => void;
}

export interface SpeakerReviewEntry {
  /** Speakers still waiting for a decision; the red dot shows while this is above zero. */
  pendingCount: number;
  /** Some speakers were left without a name (only meaningful with no pending ones). */
  hasUnnamed: boolean;
  onReview: () => void;
}

export function MeetingHeader({ title, createdAt, stage, processState, speakerCount, speakerReview, onBack, ...downloads }: MeetingHeaderProps) {
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
  // A newer title from outside (renamed in the library list) replaces the one saved here.
  useEffect(() => setRenamedTitle(null), [title]);
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
      notifyLibraryChanged();
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
      notifyLibraryChanged();
    } catch {
      setError(text.deleteFailed);
    } finally {
      pending.current = false;
      setBusy(false);
      setConfirming(false);
    }
  }

  return <header className="meeting-header" aria-busy={busy || undefined}>
    <div className="meeting-heading-row">
      {onBack && <button type="button" className="ui-icon-button ui-icon-button--ghost meeting-back"
        aria-label={text.backToList} onClick={onBack}><Icon icon={ArrowLeft} /></button>}
      <div className="meeting-heading">
        {editing ? <form className="meeting-rename" onSubmit={event => { event.preventDefault(); void save(); }}>
          <TextField label={text.titleLabel} value={draft} autoFocus disabled={busy}
            onChange={event => setDraft(event.target.value)} />
          <div className="meeting-actions">
            <Button variant="primary" size="sm" type="submit" disabled={!validTitle || busy}>{text.save}</Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => { setEditing(false); setError(null); }}>{text.cancel}</Button>
          </div>
        </form> : <h1 title={currentTitle}>{currentTitle}</h1>}
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
        {speakerReview && <Popover className="meeting-speakers" label={text.speakersButton(speakerReview.pendingCount)}
          panelLabel={text.speakersPanel} triggerClassName={`ui-icon-button ui-icon-button--ghost${
            speakerReview.pendingCount > 0 ? " ui-icon-button--alert" : ""}`}
          trigger={<Icon icon={UsersRound} />}>
          {close => <>
            <p className="meeting-speakers-message">{speakerReview.pendingCount > 0
              ? text.pendingSpeakers(speakerReview.pendingCount)
              : speakerReview.hasUnnamed ? text.speakersSomeUnnamed : text.speakersAllNamed}</p>
            <Button variant="secondary" size="sm" onClick={() => { close(); speakerReview.onReview(); }}>
              {speakerReview.pendingCount > 0 ? text.reviewSpeakers : text.editSpeakers}</Button>
          </>}
        </Popover>}
        <MeetingDownloads {...downloads} title={renamedTitle ?? title} />
        <Menu label={text.moreActions} tooltip trigger={<Icon icon={Ellipsis} />}
          triggerClassName="ui-icon-button ui-icon-button--quiet">
          {!editing && <MenuItem disabled={busy} onSelect={() => {
            setDraft(renamedTitle ?? title ?? ""); setEditing(true); setError(null);
          }}><Icon icon={Pencil} />{text.rename}</MenuItem>}
          <MenuItem tone="danger" disabled={busy || editing}
            onSelect={() => { setConfirming(true); setError(null); }}><Icon icon={Trash2} />{text.deleteRecording}</MenuItem>
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
