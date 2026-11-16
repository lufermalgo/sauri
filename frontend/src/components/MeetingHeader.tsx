import { useEffect, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import { deleteMeeting, renameMeeting } from "../api";
import { notifyLibraryChanged } from "../library-events";
import { navigate } from "../router";
import { stageLabel, type DetectedStage } from "../processing-estimate";
import { ArrowLeft, Ellipsis, Pencil, Trash2, UsersRound } from "lucide-react";
import { Button, ConfirmDialog, Icon, Popover, StatusBadge, TextField, Menu, MenuItem, useTooltip } from "./ui";
import { MeetingDownloads, type MeetingDownloadsProps } from "./MeetingDownloads";
import "../styles/meeting.css";
import { useT } from "../i18n";
import { formatDate } from "../i18n/format";

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

const MAX_TITLE_LENGTH = 512;

export interface SpeakerReviewEntry {
  /** Speakers still waiting for a decision; the red dot shows while this is above zero. */
  pendingCount: number;
  /** Some speakers were left without a name (only meaningful with no pending ones). */
  hasUnnamed: boolean;
  onReview: () => void;
}

export function MeetingHeader({ title, createdAt, stage, processState, speakerCount, speakerReview, onBack, ...downloads }: MeetingHeaderProps) {
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
  // Set once the draft was edited or submitted, so a blank title is only flagged after the person acted.
  const [touched, setTouched] = useState(false);
  // Screen-reader confirmation of a saved rename; the page already shows the new title.
  const [notice, setNotice] = useState("");
  const startTitle = useRef("");
  const form = useRef<HTMLFormElement>(null);
  const pencil = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  const pencilTip = useTooltip(t("meeting:renameTitle"));
  // A newer title from outside (renamed in the library list) replaces the one saved here.
  useEffect(() => setRenamedTitle(null), [title]);
  const currentTitle = renamedTitle ?? title ?? t("meeting:untitled");
  const blank = draft.trim().length === 0;
  const validTitle = !blank && draft.trim().length <= MAX_TITLE_LENGTH;

  // The input takes the title's place focused and selected; closing it hands the focus back to the pencil.
  useEffect(() => {
    if (editing) {
      const input = form.current?.querySelector("input");
      input?.focus();
      input?.select();
    } else if (returnFocus.current) {
      returnFocus.current = false;
      pencil.current?.focus();
    }
  }, [editing]);

  function startEditing() {
    startTitle.current = renamedTitle ?? title ?? "";
    setDraft(startTitle.current);
    setTouched(false);
    setNotice("");
    setError(null);
    setEditing(true);
  }

  function stopEditing() {
    returnFocus.current = true;
    setEditing(false);
    setTouched(false);
    setError(null);
  }

  async function save() {
    if (pending.current) return;
    if (!validTitle) { setTouched(true); return; }
    // Nothing changed: no request, just close.
    if (draft.trim() === startTitle.current.trim()) { stopEditing(); return; }
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await renameMeeting(downloads.meetingId, draft.trim());
      setRenamedTitle(result.title);
      setNotice(t("meeting:renamed"));
      stopEditing();
      notifyLibraryChanged();
    } catch {
      setError(t("meeting:renameFailed"));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  // Escape closes the editor (never while saving); Enter submits through the form.
  function onRenameKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key !== "Escape" || busy) return;
    event.preventDefault();
    event.stopPropagation();
    stopEditing();
  }

  // Leaving the field with nothing changed closes it; a changed draft stays open so no typing is lost
  // (the same rule as renaming from the library list). Moving to Save or Cancel is not leaving.
  function onRenameBlur(event: FocusEvent<HTMLFormElement>) {
    if (busy || form.current?.contains(event.relatedTarget as Node | null)) return;
    if (draft === startTitle.current) stopEditing();
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
        {editing ? <form ref={form} className="meeting-rename" onSubmit={event => { event.preventDefault(); void save(); }}
          onKeyDown={onRenameKeyDown} onBlur={onRenameBlur}>
          <TextField label={t("meeting:titleLabel")} value={draft} disabled={busy} maxLength={MAX_TITLE_LENGTH}
            autoComplete="off" error={touched && blank ? t("meeting:titleRequired") : undefined}
            onChange={event => { setDraft(event.target.value); setTouched(true); }} />
          <div className="meeting-actions">
            <Button variant="primary" size="sm" type="submit" disabled={busy}>{t("meeting:save")}</Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={stopEditing}>{t("meeting:cancel")}</Button>
          </div>
        </form> : <div className="meeting-title-row">
          <h1 title={currentTitle}>{currentTitle}</h1>
          <span className="meeting-title-edit">
            <button type="button" ref={pencil} className="ui-icon-button ui-icon-button--ghost"
              aria-label={t("meeting:renameTitle")} disabled={busy} {...pencilTip.triggerProps}
              onClick={() => { pencilTip.hide(); startEditing(); }}><Icon icon={Pencil} size={16} /></button>
            {pencilTip.tooltip}
          </span>
        </div>}
        <div className="meeting-details">
        {stage && <StatusBadge tone={stage === "done" ? "success" : stage === "failed" ? "error" : "progress"}>
          {stageLabel(stage, processState)}
        </StatusBadge>}
        {createdAt && <time className="meeting-date" dateTime={createdAt}>
          {formatDate(new Date(createdAt), { day: "numeric", month: "long", year: "numeric" })}
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
          {!editing && <MenuItem disabled={busy} onSelect={startEditing}><Icon icon={Pencil} />{t("meeting:rename")}</MenuItem>}
          <MenuItem tone="danger" disabled={busy || editing}
            onSelect={() => { setConfirming(true); setError(null); }}><Icon icon={Trash2} />{t("meeting:deleteRecording")}</MenuItem>
        </Menu>
      </div>
    </div>
    <p role="status" className="meeting-sr-only">{notice}</p>
    {busy && <p role="status">{confirming ? t("meeting:deleting") : t("meeting:saving")}</p>}
    {error && <p role="alert" className="meeting-error">{error}</p>}
    {confirming && <ConfirmDialog title={t("meeting:deleteTitle")} body={t("meeting:deleteBody")}
      confirmLabel={t("meeting:delete")} cancelLabel={t("meeting:cancel")} onConfirm={() => { void remove(); }}
      onCancel={() => { if (!pending.current) setConfirming(false); }} />}
  </header>;
}
