import React, { useEffect, useState } from "react";
import { ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { listMeetings } from "../api";

const CREATED_AT_FORMATTER = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
});

const STATE_LABELS: Record<ProcessState, string> = {
  [ProcessState.Queued]: "Queued",
  [ProcessState.Joining]: "Joining",
  [ProcessState.Recording]: "Recording",
  [ProcessState.Transcribing]: "Transcribing",
  [ProcessState.Completed]: "Ready",
  [ProcessState.Failed]: "Failed",
};

const STATE_COLORS: Record<ProcessState, string> = {
  [ProcessState.Queued]: "#6b7280",
  [ProcessState.Joining]: "#f59e0b",
  [ProcessState.Recording]: "#ef4444",
  [ProcessState.Transcribing]: "#3b82f6",
  [ProcessState.Completed]: "#22c55e",
  [ProcessState.Failed]: "#dc2626",
};

interface MeetingListProps {
  refreshKey: number;
  onSelectMeeting: (meeting: MeetingListItem) => void;
}

export function MeetingList({ refreshKey, onSelectMeeting }: MeetingListProps) {
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    listMeetings()
      .then((data) => {
        if (!cancelled) setMeetings(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load meetings");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [refreshKey]);

  if (loading) return <p>Loading meetings...</p>;
  if (error) return <p role="alert" style={{ color: "red" }}>{error}</p>;
  if (meetings.length === 0) return <p>No meetings registered.</p>;

  return (
    <section>
      <h2>Meetings</h2>
      <table>
        <thead>
          <tr>
            <th>Title</th>
            <th>Created</th>
            <th>State</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {meetings.map((meeting) => (
            <tr key={meeting.id}>
              <td>{meeting.title}</td>
              <td>
                {meeting.createdAt
                  ? CREATED_AT_FORMATTER.format(new Date(meeting.createdAt))
                  : "—"}
              </td>
              <td>
                <span
                  style={{
                    color: STATE_COLORS[meeting.processState],
                    fontWeight: "bold",
                  }}
                >
                  {STATE_LABELS[meeting.processState]}
                </span>
              </td>
              <td>
                <button type="button" onClick={() => onSelectMeeting(meeting)}>
                  Open
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
