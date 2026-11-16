import { useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, MouseEvent } from "react";
import { AudioLines, Ellipsis, FileText, Pencil, ScrollText, Trash2, Video } from "lucide-react";
import { ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { meetingDate, type LibraryDateField } from "../library-query";
import { NO_SPEECH_CAUSE, estimateProgress, secondsSince } from "../processing-estimate";
import { Icon, Menu, MenuItem, MenuSeparator, ProgressBar, StatusBadge, useTooltip } from "./ui";
import { t, useT } from "../i18n";
import { formatDate } from "../i18n/format";

/** Hover or keyboard focus on a row waits this long before its summary tooltip appears. */
const SUMMARY_TOOLTIP_DELAY_MS = 500;

type BadgeTone = "neutral" | "progress" | "success" | "error";

const STATE_LABEL_KEYS = {
  [ProcessState.Queued]: "library:states.queued",
  [ProcessState.Joining]: "library:states.joining",
  [ProcessState.Recording]: "library:states.recording",
  [ProcessState.Transcribing]: "library:states.transcribing",
  [ProcessState.Completed]: "library:states.completed",
  [ProcessState.Failed]: "library:states.failed",
} as const;

const STATE_TONES: Record<ProcessState, BadgeTone> = {
  [ProcessState.Queued]: "neutral",
  [ProcessState.Joining]: "progress",
  [ProcessState.Recording]: "progress",
  [ProcessState.Transcribing]: "progress",
  [ProcessState.Completed]: "success",
  [ProcessState.Failed]: "error",
};

const ROW_EDGES: Record<BadgeTone, string> = {
  success: "ready",
  progress: "progress",
  error: "failed",
  neutral: "queued",
};

const THUMBNAIL_ICON_SIZE = 16;
const MAX_TITLE_LENGTH = 512;

function formatListDate(isoDate: string | null): string {
  if (!isoDate) return t("library:noDate");
  const date = new Date(isoDate);
  return Number.isNaN(date.getTime()) ? t("library:noDate") : formatDate(date, { dateStyle: "medium", timeStyle: "short" });
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** `mm:ss`, or `h:mm:ss` from one hour on. */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${pad(minutes)}:${pad(rest)}`;
}

/** A recording whose transcript can be downloaded. */
export function isReady(meeting: MeetingListItem): boolean {
  return meeting.processState === ProcessState.Completed;
}

/** A recording whose summary can be downloaded: the list reports its topic only once a summary exists. */
export function hasSummary(meeting: MeetingListItem): boolean {
  return isReady(meeting) && meeting.summaryTopic !== null;
}

export type RowDownloadKind = "transcript" | "summary" | "media";

/** Compact estimate for rows in transcription; nothing when there is no honest estimate. */
function RowProgress({ meeting }: { meeting: MeetingListItem }) {
  const { t } = useT();
  if (meeting.processState !== ProcessState.Queued && meeting.processState !== ProcessState.Transcribing) return null;
  const elapsed = secondsSince(meeting.createdAt, Date.now());
  if (elapsed === null) return null;
  const estimate = estimateProgress({
    stage: "transcription", audioSeconds: meeting.durationSeconds, elapsedSinceUploadSeconds: elapsed,
  });
  if (!estimate) return null;
  const stage = t("processing:steps.transcription");
  const label = estimate.overtime ? t("processing:libraryOvertime", { stage }) : t("processing:libraryProgress", { stage, percent: estimate.percent });
  return (
    <span className="processing-compact library-item-progress">
      <ProgressBar label={t("processing:libraryProgressLabel")} value={estimate.percent} valueText={label} />
      <span>{label}</span>
    </span>
  );
}

/**
 * Preview frame of the recording. The image is decorative (the title sits next to it), and the
 * generic tile replaces it when there is no frame or the signed link no longer loads.
 */
function RowThumbnail({ meeting }: { meeting: MeetingListItem }) {
  const url = meeting.thumbnailUrl;
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = url !== null && url !== failedUrl;
  return (
    <span className="library-item-thumb">
      {showImage ? (
        <img src={url} alt="" loading="lazy" decoding="async" onError={() => setFailedUrl(url)} />
      ) : (
        <Icon icon={meeting.mediaKind === "audio" ? AudioLines : Video} size={THUMBNAIL_ICON_SIZE} />
      )}
    </span>
  );
}

/** Inline rename: the input takes the title's place. Enter saves, Escape cancels, a failure stays in the row. */
function RowRename({ meeting, onSubmit, onCancel }: {
  meeting: MeetingListItem;
  onSubmit: (title: string) => Promise<void>;
  onCancel: () => void;
}) {
  const { t } = useT();
  const initial = meeting.title;
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const errorId = useId();
  const trimmed = draft.trim();
  const valid = trimmed.length > 0 && trimmed.length <= MAX_TITLE_LENGTH;

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);

  async function save() {
    if (busy || !valid) return;
    if (trimmed === initial.trim()) { onCancel(); return; }
    setBusy(true);
    setFailed(false);
    try {
      await onSubmit(trimmed);
    } catch {
      setFailed(true);
      setBusy(false);
      input.current?.focus();
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Escape") return;
    // Handled here: it must not also clear the selection or close something around the row.
    event.preventDefault();
    if (!busy) onCancel();
  };

  return (
    <form className="library-rename" aria-busy={busy || undefined}
      onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <input ref={input} type="text" className="library-rename-input" aria-label={t("library:row.renameLabel")}
        value={draft} disabled={busy} maxLength={MAX_TITLE_LENGTH} autoComplete="off"
        aria-invalid={failed || !valid ? true : undefined} aria-describedby={failed ? errorId : undefined}
        onChange={(event) => { setDraft(event.target.value); setFailed(false); }}
        onKeyDown={onKeyDown}
        onBlur={() => { if (!busy && draft === initial) onCancel(); }} />
      {failed && <p id={errorId} role="alert" className="library-rename-error">{t("library:row.renameFailed")}</p>}
    </form>
  );
}

export interface LibraryRowProps {
  meeting: MeetingListItem;
  /** Which date the meta line shows: when it was recorded (default) or when Sauri processed it. */
  dateField?: LibraryDateField;
  /** The recording open in the detail pane. */
  open: boolean;
  /** Part of the bulk selection. */
  checked: boolean;
  /** Only one row at a time is in the tab order; arrow keys move between rows. */
  tabbable: boolean;
  renaming: boolean;
  /** Last failed action on this row (download, delete). */
  error: string | null;
  /** Progress or outcome of a download in flight, shown under the row. */
  notice: string | null;
  onOpen: (meeting: MeetingListItem, modifiers: { range: boolean; toggle: boolean }) => void;
  onToggleChecked: (id: string, range: boolean) => void;
  onFocusRow: (id: string) => void;
  onStartRename: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onCancelRename: () => void;
  onDownload: (meeting: MeetingListItem, kind: RowDownloadKind) => void;
  onDelete: (meeting: MeetingListItem) => void;
}

/** One recording: title line, meta line and status chip; selection checkbox and actions menu beside it. */
export function LibraryRow({
  meeting, dateField = "recorded", open, checked, tabbable, renaming, error, notice, onOpen, onToggleChecked, onFocusRow,
  onStartRename, onRename, onCancelRename, onDownload, onDelete,
}: LibraryRowProps) {
  const { t } = useT();
  const tone = STATE_TONES[meeting.processState];
  const title = meeting.title.trim() || t("library:untitled");
  const topic = meeting.summaryTopic?.trim() || undefined;
  // A failed row keeps its cause out of the row's lines but not out of reach: it leads the tooltip.
  const cause = meeting.processState !== ProcessState.Failed ? undefined
    : meeting.failureCause === NO_SPEECH_CAUSE ? t("library:noSpeechCause") : t("library:failedCause");
  const tooltipText = [cause, topic].filter(Boolean).join(" ") || undefined;
  // The API may omit these fields for older recordings.
  const duration = typeof meeting.durationSeconds === "number" ? meeting.durationSeconds : null;
  const speakers = typeof meeting.speakerCount === "number" && meeting.speakerCount > 0
    ? meeting.speakerCount
    : null;
  const ready = isReady(meeting);
  const summaryReady = hasSummary(meeting);
  const audioOnly = meeting.mediaKind === "audio";

  const item = useRef<HTMLLIElement>(null);
  const openButton = useRef<HTMLButtonElement>(null);
  const [placement, setPlacement] = useState<CSSProperties>();
  // The row's scroll pane would clip a tooltip drawn inside it, so it is fixed to the window,
  // below the row or above it when there is no room.
  const tip = useTooltip(tooltipText, {
    delayMs: SUMMARY_TOOLTIP_DELAY_MS,
    className: "ui-tooltip--wrap library-row-tip",
    style: placement,
    onShow: () => {
      const rect = item.current?.getBoundingClientRect();
      if (!rect) return;
      const below = window.innerHeight - rect.bottom;
      setPlacement({
        position: "fixed", right: "auto", left: rect.left + 12,
        ...(below < 160 ? { top: "auto", bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
      });
    },
  });

  // After rename ends, the keyboard returns to the row.
  const wasRenaming = useRef(false);
  useEffect(() => {
    if (wasRenaming.current && !renaming) openButton.current?.focus();
    wasRenaming.current = renaming;
  }, [renaming]);

  const onClick = (event: MouseEvent<HTMLButtonElement>) => {
    onOpen(meeting, { range: event.shiftKey, toggle: event.ctrlKey || event.metaKey });
  };

  const tabIndex = tabbable ? 0 : -1;

  return (
    <li ref={item} className="library-row" data-checked={checked || undefined} data-open={open || undefined}>
      {renaming ? (
        <RowRename meeting={meeting} onSubmit={(next) => onRename(meeting.id, next)} onCancel={onCancelRename} />
      ) : (
        <>
          <button
            ref={openButton}
            type="button"
            data-row-id={meeting.id}
            className={`library-item library-item--${ROW_EDGES[tone]}`}
            aria-current={open ? "true" : undefined}
            tabIndex={tabIndex}
            {...tip.triggerProps}
            onFocus={(event) => { tip.triggerProps.onFocus?.(event); onFocusRow(meeting.id); }}
            onClick={onClick}
          >
            <RowThumbnail meeting={meeting} />
            <span className="library-item-main">
              <span className="library-item-head">
                <span className="library-item-title">{title}</span>
                <StatusBadge tone={tone}>{t(STATE_LABEL_KEYS[meeting.processState])}</StatusBadge>
              </span>
              <span className="library-item-meta">
                <span>{formatListDate(meetingDate(meeting, dateField))}</span>
                {duration !== null && <span className="library-item-duration">{formatDuration(duration)}</span>}
                {speakers !== null && <span>{t("library:speakers", { count: speakers })}</span>}
              </span>
              <RowProgress meeting={meeting} />
            </span>
          </button>
          <span className="library-row-check">
            <input type="checkbox" aria-label={t("library:row.select", { title })} checked={checked} tabIndex={tabIndex}
              onFocus={() => onFocusRow(meeting.id)}
              onChange={(event) => onToggleChecked(meeting.id, (event.nativeEvent as globalThis.MouseEvent).shiftKey === true)} />
          </span>
          <div className="library-row-menu">
            <Menu label={t("library:row.actions", { title })} trigger={<Icon icon={Ellipsis} />} triggerTabIndex={tabIndex}
              triggerClassName="ui-icon-button ui-icon-button--ghost">
              <MenuItem onSelect={() => onStartRename(meeting.id)}>
                <Icon icon={Pencil} size={16} />{t("library:row.rename")}
              </MenuItem>
              <MenuItem disabled={!ready} hint={ready ? undefined : t("library:row.downloadUnavailable")}
                onSelect={() => onDownload(meeting, "transcript")}>
                <Icon icon={FileText} size={16} />{t("library:row.downloadTranscript")}
              </MenuItem>
              <MenuItem disabled={!summaryReady} hint={summaryReady ? undefined : t("library:row.downloadSummaryUnavailable")}
                onSelect={() => onDownload(meeting, "summary")}>
                <Icon icon={ScrollText} size={16} />{t("library:row.downloadSummary")}
              </MenuItem>
              <MenuItem disabled={!ready} hint={ready ? undefined : t("library:row.downloadMediaUnavailable")}
                onSelect={() => onDownload(meeting, "media")}>
                <Icon icon={audioOnly ? AudioLines : Video} size={16} />
                {audioOnly ? t("library:row.downloadAudio") : t("library:row.downloadVideo")}
              </MenuItem>
              <MenuSeparator />
              <MenuItem tone="danger" onSelect={() => onDelete(meeting)}>
                <Icon icon={Trash2} size={16} />{t("library:row.delete")}
              </MenuItem>
            </Menu>
          </div>
          {tip.tooltip}
        </>
      )}
      {notice && <p role="status" className="library-row-notice">{notice}</p>}
      {error && <p role="alert" className="library-row-error">{error}</p>}
    </li>
  );
}
