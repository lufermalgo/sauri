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
import { groupTranscriptTurns } from "../transcript-turns";
import { SummaryPanel } from "./SummaryPanel";
import { copy } from "../copy/es";

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
  const [activeTab, setActiveTab] = useState<"transcript" | "summary">("transcript");
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
    setActiveTab("transcript");

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

  function speakerPresentation(turnId: string) {
    const speakerId = diarization?.assignments.find((assignment) => assignment.turn_id === turnId)?.speaker_id;
    const speaker = diarization?.speakers.find((candidate) => candidate.id === speakerId);
    const reviewedLabel = review?.items.find((item) => item.speakerId === speakerId)?.currentLabel.trim();
    return {
      label: reviewedLabel || speaker?.label || "Speaker N",
      color: speakerColor(diarization, speakerId),
    };
  }

  const playbackPassages = data.segments.map((passage) => {
    const speaker = speakerPresentation(passage.id);
    return { ...passage, speakerLabel: speaker.label, speakerColor: speaker.color };
  });
  const sourceTurnById = new Map(data.turns.map((turn) => [turn.id, turn]));
  const presentationTurns = groupTranscriptTurns(
    data.turns.map((turn) => ({
      id: turn.id,
      text: turn.text,
      startMs: turn.startMs,
      endMs: turn.endMs,
      sequence: turn.sequence,
    })),
    new Map(diarization?.assignments.map(({ turn_id, speaker_id }) => [turn_id, speaker_id]) ?? []),
  );

  return (
    <section>
      <button onClick={onBack}>← Back to list</button>
      {diarizationNotFound && <p role="status">Identificando hablantes</p>} {/* spanish-sample-data */}
      <div id="meeting-playback">
        <MeetingPlaybackView
          manifest={playbackManifest}
          passages={playbackPassages}
          loading={playbackLoading}
          error={playbackError}
          onRefreshManifest={() => getPlaybackManifest(meetingId)}
          onSeekToReady={registerSeekTo}
        />
      </div>
      <div role="tablist" aria-label={copy.summary.tabsLabel} onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" ? "transcript" : event.key === "End" ? "summary"
          : activeTab === "transcript" ? "summary" : "transcript";
        setActiveTab(next);
        event.currentTarget.querySelector<HTMLButtonElement>(`#${next}-tab`)?.focus();
      }}>
        <button type="button" role="tab" id="transcript-tab" aria-controls="transcript-panel"
          aria-selected={activeTab === "transcript"} tabIndex={activeTab === "transcript" ? 0 : -1}
          onClick={() => setActiveTab("transcript")}>{copy.summary.transcriptTab}</button>
        <button type="button" role="tab" id="summary-tab" aria-controls="summary-panel"
          aria-selected={activeTab === "summary"} tabIndex={activeTab === "summary" ? 0 : -1}
          onClick={() => setActiveTab("summary")}>{copy.summary.tab}</button>
      </div>
      <div role="tabpanel" id="summary-panel" aria-labelledby="summary-tab" hidden={activeTab !== "summary"}>
        {activeTab === "summary" && (
          <SummaryPanel meetingId={meetingId} onSeek={(timeMs) => seekToRef.current?.(timeMs)} />
        )}
      </div>
      <div role="tabpanel" id="transcript-panel" aria-labelledby="transcript-tab" hidden={activeTab !== "transcript"}>
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
            const speaker = speakerPresentation(turn.id);
            const lastSource = sourceTurnById.get(turn.sourceIds.at(-1) ?? "");
            const timestamp = lastSource && turn.sourceIds.length === 1
              ? `[${formatTimestamp(turn.timestampMs ?? 0)} – ${formatTimestamp(lastSource.endMs)}]`
              : `[${formatTimestamp(turn.timestampMs ?? 0)}]`;
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
      </div>
    </section>
  );
}
