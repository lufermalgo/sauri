import React, { useEffect, useState } from "react";
import {
  getPlaybackManifest,
  getSpeakerReview,
  getTranscript,
  playSpeakerExcerpt,
  submitSpeakerDisposition,
} from "../api";
import type { MeetingTranscript, PlaybackManifest, SpeakerDisposition, SpeakerDispositionRequest, SpeakerReview } from "../api";
import { MeetingPlaybackView } from "./MeetingPlaybackView";

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
  const [data, setData] = useState<MeetingTranscript | null>(null);
  const [playbackManifest, setPlaybackManifest] = useState<PlaybackManifest | null>(null);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const [playbackLoading, setPlaybackLoading] = useState(true);
  const [review, setReview] = useState<SpeakerReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [names, setNames] = useState<Record<string, string>>({});
  const [submittingSpeakerId, setSubmittingSpeakerId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setPlaybackLoading(true);
    setPlaybackManifest(null);
    setPlaybackError(null);
    setError(null);
    setReviewError(null);
    setReview(null);

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

    getPlaybackManifest(meetingId)
      .then((result) => {
        if (!cancelled) setPlaybackManifest(result);
      })
      .catch((err) => {
        if (!cancelled) setPlaybackError(err instanceof Error ? err.message : "Failed to load playback manifest");
      })
      .finally(() => {
        if (!cancelled) setPlaybackLoading(false);
      });

    Promise.resolve()
      .then(() => getSpeakerReview(meetingId))
      .then((result) => {
        if (!cancelled) setReview(result);
      })
      .catch((err) => {
        if (!cancelled) {
          setReviewError(err instanceof Error ? err.message : "Failed to load speaker review");
        }
      });

    return () => { cancelled = true; };
  }, [meetingId]);

  async function recordDisposition(
    speakerId: string,
    disposition: SpeakerDisposition,
    label?: string
  ) {
    if (!review) return;
    const item = review.items.find((candidate) => candidate.speakerId === speakerId);
    if (!item) return;
    const request: SpeakerDispositionRequest = {
      disposition,
      expectedVersion: item.expectedVersion,
      ...(label === undefined ? {} : { label }),
    };

    setSubmittingSpeakerId(speakerId);
    setReviewError(null);
    try {
      const updatedReview = await submitSpeakerDisposition(
        meetingId,
        review.revisionId,
        speakerId,
        request
      );
      setReview(updatedReview);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : "Failed to save speaker review");
    } finally {
      setSubmittingSpeakerId(null);
    }
  }

  async function playExcerpt(speakerId: string) {
    if (!review) return;
    setReviewError(null);
    try {
      await playSpeakerExcerpt(meetingId, review.revisionId, speakerId);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : "Failed to play speaker excerpt");
    }
  }

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
      <MeetingPlaybackView
        manifest={playbackManifest}
        passages={data.segments}
        loading={playbackLoading}
        error={playbackError}
        onRefreshManifest={() => getPlaybackManifest(meetingId)}
      />
      {reviewError && <p role="alert" style={{ color: "red" }}>{reviewError}</p>}
      {review && (
        <section aria-labelledby="speaker-review-heading">
          <h3 id="speaker-review-heading">Speaker review</h3>
          <p role="status">Review {review.status}</p>
          {review.items.map((item, index) => {
            const label = item.attributionState === "uncertain"
              ? item.currentLabel || `Speaker ${index + 1}`
              : item.currentLabel;
            const busy = submittingSpeakerId === item.speakerId;
            return (
              <article key={item.speakerId}>
                <h4>{label}</h4>
                <button
                  type="button"
                  onClick={() => void playExcerpt(item.speakerId)}
                  disabled={busy}
                >
                  Play excerpt for {label}
                </button>
                {item.disposition === null && (
                  <div>
                    <button
                      type="button"
                      onClick={() => void recordDisposition(item.speakerId, "confirmed")}
                      disabled={busy}
                    >
                      Confirm {label}
                    </button>
                    <label>
                      Name for {label}
                      <input
                        type="text"
                        value={names[item.speakerId] ?? ""}
                        onChange={(event) => setNames((current) => ({
                          ...current,
                          [item.speakerId]: event.target.value,
                        }))}
                        disabled={busy}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => void recordDisposition(item.speakerId, "named", names[item.speakerId]?.trim())}
                      disabled={busy || !names[item.speakerId]?.trim()}
                    >
                      Name {label}
                    </button>
                    <button
                      type="button"
                      onClick={() => void recordDisposition(item.speakerId, "corrected", names[item.speakerId]?.trim())}
                      disabled={busy || !names[item.speakerId]?.trim()}
                    >
                      Correct {label}
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </section>
      )}
    </section>
  );
}
