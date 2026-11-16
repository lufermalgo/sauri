import React, { useEffect, useState } from "react";
import { AudioLines, Video } from "lucide-react";
import { ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { listMeetings } from "../api";
import { copy } from "../copy/es";
import { applyLibraryQuery, type LibraryQuery } from "../library-query";
import { navigate } from "../router";
import { NO_SPEECH_CAUSE, estimateProgress, secondsSince } from "../processing-estimate";
import { Button, Icon, ProgressBar, Skeleton, StatusBadge } from "./ui";
import { LibraryToolbar } from "./LibraryToolbar";
import "../styles/library.css";
import "../styles/processing.css";

const text = copy.library;

const CREATED_AT_FORMATTER = new Intl.DateTimeFormat("es", {
  dateStyle: "medium",
  timeStyle: "short",
});

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

// Rows still being worked on; while any is visible the list refreshes quietly.
const IN_PROGRESS_STATES: ReadonlySet<ProcessState> = new Set([
  ProcessState.Queued, ProcessState.Joining, ProcessState.Recording, ProcessState.Transcribing,
]);
const LIBRARY_REFRESH_MS = 10_000;

const EMPTY_QUERY: LibraryQuery = { text: "", from: null, to: null, sort: "newest" };

function isQueryActive(query: LibraryQuery): boolean {
  return query.text.trim() !== "" || query.from !== null || query.to !== null || query.sort !== "newest";
}

function formatCreatedAt(createdAt: string | null): string {
  if (!createdAt) return text.noDate;
  const date = new Date(createdAt);
  return Number.isNaN(date.getTime()) ? text.noDate : CREATED_AT_FORMATTER.format(date);
}

type RowEdge = "ready" | "progress" | "failed" | "queued";

const ROW_EDGES: Record<BadgeTone, RowEdge> = {
  success: "ready",
  progress: "progress",
  error: "failed",
  neutral: "queued",
};

type GroupKey = "today" | "thisWeek" | "earlier";

const GROUP_ORDER: GroupKey[] = ["today", "thisWeek", "earlier"];

const MS_PER_DAY = 24 * 60 * 60 * 1000;
const WEEK_DAYS = 7;
const SKELETON_ROWS = [
  { title: "38%", topic: "62%" },
  { title: "46%", topic: "54%" },
  { title: "32%", topic: "68%" },
];

function startOfLocalDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Groups by the local calendar date of createdAt, relative to `now`. Missing dates are "earlier". */
function groupKeyFor(createdAt: string | null, now: Date): GroupKey {
  if (!createdAt) return "earlier";
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "earlier";
  const daysAgo = Math.round((startOfLocalDay(now) - startOfLocalDay(date)) / MS_PER_DAY);
  if (daysAgo <= 0) return "today";
  return daysAgo < WEEK_DAYS ? "thisWeek" : "earlier";
}

function groupMeetings(
  items: MeetingListItem[],
  now: Date,
): Array<{ key: GroupKey; items: MeetingListItem[] }> {
  const buckets: Record<GroupKey, MeetingListItem[]> = { today: [], thisWeek: [], earlier: [] };
  for (const item of items) buckets[groupKeyFor(item.createdAt, now)].push(item);
  return GROUP_ORDER.filter((key) => buckets[key].length > 0).map((key) => ({ key, items: buckets[key] }));
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

function topicLine(meeting: MeetingListItem): string | null {
  const topic = meeting.summaryTopic?.trim();
  if (topic) return topic;
  const tone = STATE_TONES[meeting.processState];
  // Only the transcription stage is "generating"; a meeting still being recorded has no such text.
  if (meeting.processState === ProcessState.Transcribing) return text.topicGenerating;
  if (tone === "error") return meeting.failureCause === NO_SPEECH_CAUSE ? text.topicNoSpeech : text.topicFailed;
  return null;
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

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg className="library-item-chevron" width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="M6.5 3.5L12 9l-5.5 5.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const THUMBNAIL_ICON_SIZE = 24;

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

/** A quiet refresh keeps each row's current preview link: a new signature would reload the image. */
function keepThumbnailUrls(previous: MeetingListItem[], next: MeetingListItem[]): MeetingListItem[] {
  const urls = new Map(previous.map((item) => [item.id, item.thumbnailUrl]));
  return next.map((item) => {
    const current = urls.get(item.id);
    return current && item.thumbnailUrl ? { ...item, thumbnailUrl: current } : item;
  });
}

function LibraryRow({ meeting, onSelect }: { meeting: MeetingListItem; onSelect: () => void }) {
  const tone = STATE_TONES[meeting.processState];
  const topic = topicLine(meeting);
  // The API may omit these fields for older recordings.
  const duration = typeof meeting.durationSeconds === "number" ? meeting.durationSeconds : null;
  const speakers = typeof meeting.speakerCount === "number" && meeting.speakerCount > 0
    ? meeting.speakerCount
    : null;
  return (
    <li>
      <button
        type="button"
        className={`ui-card library-item library-item--${ROW_EDGES[tone]}`}
        onClick={onSelect}
      >
        <RowThumbnail meeting={meeting} />
        <span className="library-item-main">
          <span className="library-item-title">{meeting.title.trim() || text.untitled}</span>
          {topic && <span className="library-item-topic">{topic}</span>}
          <span className="library-item-meta">
            <span>{formatCreatedAt(meeting.createdAt)}</span>
            {duration !== null && <span className="library-item-duration">{formatDuration(duration)}</span>}
            {speakers !== null && <span>{text.speakers(speakers)}</span>}
          </span>
          <RowProgress meeting={meeting} />
        </span>
        <StatusBadge tone={tone}>{STATE_LABELS[meeting.processState]}</StatusBadge>
        <ChevronIcon />
      </button>
    </li>
  );
}

function LibrarySkeleton() {
  return (
    <ul className="library-list library-skeleton" aria-hidden="true">
      {SKELETON_ROWS.map((row) => (
        <li key={row.title} className="library-skeleton-row">
          <Skeleton className="library-skeleton-thumb" />
          <span className="library-skeleton-main">
            <Skeleton height={20} width={row.title} />
            <Skeleton height={14} width={row.topic} />
            <Skeleton height={12} width={220} />
          </span>
          <Skeleton height={28} width={84} radius="full" />
        </li>
      ))}
    </ul>
  );
}

interface RecordingLibraryProps {
  refreshKey: number;
  onSelectMeeting: (meeting: MeetingListItem) => void;
}

export function RecordingLibrary({ refreshKey, onSelectMeeting }: RecordingLibraryProps) {
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState<LibraryQuery>(EMPTY_QUERY);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);

    listMeetings()
      .then((data) => {
        // The API can return a null title for recordings that never had one.
        if (!cancelled) setMeetings(data.map((item) => ({ ...item, title: item.title ?? "" })));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [refreshKey, attempt]);

  const inProgress = meetings.some((meeting) => IN_PROGRESS_STATES.has(meeting.processState));
  useEffect(() => {
    if (!inProgress) return;
    let cancelled = false;
    // Quiet refresh: no loading state, and a failed refresh keeps the current list.
    const timer = setInterval(() => {
      if (document.hidden) return;
      listMeetings()
        .then((data) => {
          if (!cancelled) {
            const refreshed = data.map((item) => ({ ...item, title: item.title ?? "" }));
            setMeetings((current) => keepThumbnailUrls(current, refreshed));
          }
        })
        .catch(() => undefined);
    }, LIBRARY_REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [inProgress]);

  const goToUpload = () => navigate({ name: "upload" });

  // The search tools belong to a list that exists: not while loading, on error or with no recordings.
  const showToolbar = !loading && !failed && meetings.length > 0;
  const header = (
    <div className="library-header">
      <h1 className="library-title">{text.title}</h1>
      {showToolbar && <LibraryToolbar query={query} onChange={setQuery} />}
      <Button variant="primary" className="library-upload" onClick={goToUpload}>
        <PlusIcon />
        {text.upload}
      </Button>
    </div>
  );

  let body: React.ReactNode;
  if (loading) {
    body = (
      <>
        <p role="status" className="library-message">{text.loading}</p>
        <LibrarySkeleton />
      </>
    );
  } else if (failed) {
    body = (
      <div className="library-state">
        <p role="alert" className="library-message">{text.error}</p>
        <Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>
          {text.retry}
        </Button>
      </div>
    );
  } else if (meetings.length === 0) {
    body = (
      <div className="library-state">
        <p className="library-message">{text.empty}</p>
        <Button variant="primary" onClick={goToUpload}>{text.upload}</Button>
      </div>
    );
  } else {
    // Without criteria the list keeps the order received from the API and is grouped by date;
    // any search, filter or non-default sort shows a flat list.
    const active = isQueryActive(query);
    const visible = active ? applyLibraryQuery(meetings, query) : meetings;
    const renderRow = (meeting: MeetingListItem) => (
      <LibraryRow key={meeting.id} meeting={meeting} onSelect={() => onSelectMeeting(meeting)} />
    );

    let list: React.ReactNode;
    if (visible.length === 0) {
      list = <p role="status" className="library-message">{text.noMatch}</p>;
    } else if (active) {
      list = <ul className="library-list" aria-label={text.listLabel}>{visible.map(renderRow)}</ul>;
    } else {
      list = groupMeetings(visible, new Date()).map((group) => (
        <section key={group.key} className="library-group" aria-labelledby={`library-group-${group.key}`}>
          <h2 id={`library-group-${group.key}`} className="library-group-title">{text.groups[group.key]}</h2>
          <ul className="library-list">{group.items.map(renderRow)}</ul>
        </section>
      ));
    }

    body = list;
  }

  return (
    <section className="library">
      {header}
      {body}
    </section>
  );
}
