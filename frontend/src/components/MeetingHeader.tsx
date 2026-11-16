import { useEffect, useRef, useState } from "react";
import { deleteMeeting, renameMeeting } from "../api";
import { notifyLibraryChanged } from "../library-events";
import { navigate } from "../router";
import { stageLabel, type DetectedStage } from "../processing-estimate";
import { ArrowLeft, Ellipsis, Pencil, Trash2, UsersRound } from "lucide-react";
import { Button, ConfirmDialog, Icon, Popover, StatusBadge, TextField, Menu, MenuItem } from "./ui";
import { MeetingDownloads, type MeetingDownloadsProps } from "./MeetingDownloads";
import "../styles/meeting.css";
import { t, useT } from "../i18n";
import { formatDate } from "../i18n/format";

interface MeetingHeaderProps extends MeetingDownloadsProps {
  title: string | null;
  /** When Sauri received the recording. */
  createdAt: string | null;
  /** When the recording was made; this is the date shown, with `createdAt` in its tooltip. */
  recordedAt?: string | null;
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

/** "Grabada el … · Procesada el …" when the two dates differ by more than a minute; otherwise no tooltip. */
function datesTooltip(recordedAt: string | null, createdAt: string | null): string | undefined {
  if (!recordedAt || !createdAt) return undefined;
  const recorded = new Date(recordedAt);
  const processed = new Date(createdAt);
  if (Number.isNaN(recorded.getTime()) || Number.isNaN(processed.getTime())) return undefined;
  if (Math.abs(recorded.getTime() - processed.getTime()) < 60_000) return undefined;
  const style = { dateStyle: "medium", timeStyle: "short" } as const;
  return t("meeting:datesTooltip", { recorded: formatDate(recorded, style), processed: formatDate(processed, style) });
}

export function MeetingHeader({ title, createdAt, recordedAt, stage, processState, speakerCount, speakerReview, onBack, ...downloads }: MeetingHeaderProps) {
  const { t } = useT();
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
  const currentTitle = renamedTitle ?? title ?? t("meeting:untitled");
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
      setError(t("meeting:renameFailed"));
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
      setError(t("meeting:deleteFailed"));
    } finally {
      pending.current = false;
      setBusy(false);
      setConfirming(false);
    }
  }

  return <header className="meeting-header" aria-busy={busy || undefined}>
    <div className="meeting-heading-row">
      {onBack && <button type="button" className="ui-icon-button ui-icon-button--ghost meeting-back"
        aria-label={t("meeting:backToList")} onClick={onBack}><Icon icon={ArrowLeft} /></button>}
      <div className="meeting-heading">
        {editing ? <form className="meeting-rename" onSubmit={event => { event.preventDefault(); void save(); }}>
          <TextField label={t("meeting:titleLabel")} value={draft} autoFocus disabled={busy}
            onChange={event => setDraft(event.target.value)} />
          <div className="meeting-actions">
            <Button variant="primary" size="sm" type="submit" disabled={!validTitle || busy}>{t("meeting:save")}</Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => { setEditing(false); setError(null); }}>{t("meeting:cancel")}</Button>
          </div>
        </form> : <h1 title={currentTitle}>{currentTitle}</h1>}
        <div className="meeting-details">
        {stage && <StatusBadge tone={stage === "done" ? "success" : stage === "failed" ? "error" : "progress"}>
          {stageLabel(stage, processState)}
        </StatusBadge>}
        {(recordedAt ?? createdAt) && <time className="meeting-date" dateTime={recordedAt ?? createdAt ?? undefined}
          title={datesTooltip(recordedAt ?? null, createdAt)}>
          {formatDate(new Date((recordedAt ?? createdAt)!), { day: "numeric", month: "long", year: "numeric" })}
        </time>}
        {durationLabel !== null && <span className="meeting-duration">{durationLabel}</span>}
        {speakerCount !== undefined && <span>{t("meeting:speakerCount", { count: speakerCount })}</span>}
        </div>
      </div>
      <div className="meeting-actions">
        {speakerReview && <Popover className="meeting-speakers" label={speakerReview.pendingCount > 0
          ? t("meeting:speakersButtonPending", { count: speakerReview.pendingCount }) : t("meeting:speakersButton")}
          panelLabel={t("meeting:speakersPanel")} triggerClassName={`ui-icon-button ui-icon-button--ghost${
            speakerReview.pendingCount > 0 ? " ui-icon-button--alert" : ""}`}
          trigger={<Icon icon={UsersRound} />}>
          {close => <>
            <p className="meeting-speakers-message">{speakerReview.pendingCount > 0
              ? t("meeting:pendingSpeakers", { count: speakerReview.pendingCount })
              : speakerReview.hasUnnamed ? t("meeting:speakersSomeUnnamed") : t("meeting:speakersAllNamed")}</p>
            <Button variant="secondary" size="sm" onClick={() => { close(); speakerReview.onReview(); }}>
              {speakerReview.pendingCount > 0 ? t("meeting:reviewSpeakers") : t("meeting:editSpeakers")}</Button>
          </>}
        </Popover>}
        <MeetingDownloads {...downloads} title={renamedTitle ?? title} />
        <Menu label={t("meeting:moreActions")} tooltip trigger={<Icon icon={Ellipsis} />}
          triggerClassName="ui-icon-button ui-icon-button--quiet">
          {!editing && <MenuItem disabled={busy} onSelect={() => {
            setDraft(renamedTitle ?? title ?? ""); setEditing(true); setError(null);
          }}><Icon icon={Pencil} />{t("meeting:rename")}</MenuItem>}
          <MenuItem tone="danger" disabled={busy || editing}
            onSelect={() => { setConfirming(true); setError(null); }}><Icon icon={Trash2} />{t("meeting:deleteRecording")}</MenuItem>
        </Menu>
      </div>
    </div>
    {busy && <p role="status">{confirming ? t("meeting:deleting") : t("meeting:saving")}</p>}
    {error && <p role="alert" className="meeting-error">{error}</p>}
    {confirming && <ConfirmDialog title={t("meeting:deleteTitle")} body={t("meeting:deleteBody")}
      confirmLabel={t("meeting:delete")} cancelLabel={t("meeting:cancel")} onConfirm={() => { void remove(); }}
      onCancel={() => { if (!pending.current) setConfirming(false); }} />}
  </header>;
}
