import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, RefObject } from "react";
import { LoaderCircle, Pause, Pencil, Play } from "lucide-react";
import type { SpeakerDisposition } from "../api";
import type { ListeningInterval } from "../speaker-review-interval";
import { Avatar, Icon, StatusBadge, useTooltip } from "./ui";
import { t, useT } from "../i18n";
import { toUpperLocale } from "../i18n/format";

export interface SpeakerRowModel {
  speakerId: string;
  /** Name shown for the speaker: the generic numbered label (for example "Speaker 1" in Spanish copy) or the assigned name. */
  label: string;
  /** True while the speaker still carries the generic numbered label (no real name yet). */
  generic: boolean;
  color: string;
  disposition: SpeakerDisposition | null;
  interval: ListeningInterval | null;
}

export interface SpeakerReviewPanelProps {
  rows: SpeakerRowModel[];
  complete: boolean;
  /** Speakers with a save in flight. */
  busyIds: readonly string[];
  playingId: string | null;
  /** Speaker talking at the current playback position, highlighted so the video can be matched to a row. */
  speakingId?: string | null;
  playbackReady: boolean;
  playbackLoading: boolean;
  error: string | null;
  onListen: (row: SpeakerRowModel) => void;
  /** Saves a name. Resolves to null on success or to the message to show when the save failed. */
  onRename: (speakerId: string, name: string) => Promise<string | null>;
  /** Keeps the machine-suggested name as final. */
  onAcceptSuggestion: (speakerId: string) => void;
  /** Marks every pending speaker that still has the generic label as reviewed without a name. */
  onLeaveUnnamed: () => Promise<void>;
}

const segmenter = typeof Intl !== "undefined" && "Segmenter" in Intl
  ? new Intl.Segmenter(undefined, { granularity: "grapheme" }) : null;

/** First user-perceived character of a name, uppercased (accents and emoji stay whole). */
export function firstGrapheme(name: string): string {
  const trimmed = name.trim();
  const first = segmenter ? segmenter.segment(trimmed)[Symbol.iterator]().next().value?.segment : Array.from(trimmed)[0];
  return toUpperLocale(first ?? "");
}

/** Avatar text: initial plus number (such as "H1") for a generic numbered label, the first letter of the name otherwise. */
export function avatarText(label: string, generic: boolean): string {
  if (!generic) return firstGrapheme(label);
  const numbered = /^(\S+)\s+(\d+)$/.exec(label.trim());
  if (numbered) return firstGrapheme(numbered[1]) + numbered[2];
  return label.trim().split(/\s+/).slice(0, 2).map(firstGrapheme).join("");
}

/**
 * Splits the "Name - Organization" convention used for speakers (for example "Ana Perez - Summan") so the
 * organization can be shown as secondary text. The stored label is never changed: `tail` keeps the original
 * separator, so name + tail is exactly the label.
 */
export function splitOrganization(label: string): { name: string; tail: string } {
  const match = /^(.+?)(\s+[-\u2013\u2014]\s+\S.*)$/.exec(label.trim());
  return match ? { name: match[1], tail: match[2] } : { name: label, tail: "" };
}

/** True while the text of `ref` is cut by its ellipsis, so a tooltip can show the whole name. */
function useIsTruncated(ref: RefObject<HTMLElement>, key: unknown): boolean {
  const [truncated, setTruncated] = useState(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) { setTruncated(false); return; }
    const measure = () => setTruncated(element.scrollWidth > element.clientWidth + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, key]);
  return truncated;
}

