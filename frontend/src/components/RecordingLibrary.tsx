import React, { useEffect, useState } from "react";
import { ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { listMeetings } from "../api";
import { copy } from "../copy/es";
import { applyLibraryQuery, type LibraryQuery, type LibrarySort } from "../library-query";
import { navigate } from "../router";
import { Button, Card, StatusBadge, TextField } from "./ui";
import "../styles/library.css";

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

interface RecordingLibraryProps {
  refreshKey: number;
  onSelectMeeting: (meeting: MeetingListItem) => void;
}

export function RecordingLibrary({ refreshKey, onSelectMeeting }: RecordingLibraryProps) {
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
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

  const goToUpload = () => navigate({ name: "upload" });

  const header = (
    <div className="library-header">
      <h1 className="library-title">{text.title}</h1>
      <Button variant="secondary" onClick={goToUpload}>{text.upload}</Button>
    </div>
  );

  let body: React.ReactNode;
  if (loading) {
    body = <p role="status" className="library-message">{text.loading}</p>;
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
    // Without criteria the list keeps the order received from the API.
    const visible = isQueryActive(query) ? applyLibraryQuery(meetings, query) : meetings;
    body = (
      <>
        <Card className="library-search" role="search" aria-label={text.search.regionLabel}>
          <div className="library-search-text">
            <TextField
              type="search"
              label={text.search.text}
              value={query.text}
              onChange={(event) => setQuery({ ...query, text: event.target.value })}
            />
          </div>
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
          <label className="library-sort library-search-sort">
            <span>{text.search.sort}</span>
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
          {isQueryActive(query) && (
            <Button variant="ghost" className="library-clear" onClick={() => setQuery(EMPTY_QUERY)}>
              {text.search.clear}
            </Button>
          )}
        </Card>
        {visible.length === 0 ? (
          <p role="status" className="library-message">{text.noMatch}</p>
        ) : (
          <ul className="library-list" aria-label={text.listLabel}>
            {visible.map((meeting) => (
              <li key={meeting.id}>
                <button
                  type="button"
                  className="ui-card library-item"
                  onClick={() => onSelectMeeting(meeting)}
                >
                  <span className="library-item-main">
                    <span className="library-item-title">{meeting.title.trim() || text.untitled}</span>
                    <span className="library-item-date">{formatCreatedAt(meeting.createdAt)}</span>
                  </span>
                  <StatusBadge tone={STATE_TONES[meeting.processState]}>
                    {STATE_LABELS[meeting.processState]}
                  </StatusBadge>
                </button>
              </li>
            ))}
          </ul>
        )}
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
