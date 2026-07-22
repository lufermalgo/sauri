import React, { useEffect, useState } from "react";
import { ProcessState } from "@sauri/shared-types";
import type { Meeting } from "@sauri/shared-types";
import { listMeetings } from "../api";

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
  onSelectMeeting: (meeting: Meeting) => void;
}

export function MeetingList({ refreshKey, onSelectMeeting }: MeetingListProps) {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
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
            <th>Link</th>
            <th>State</th>
            <th>Failure cause</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {meetings.map((m) => (
            <tr key={m.id}>
              <td>{m.meetLink}</td>
              <td>
                <span
                  style={{
                    color: STATE_COLORS[m.processState],
                    fontWeight: "bold",
                  }}
                >
                  {m.processState}
                </span>
              </td>
              <td>{m.failureCause ?? "—"}</td>
              <td>
                {m.processState === ProcessState.Completed && (
                  <button onClick={() => onSelectMeeting(m)}>
                    View transcript
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