/** Speaker identification list shown in the panel beside the video: one row per speaker. */
export function SpeakerReviewPanel({
  rows, complete, busyIds, playingId, speakingId = null, playbackReady, playbackLoading, error,
  onListen, onRename, onAcceptSuggestion, onLeaveUnnamed,
}: SpeakerReviewPanelProps) {
  const { t } = useT();
  const [announcement, setAnnouncement] = useState<{ id: number; message: string } | null>(null);
  const [leaving, setLeaving] = useState(false);
  const announce = (message: string) => setAnnouncement(current => ({ id: (current?.id ?? 0) + 1, message }));
  const pendingGeneric = rows.some(row => row.generic && row.disposition === null);

  async function leaveUnnamed() {
    setLeaving(true);
    try {
      await onLeaveUnnamed();
      announce(t("speakerReview:leftUnnamed"));
    } finally {
      setLeaving(false);
    }
  }

  return <div className="meeting-speaker-review">
    <p role="status" className={complete ? "meeting-sr-only" : undefined}>{complete ? t("speakerReview:complete") : t("speakerReview:pending")}</p>
    <div role="status" className="meeting-sr-only">
      {announcement && <span key={announcement.id}>{announcement.message}</span>}
    </div>
    {error && <p role="alert" className="meeting-error">{error}</p>}
    {rows.map(row => <SpeakerRow key={row.speakerId} row={row}
      busy={busyIds.includes(row.speakerId)} playing={playingId === row.speakerId} speaking={speakingId === row.speakerId}
      playbackReady={playbackReady} playbackLoading={playbackLoading}
      onListen={onListen} onRename={onRename} onAcceptSuggestion={onAcceptSuggestion} onAnnounce={announce} />)}
    {pendingGeneric && <div className="meeting-review-footer">
      <button type="button" className="meeting-review-leave" disabled={leaving || busyIds.length > 0}
        aria-busy={leaving || undefined} onClick={() => void leaveUnnamed()}>{t("speakerReview:leaveUnnamed")}</button>
    </div>}
  </div>;
}

interface SpeakerRowProps extends Pick<SpeakerReviewPanelProps, "playbackReady" | "playbackLoading" | "onListen" | "onRename" | "onAcceptSuggestion"> {
  row: SpeakerRowModel;
  busy: boolean;
  playing: boolean;
  speaking: boolean;
  onAnnounce: (message: string) => void;
}

function statusText(row: SpeakerRowModel): string {
  if (row.generic) return row.disposition === null ? t("speakerReview:pendingState") : t("speakerReview:unnamedState");
  return row.disposition === null ? t("speakerReview:suggestedState") : t("speakerReview:namedState");
}

