import React, { useEffect, useState } from "react";
import type { Transcript, SpeechTurn } from "@sauri/shared-types";
import { getTranscript } from "../api";

interface TranscriptViewProps {
  meetingId: string;
  onBack: () => void;
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

export function TranscriptView({ meetingId, onBack }: TranscriptViewProps) {
  const [data, setData] = useState<(Transcript & { turns: SpeechTurn[] }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    getTranscript(meetingId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load transcript");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [meetingId]);

  if (loading) return <p>Loading transcript...</p>;
  if (error) return <p role="alert" style={{ color: "red" }}>{error}</p>;
  if (!data) return <p>Transcript not found.</p>;

  return (
    <section>
      <button onClick={onBack}>← Back to list</button>
      <h2>Transcript</h2>
      <p>
        Language: {data.language} | Provider: {data.provider} |
        Turns: {data.supportsTurns ? "Yes" : "No"}
      </p>
      {data.turns.length === 0 ? (
        <p>No transcript segments.</p>
      ) : (
        <ol>
          {data.turns.map((turn) => (
            <li key={turn.id}>
              <span style={{ color: "#6b7280", marginRight: "0.5rem" }}>
                [{formatTimestamp(turn.startMs)} – {formatTimestamp(turn.endMs)}]
              </span>
              {turn.text}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
