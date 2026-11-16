import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { deleteMeeting, renameMeeting } from "../api";
import { notifyLibraryChanged } from "../library-events";
import { navigate } from "../router";
import { stageLabel, type DetectedStage } from "../processing-estimate";
import { ArrowLeft, Pencil, Trash2, UsersRound } from "lucide-react";
import { ConfirmDialog, Icon, StatusBadge, useTooltip } from "./ui";
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

const MAX_TITLE_LENGTH = 512;
/** How long the floating rename message stays up. */
const HINT_MS = 5000;

export interface SpeakerReviewEntry {
  /** Speakers still waiting for a decision; the red dot shows while this is above zero. */
  pendingCount: number;
  /** Whether the speakers panel beside the video is open. */
  open: boolean;
  /** Opens or closes that panel: the icon is its toggle, with no step in between. */
  onToggle: () => void;
}

/** `id` of the speakers panel, the target of the icon's `aria-controls`. */
export const SPEAKER_DOCK_ID = "meeting-speakers-dock";

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
  // Quiet, floating message about a rename that did not go through (blank name, failed request).
  const [hint, setHint] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  // Screen-reader confirmation of a saved rename; the page already shows the new title.
  const [notice, setNotice] = useState("");
  const startTitle = useRef("");
  // True while the field is open and nobody has decided yet, so Enter followed by blur cannot save twice.
  const open = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  const pencil = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  const pencilTip = useTooltip(t("meeting:renameTitle"));
  const speakersLabel = speakerReview && speakerReview.pendingCount > 0
    ? t("meeting:speakersButtonPending", { count: speakerReview.pendingCount }) : t("meeting:speakersButton");
  const speakersTip = useTooltip(speakerReview ? speakersLabel : "");
  const deleteTip = useTooltip(t("meeting:deleteRecording"));
  // A newer title from outside (renamed in the library list) replaces the one saved here.
  useEffect(() => setRenamedTitle(null), [title]);
  useEffect(() => {
    if (!hint) return;
    const timer = window.setTimeout(() => setHint(null), HINT_MS);
    return () => window.clearTimeout(timer);
  }, [hint]);
  const currentTitle = renamedTitle ?? title ?? t("meeting:untitled");

  // The field takes the title's place focused and selected; closing it with the keyboard hands the focus
  // back to the pencil (a click elsewhere keeps the focus where the person put it).
  useEffect(() => {
    if (editing) {
      const field = input.current;
      if (!field) return;
      field.focus();
      field.select();
      // Selecting scrolls to the end of a long title; the person expects to see its start, as before.
      field.scrollLeft = 0;
    } else if (returnFocus.current) {
      returnFocus.current = false;
      pencil.current?.focus();
    }
  }, [editing]);

  function startEditing() {
    if (open.current || pending.current) return;
    startTitle.current = renamedTitle ?? title ?? "";
    setDraft(startTitle.current);
    setNotice("");
    setHint(null);
    setError(null);
    open.current = true;
    setEditing(true);
  }

  function stopEditing(keyboard: boolean) {
    open.current = false;
    returnFocus.current = keyboard;
    setEditing(false);
  }

  // Saves a changed, non-blank name. A blank or unchanged one closes the field on the old title.
  async function commit(keyboard: boolean) {
    if (!open.current || pending.current) return;
    const next = draft.trim();
    if (next === startTitle.current.trim()) { stopEditing(keyboard); return; }
    if (next.length === 0) {
      stopEditing(keyboard);
      setHint({ tone: "info", text: t("meeting:titleRequired") });
      return;
    }
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await renameMeeting(downloads.meetingId, next);
      setRenamedTitle(result.title);
      setNotice(t("meeting:renamed"));
      notifyLibraryChanged();
    } catch {
      setHint({ tone: "error", text: t("meeting:renameFailed") });
    } finally {
      pending.current = false;
      setBusy(false);
      stopEditing(keyboard);
    }
  }

  // Enter saves, Escape reverts; neither reaches the shortcuts outside the header.
  function onTitleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (busy || event.nativeEvent.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      void commit(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      stopEditing(true);
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
        <div className={`meeting-title-row${editing ? " meeting-title-row--editing" : ""}`}>
          <h1 title={currentTitle} onDoubleClick={startEditing}>
            {editing ? <span className="meeting-title-field" data-value={draft || currentTitle}>
              <input ref={input} value={draft} maxLength={MAX_TITLE_LENGTH} readOnly={busy} autoComplete="off"
                spellCheck={false} placeholder={t("meeting:untitled")} aria-label={t("meeting:titleLabel")} aria-busy={busy || undefined}
                onChange={event => setDraft(event.target.value)} onKeyDown={onTitleKeyDown}
                onBlur={() => { void commit(false); }} />
            </span> : currentTitle}
          </h1>
          <span className="meeting-title-edit" aria-hidden={editing || undefined}>
            <button type="button" ref={pencil} className="ui-icon-button ui-icon-button--ghost"
              aria-label={t("meeting:renameTitle")} disabled={editing} {...pencilTip.triggerProps}
              onClick={() => { pencilTip.hide(); startEditing(); }}><Icon icon={Pencil} size={16} /></button>
            {pencilTip.tooltip}
          </span>
          <span className="meeting-actions-divider" aria-hidden="true" />
          <div className="meeting-actions">
            {speakerReview && <span className="meeting-speakers">
              <button type="button" className={`ui-icon-button ui-icon-button--ghost${speakerReview.pendingCount > 0 ? " ui-icon-button--alert" : ""}`}
                aria-label={speakersLabel} aria-expanded={speakerReview.open} aria-controls={speakerReview.open ? SPEAKER_DOCK_ID : undefined}
                {...speakersTip.triggerProps} onClick={() => { speakersTip.hide(); speakerReview.onToggle(); }}>
                <Icon icon={UsersRound} />
              </button>
              {speakersTip.tooltip}
            </span>}
            <MeetingDownloads {...downloads} title={renamedTitle ?? title} />
            <span className="meeting-delete">
              <button type="button" className="ui-icon-button ui-icon-button--ghost ui-icon-button--danger"
                aria-label={t("meeting:deleteRecording")} disabled={busy || editing} {...deleteTip.triggerProps}
                onClick={() => { deleteTip.hide(); setConfirming(true); setError(null); }}>
                <Icon icon={Trash2} />
              </button>
              {deleteTip.tooltip}
            </span>
          </div>
        </div>
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
    </div>
    <p role="status" className="meeting-sr-only">{notice}</p>
    {busy && <p role="status" className={confirming ? undefined : "meeting-sr-only"}>
      {confirming ? t("meeting:deleting") : t("meeting:saving")}</p>}
    {error && <p role="alert" className="meeting-error">{error}</p>}
    {hint && <p role={hint.tone === "error" ? "alert" : "status"}
      className={`meeting-title-hint meeting-title-hint--${hint.tone}`}>{hint.text}</p>}
    {confirming && <ConfirmDialog title={t("meeting:deleteTitle")} body={t("meeting:deleteBody")}
      confirmLabel={t("meeting:delete")} cancelLabel={t("meeting:cancel")} onConfirm={() => { void remove(); }}
      onCancel={() => { if (!pending.current) setConfirming(false); }} />}
  </header>;
}