function SpeakerRow({ row, busy, playing, speaking, playbackReady, playbackLoading, onListen, onRename, onAcceptSuggestion, onAnnounce }: SpeakerRowProps) {
  const { t } = useT();
  const { speakerId, label, interval } = row;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);
  const pencilRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Guards: a save in flight, and an edit that already ended (its unmount-time blur must not save again).
  const inFlight = useRef(false);
  const ended = useRef(false);
  const refocusPencil = useRef(false);
  const errorId = `speaker-name-error-${speakerId}`;

  const playName = t("speakerReview:listenTo", { label });
  const playTip = useTooltip(playing ? t("speakerReview:stopFor", { label }) : playName);
  const editName = t("speakerReview:editName", { label });
  const editTip = useTooltip(editName);
  const nameRef = useRef<HTMLHeadingElement>(null);
  const truncated = useIsTruncated(nameRef, `${label}|${editing}`);
  const nameTip = useTooltip(truncated && !editing ? label : undefined);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    } else if (refocusPencil.current) {
      refocusPencil.current = false;
      pencilRef.current?.focus();
    }
  }, [editing]);

  function startEdit() {
    editTip.hide();
    ended.current = false;
    setDraft(label);
    setRowError(null);
    setEditing(true);
  }

  function endEdit(returnFocus: boolean) {
    ended.current = true;
    refocusPencil.current = returnFocus;
    setRowError(null);
    setEditing(false);
  }

  async function commit(via: "enter" | "blur") {
    if (ended.current || inFlight.current) return;
    const name = draft.trim();
    if (!name) {
      // An empty name cannot be saved (the backend requires one and cannot revert to the generic label).
      if (via === "enter") {
        setRowError(t("speakerReview:nameRequired"));
        onAnnounce(t("speakerReview:nameRequired"));
      } else endEdit(false);
      return;
    }
    if (name === label) { endEdit(via === "enter"); return; }
    inFlight.current = true;
    setSaving(true);
    setRowError(null);
    const message = await onRename(speakerId, name);
    inFlight.current = false;
    setSaving(false);
    if (message) {
      setRowError(message);
      onAnnounce(message);
      return;
    }
    onAnnounce(t("speakerReview:saved", { name }));
    endEdit(via === "enter");
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      void commit("enter");
    } else if (event.key === "Escape") {
      // Cancels the edit only: the panel stays open.
      event.preventDefault();
      if (!inFlight.current) endEdit(true);
    }
  }

  const status = statusText(row);
  const pending = row.generic && row.disposition === null;
  const suggested = !row.generic && row.disposition === null;
  const { name: person, tail } = row.generic ? { name: label, tail: "" } : splitOrganization(label);
  return <article className={`meeting-review-item${speaking ? " meeting-review-item--speaking" : ""}${pending ? " meeting-review-item--pending" : ""}`}
    style={{ "--meeting-speaker": row.color } as CSSProperties}
    aria-current={speaking ? "true" : undefined} aria-busy={busy || saving || undefined}>
    <Avatar initials={avatarText(label, row.generic)} color={row.color} size="md" />
    <div className="meeting-review-identity">
      {editing
        ? <div className="meeting-review-edit">
          <input ref={inputRef} className="ui-input meeting-review-input" type="text" value={draft}
            maxLength={64} aria-label={t("speakerReview:nameFor", { label })} readOnly={saving} aria-busy={saving || undefined}
            aria-invalid={rowError ? true : undefined} aria-describedby={rowError ? errorId : undefined}
            onChange={event => setDraft(event.target.value)} onKeyDown={onKeyDown} onBlur={() => void commit("blur")} />
          {saving && <span className="meeting-review-spinner"><Icon icon={LoaderCircle} size={16} /></span>}
        </div>
        : <h3 ref={nameRef} className="meeting-review-name" {...nameTip.triggerProps}>
          {person}{tail && <span className="meeting-review-org">{tail}</span>}
        </h3>}
      {!editing && nameTip.tooltip}
      {editing && rowError
        ? <p id={errorId} className="meeting-review-field-error">{rowError}</p>
        // Only a speaker that still needs a name shows its state; for the rest it stays available to screen readers.
        : editing ? null
          : pending ? <StatusBadge tone="progress" dot className="meeting-review-status">{status}</StatusBadge>
          : <span className="meeting-sr-only">{status}</span>}
    </div>
    <div className="meeting-review-actions">
      <span className="meeting-review-play">
        <button type="button" className={`ui-icon-button ${playing ? "ui-icon-button--primary" : "ui-icon-button--ghost"}`}
          aria-label={playName} aria-pressed={playing} {...playTip.triggerProps}
          onClick={() => { playTip.hide(); onListen(row); }} disabled={!interval || !playbackReady}>
          <Icon icon={playing ? Pause : Play} size={16} />
        </button>
        {playTip.tooltip}
      </span>
      {!editing && <span className="meeting-review-edit-trigger">
        <button ref={pencilRef} type="button" className="ui-icon-button ui-icon-button--ghost"
          aria-label={editName} {...editTip.triggerProps} onClick={startEdit} disabled={busy}>
          <Icon icon={Pencil} size={16} />
        </button>
        {editTip.tooltip}
      </span>}
    </div>
    {suggested && !editing && <div className="meeting-review-suggest">
      <button type="button" className="meeting-review-chip" disabled={busy}
        onClick={() => onAcceptSuggestion(speakerId)}>{t("speakerReview:acceptSuggestion", { name: label })}</button>
    </div>}
    {!interval && <p>{t("speakerReview:noInterval")}</p>}
    {interval?.short && <p>{t("speakerReview:shortInterval")}</p>}
    {interval && !playbackReady && !playbackLoading && <p>{t("speakerReview:playbackUnavailable")}</p>}
  </article>;
}
