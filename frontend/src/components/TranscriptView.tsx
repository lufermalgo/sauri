import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  getDiarization,
  getPlaybackManifest,
  getSpeakerReview,
  getTranscript,
  playSpeakerExcerpt,
  submitSpeakerDisposition,
} from "../api";
import type { MeetingDiarization, MeetingTranscript, PlaybackManifest, SpeakerDisposition, SpeakerDispositionRequest, SpeakerReview } from "../api";
import { MeetingPlaybackView } from "./MeetingPlaybackView";
import { createPlaybackIntervals, groupTranscriptTurns, projectTranscript } from "../transcript-turns";

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

const SPEAKER_COLORS = ["#1d4ed8", "#b45309", "#047857", "#7e22ce", "#be123c", "#0e7490"];
const UNRESOLVED_SPEAKER_COLOR = "#6b7280";

function speakerColor(diarization: MeetingDiarization | null, speakerId: string | undefined): string {
  const sequence = diarization?.speakers.find((speaker) => speaker.id === speakerId)?.sequence;
  if (sequence === undefined) return UNRESOLVED_SPEAKER_COLOR;
  return SPEAKER_COLORS[(Math.max(1, sequence) - 1) % SPEAKER_COLORS.length];
}

export function TranscriptView({ meetingId, onBack }: TranscriptViewProps) {
  const seekToRef = useRef<((timeMs: number) => void) | undefined>(undefined);
  const registerSeekTo = useCallback((seekTo: ((timeMs: number) => void) | undefined) => {
    seekToRef.current = seekTo;
  }, []);
  const [data, setData] = useState<MeetingTranscript | null>(null);
  const [playbackManifest, setPlaybackManifest] = useState<PlaybackManifest | null>(null);
  const [diarization, setDiarization] = useState<MeetingDiarization | null>(null);
  const [diarizationNotFound, setDiarizationNotFound] = useState(false);
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
    setDiarization(null);
    setDiarizationNotFound(false);
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

    getDiarization(meetingId)
      .then((result) => {
        if (!cancelled) setDiarization(result);
      })
      .catch((err) => {
        if (!cancelled) {
          setDiarization(null);
          setDiarizationNotFound(err instanceof Error && err.message === "Error 404");
        }
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
    if (!item || item.expectedVersion === undefined) return;
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

  const notReconstructible = diarization?.latest_attempt?.diarization_state === "not_reconstructible";
  const speakersById = new Map(diarization?.speakers.map((speaker) => [speaker.id, speaker]) ?? []);
  const speakerIdByTurnId = new Map(
    !notReconstructible && diarization?.processing_revision != null
      ? diarization.assignments
        .filter((assignment) => typeof assignment.overlap_ms === "number"
          && Number.isFinite(assignment.overlap_ms) && assignment.overlap_ms > 0
          && speakersById.has(assignment.speaker_id))
        .map((assignment) => [assignment.turn_id, assignment.speaker_id] as const)
      : [],
  );
  const activeReview = review && String(diarization?.processing_revision) === review.revisionId
    ? review : null;

  function speakerPresentation(speakerId: string | undefined) {
    const speaker = speakerId ? speakersById.get(speakerId) : undefined;
    const reviewedLabel = speakerId ? activeReview?.labelsBySpeakerId?.[speakerId]?.trim() : undefined;
    return {
      label: reviewedLabel || speaker?.label || "Speaker N",
      color: speakerColor(diarization, speakerId),
    };
  }

  // Preserve untimed source text too; it cannot form a time-linked group.
  const sourceTurns = data.segments.length > 0 ? data.segments : data.turns;
  const sourceTurnById = new Map(sourceTurns.map((turn) => [turn.id, turn]));
  const projection = notReconstructible ? null : projectTranscript(sourceTurns, diarization, data.id);
  const presentationTurns = projection?.turns ?? groupTranscriptTurns(
    sourceTurns.map((turn) => ({
      id: turn.id,
      text: turn.text,
      startMs: turn.startMs,
      endMs: turn.endMs,
      sequence: turn.sequence,
    })),
    speakerIdByTurnId,
  );
  const playbackPassages = projection?.intervals ?? createPlaybackIntervals(sourceTurns, presentationTurns);
  const playbackTurns = presentationTurns.map((turn) => {
    const speaker = speakerPresentation(turn.speakerId);
    return { ...turn, speakerLabel: speaker.label, speakerColor: speaker.color };
  });

  return (
    <section>
      <button onClick={onBack}>← Back to list</button>
      {notReconstructible && <p role="status">No se puede reconstruir la atribución: el audio original no está disponible. Se conservan los fragmentos fuente.</p>} {/* spanish-sample-data: user-facing terminal explanation */}
      {diarizationNotFound && <p role="status">Identificando hablantes</p>} {/* spanish-sample-data */}
      <MeetingPlaybackView
        manifest={playbackManifest}
        passages={playbackPassages}
        presentationTurns={playbackTurns}
        loading={playbackLoading}
        error={playbackError}
        onRefreshManifest={() => getPlaybackManifest(meetingId)}
        onSeekToReady={registerSeekTo}
      />
      <h2>Transcript</h2>
      <p>
        Language: {data.language} | Provider: {data.provider} |
        Turns: {data.supportsTurns ? "Yes" : "No"}
      </p>
      {presentationTurns.length === 0 ? (
        <p>No transcript segments.</p>
      ) : (
        <ol>
          {presentationTurns.map((turn) => {
            const speaker = speakerPresentation(turn.speakerId);
            const lastSource = sourceTurnById.get(turn.sourceIds.at(-1) ?? "");
            const timestamp = turn.timestampMs === null ? "Sin marca de tiempo"
              : !projection && lastSource?.endMs != null && turn.sourceIds.length === 1
                ? `[${formatTimestamp(turn.timestampMs)} – ${formatTimestamp(lastSource.endMs)}]`
                : `[${formatTimestamp(turn.timestampMs)}]`;
            return (
              <li key={turn.id}>
                <span style={{ color: "#6b7280", marginRight: "0.5rem" }}>
                  {timestamp}
                </span>
                <span
                  data-testid="transcript-speaker-label"
                  style={{ color: speaker.color, fontWeight: 600, marginRight: "0.5rem" }}
                >
                  {speaker.label}
                </span>
                <button
                  type="button"
                  aria-label={`Play turn at ${formatTimestamp(turn.timestampMs ?? 0)}`}
                  disabled={turn.timestampMs === null}
                  onClick={() => {
                    if (turn.timestampMs !== null) seekToRef.current?.(turn.timestampMs);
                  }}
                >
                  Play turn
                </button>
                {turn.text}
              </li>
            );
          })}
        </ol>
      )}
      {reviewError && <p role="alert" style={{ color: "red" }}>{reviewError}</p>}
      {activeReview && (
        <section aria-labelledby="speaker-review-heading">
          <h3 id="speaker-review-heading">Speaker review</h3>
          <p role="status">Review {activeReview.status}</p>
          {activeReview.items.map((item, index) => {
            const label = item.attributionState === "uncertain"
              ? item.currentLabel || `Speaker ${index + 1}`
              : item.currentLabel;
            const busy = submittingSpeakerId === item.speakerId || item.expectedVersion === undefined;
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
