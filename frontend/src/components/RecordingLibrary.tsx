import React, { useEffect, useState } from "react";
import { ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { listMeetings } from "../api";
import { copy } from "../copy/es";
import { applyLibraryQuery, type LibraryQuery, type LibrarySort } from "../library-query";
import { navigate } from "../router";
import { estimateProgress, secondsSince } from "../processing-estimate";
import { Button, ProgressBar, Skeleton, StatusBadge, TextField } from "./ui";
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

const SORT_OPTIONS: Array<{ value: LibrarySort; label: string }> = [
  { value: "newest", label: text.search.sortNewest },
  { value: "oldest", label: text.search.sortOldest },
  { value: "title", label: text.search.sortTitle },
];

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
  if (tone === "error") return text.topicFailed;
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

function SearchIcon() {
  return (
    <svg className="library-search-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="7" cy="7" r="4.8" stroke="currentColor" strokeWidth="1.6" />
      <path d="M10.6 10.6L14 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
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
          if (!cancelled) setMeetings(data.map((item) => ({ ...item, title: item.title ?? "" })));
        })
        .catch(() => undefined);
    }, LIBRARY_REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [inProgress]);

  const goToUpload = () => navigate({ name: "upload" });

  const header = (
    <div className="library-header">
      <h1 className="library-title">{text.title}</h1>
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

    body = (
      <>
        <form
          className="ui-card library-search"
          role="search"
          aria-label={text.search.regionLabel}
          onSubmit={(event) => event.preventDefault()}
        >
          <label className="library-field library-search-text">
            <span className="library-field-label">{text.search.text}</span>
            <span className="library-search-box">
              <SearchIcon />
              <input
                type="search"
                className="library-search-input"
                value={query.text}
                onChange={(event) => setQuery({ ...query, text: event.target.value })}
              />
            </span>
          </label>
          <div className="library-search-date">
            <TextField
              type="date"
              label={text.search.from}
              value={query.from ?? ""}
              onChange={(event) => setQuery({ ...query, from: event.target.value || null })}
            />
          </div>
          <div className="library-search-date">
            <TextField
              type="date"
              label={text.search.to}
              value={query.to ?? ""}
              onChange={(event) => setQuery({ ...query, to: event.target.value || null })}
            />
          </div>
          <label className="library-field library-search-sort">
            <span className="library-field-label">{text.search.sort}</span>
            <select
              className="ui-input"
              value={query.sort}
              onChange={(event) => setQuery({ ...query, sort: event.target.value as LibrarySort })}
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          {active && (
            <Button variant="ghost" className="library-clear" onClick={() => setQuery(EMPTY_QUERY)}>
              {text.search.clear}
            </Button>
          )}
        </form>
        {list}
      </>
    );
  }

  return (
    <section className="library">
      {header}
      {body}
    </section>
  );
}
