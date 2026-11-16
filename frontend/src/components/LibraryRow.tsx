import { useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, MouseEvent } from "react";
import { AudioLines, Download, Ellipsis, Pencil, Trash2, Video } from "lucide-react";
import { ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { copy } from "../copy/es";
import { estimateProgress, secondsSince } from "../processing-estimate";
import { Icon, Menu, MenuItem, ProgressBar, StatusBadge, useTooltip } from "./ui";

const text = copy.library;

/** Hover or keyboard focus on a row waits this long before its summary tooltip appears. */
const SUMMARY_TOOLTIP_DELAY_MS = 500;

type BadgeTone = "neutral" | "progress" | "success" | "error";

const STATE_LABELS: Record<ProcessState, string> = {
  [ProcessState.Queued]: text.states.queued,
  [ProcessState.Joining]: text.states.joining,
  [ProcessState.Recording]: text.states.recording,
  [ProcessState.Transcribing]: text.states.transcribing,
  [ProcessState.Completed]: text.states.completed,
  [ProcessState.Failed]: text.states.failed,
};

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

const CREATED_AT_FORMATTER = new Intl.DateTimeFormat("es", {
  dateStyle: "medium",
  timeStyle: "short",
});

const THUMBNAIL_ICON_SIZE = 16;
const MAX_TITLE_LENGTH = 512;

function formatCreatedAt(createdAt: string | null): string {
  if (!createdAt) return text.noDate;
  const date = new Date(createdAt);
  return Number.isNaN(date.getTime()) ? text.noDate : CREATED_AT_FORMATTER.format(date);
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

/** Compact estimate for rows in transcription; nothing when there is no honest estimate. */
function RowProgress({ meeting }: { meeting: MeetingListItem }) {
  if (meeting.processState !== ProcessState.Queued && meeting.processState !== ProcessState.Transcribing) return null;
  const elapsed = secondsSince(meeting.createdAt, Date.now());
  if (elapsed === null) return null;
  const estimate = estimateProgress({
    stage: "transcription", audioSeconds: meeting.durationSeconds, elapsedSinceUploadSeconds: elapsed,
  });
  if (!estimate) return null;
  const processing = copy.processing;
  const stage = processing.steps.transcription;
  const label = estimate.overtime ? processing.libraryOvertime(stage) : processing.libraryProgress(stage, estimate.percent);
  return (
    <span className="processing-compact library-item-progress">
      <ProgressBar label={processing.libraryProgressLabel} value={estimate.percent} valueText={label} />
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
      <input ref={input} type="text" className="library-rename-input" aria-label={text.row.renameLabel}
        value={draft} disabled={busy} maxLength={MAX_TITLE_LENGTH} autoComplete="off"
        aria-invalid={failed || !valid ? true : undefined} aria-describedby={failed ? errorId : undefined}
        onChange={(event) => { setDraft(event.target.value); setFailed(false); }}
        onKeyDown={onKeyDown}
        onBlur={() => { if (!busy && draft === initial) onCancel(); }} />
      {failed && <p id={errorId} role="alert" className="library-rename-error">{text.row.renameFailed}</p>}
    </form>
  );
}

export interface LibraryRowProps {
  meeting: MeetingListItem;
  /** The recording open in the detail pane. */
  open: boolean;
  /** Part of the bulk selection. */
  checked: boolean;
  /** Only one row at a time is in the tab order; arrow keys move between rows. */
  tabbable: boolean;
  renaming: boolean;
  /** Last failed action on this row (download, delete). */
  error: string | null;
  onOpen: (meeting: MeetingListItem, modifiers: { range: boolean; toggle: boolean }) => void;
  onToggleChecked: (id: string, range: boolean) => void;
  onFocusRow: (id: string) => void;
  onStartRename: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onCancelRename: () => void;
  onDownload: (meeting: MeetingListItem) => void;
  onDelete: (meeting: MeetingListItem) => void;
}

/** One recording: title line, meta line and status chip; selection checkbox and actions menu beside it. */
export function LibraryRow({
  meeting, open, checked, tabbable, renaming, error, onOpen, onToggleChecked, onFocusRow,
  onStartRename, onRename, onCancelRename, onDownload, onDelete,
}: LibraryRowProps) {
  const tone = STATE_TONES[meeting.processState];
  const title = meeting.title.trim() || text.untitled;
  const topic = meeting.summaryTopic?.trim() || undefined;
  // The API may omit these fields for older recordings.
  const duration = typeof meeting.durationSeconds === "number" ? meeting.durationSeconds : null;
  const speakers = typeof meeting.speakerCount === "number" && meeting.speakerCount > 0
    ? meeting.speakerCount
    : null;
  const ready = isReady(meeting);

  const item = useRef<HTMLLIElement>(null);
  const openButton = useRef<HTMLButtonElement>(null);
  const [placement, setPlacement] = useState<CSSProperties>();
  // The row's scroll pane would clip a tooltip drawn inside it, so it is fixed to the window,
  // below the row or above it when there is no room.
  const tip = useTooltip(topic, {
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
                <StatusBadge tone={tone}>{STATE_LABELS[meeting.processState]}</StatusBadge>
              </span>
              <span className="library-item-meta">
                <span>{formatCreatedAt(meeting.createdAt)}</span>
                {duration !== null && <span className="library-item-duration">{formatDuration(duration)}</span>}
                {speakers !== null && <span>{text.speakers(speakers)}</span>}
              </span>
              <RowProgress meeting={meeting} />
            </span>
          </button>
          <span className="library-row-check">
            <input type="checkbox" aria-label={text.row.select(title)} checked={checked} tabIndex={tabIndex}
              onFocus={() => onFocusRow(meeting.id)}
              onChange={(event) => onToggleChecked(meeting.id, (event.nativeEvent as globalThis.MouseEvent).shiftKey === true)} />
          </span>
          <div className="library-row-menu">
            <Menu label={text.row.actions(title)} trigger={<Icon icon={Ellipsis} />} triggerTabIndex={tabIndex}
              triggerClassName="ui-icon-button ui-icon-button--ghost">
              <MenuItem onSelect={() => onStartRename(meeting.id)}>
                <Icon icon={Pencil} size={16} />{text.row.rename}
              </MenuItem>
              <MenuItem disabled={!ready} hint={ready ? undefined : text.row.downloadUnavailable}
                onSelect={() => onDownload(meeting)}>
                <Icon icon={Download} size={16} />{text.row.downloadTranscript}
              </MenuItem>
              <MenuItem tone="danger" onSelect={() => onDelete(meeting)}>
                <Icon icon={Trash2} size={16} />{text.row.delete}
              </MenuItem>
            </Menu>
          </div>
          {tip.tooltip}
        </>
      )}
      {error && <p role="alert" className="library-row-error">{error}</p>}
    </li>
  );
}
