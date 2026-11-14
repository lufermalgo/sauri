import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getDiarization,
  getMeeting,
  getPlaybackManifest,
  getSpeakerReview,
  getTranscript,
  playSpeakerExcerpt,
  submitSpeakerDisposition,
} from "../api";
import type { MeetingDiarization, MeetingState, MeetingTranscript, PlaybackManifest, SpeakerDisposition, SpeakerDispositionRequest, SpeakerReview } from "../api";
import { MeetingPlaybackView } from "./MeetingPlaybackView";
import { createPlaybackIntervals, groupTranscriptTurns } from "../transcript-turns";
import { ProcessingStatus } from "./ProcessingStatus";
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
// Wall-clock speaker wait limit, including hidden time; repeated polls do not reset it.
const SPEAKER_WAIT_TIMEOUT_MS = 15 * 60 * 1000;

function speakerColor(diarization: MeetingDiarization | null, speakerId: string | undefined): string {
  const sequence = diarization?.speakers.find((speaker) => speaker.id === speakerId)?.sequence;
  if (sequence === undefined) return UNRESOLVED_SPEAKER_COLOR;
  return SPEAKER_COLORS[(Math.max(1, sequence) - 1) % SPEAKER_COLORS.length];
}

export function TranscriptView(props: TranscriptViewProps) {
  return <MeetingTranscriptView key={props.meetingId} {...props} />;
}

function MeetingTranscriptView({ meetingId, onBack }: TranscriptViewProps) {
  const [meeting, setMeeting] = useState<MeetingState | null>(null);
  const [statusError, setStatusError] = useState(false);
  const [diarizationError, setDiarizationError] = useState(false);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const turnRefs = useRef(new Map<string, HTMLLIElement>());
  const [activeTab, setActiveTab] = useState<"transcript" | "summary">("transcript");
  const seekToRef = useRef<((timeMs: number) => void) | undefined>(undefined);
  const registerSeekTo = useCallback((seekTo: ((timeMs: number) => void) | undefined) => {
    seekToRef.current = seekTo;
  }, []);
  const [data, setData] = useState<MeetingTranscript | null>(null);
  const [playbackManifest, setPlaybackManifest] = useState<PlaybackManifest | null>(null);
  const [diarization, setDiarization] = useState<MeetingDiarization | null>(null);
  const [diarizationNotFound, setDiarizationNotFound] = useState(false);
  const [speakerWaitExpired, setSpeakerWaitExpired] = useState(false);
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
    let inFlight = false;
    let terminal = false;
    let hasPlayback = false;
    let hasReview = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let speakerWaitTimer: ReturnType<typeof setTimeout> | undefined;

    function startSpeakerWait() {
      if (speakerWaitTimer !== undefined) return;
      speakerWaitTimer = setTimeout(() => {
        terminal = true;
        clearTimeout(timer);
        setSpeakerWaitExpired(true);
      }, SPEAKER_WAIT_TIMEOUT_MS);
    }

    async function refreshPlayback() {
      try {
        const result = await getPlaybackManifest(meetingId);
        if (!cancelled) {
          hasPlayback = true;
          setPlaybackManifest(result);
          setPlaybackError(null);
        }
      } catch (err) {
        if (!cancelled) setPlaybackError(err instanceof Error ? err.message : "Failed to load playback manifest");
      } finally {
        if (!cancelled) setPlaybackLoading(false);
      }
    }

    async function refreshReview() {
      try {
        const result = await getSpeakerReview(meetingId);
        if (!cancelled) {
          hasReview = Boolean(result);
          setReview(result);
          setReviewError(null);
        }
      } catch (err) {
        if (!cancelled && !(err instanceof Error && err.message === "Error 404")) {
          setReviewError(err instanceof Error ? err.message : "Failed to load speaker review");
        }
      }
    }

    async function refresh() {
      if (cancelled || document.hidden || inFlight || terminal) return;
      clearTimeout(timer);
      inFlight = true;
      try {
        const [state, speakers] = await Promise.allSettled([
          getMeeting(meetingId), getDiarization(meetingId),
        ]);
        if (cancelled || terminal || document.hidden) return;
        if (speakers.status === "fulfilled" ||
          (state.status === "fulfilled" && state.value.processState === "failed")) {
          clearTimeout(speakerWaitTimer);
          speakerWaitTimer = undefined;
        } else if (state.status === "fulfilled" && state.value.processState === "completed") {
          // completed means ASR is done, not necessarily speaker identification.
          startSpeakerWait();
        }
        // Fetch after diarization so its completed revision is visible to the transcript API.
        const [transcript] = await Promise.allSettled([getTranscript(meetingId)]);
        if (cancelled || terminal) return;
        if (state.status === "fulfilled") {
          setMeeting(state.value);
          setStatusError(false);
          terminal = state.value.processState === "failed" ||
            (state.value.processState === "completed" && speakers.status === "fulfilled");
        } else {
          setStatusError(true);
        }
        if (transcript.status === "fulfilled") {
          // Keep immutable artifact references stable so polling does not reset playback.
          setData((current) => current?.id === transcript.value.id &&
            current.presentation === transcript.value.presentation ? current : transcript.value);
          setError(null);
        } else if (transcript.reason instanceof Error && transcript.reason.message === "Error 404") {
          setData(null);
          setError(null);
        } else {
          setError(transcript.reason instanceof Error ? transcript.reason.message : "Failed to load transcript");
        }
        if (speakers.status === "fulfilled") {
          setDiarization((current) => current ?? speakers.value);
          setDiarizationNotFound(false);
          setDiarizationError(false);
        } else {
          const notFound = speakers.reason instanceof Error && speakers.reason.message === "Error 404";
          setDiarizationNotFound(notFound);
          setDiarizationError(!notFound);
        }
        if (speakers.status === "rejected" && state.status === "fulfilled" &&
          state.value.processState === "transcribing" && transcript.status === "fulfilled") {
          startSpeakerWait();
        }
        if (document.hidden) return;
        await Promise.all([
          ...(!hasPlayback ? [refreshPlayback()] : []),
          ...(!hasReview ? [refreshReview()] : []),
        ]);
      } finally {
        inFlight = false;
        if (!cancelled) {
          setLoading(false);
          if (!terminal && !document.hidden) timer = setTimeout(() => void refresh(), 5000);
        }
      }
    }

    function onVisibilityChange() {
      clearTimeout(timer);
      if (!document.hidden) void refresh();
    }

    void refresh();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearTimeout(speakerWaitTimer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
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

  const presentationTurns = useMemo(() => {
    if (!data) return [];
    if (data.presentation === "words") return data.turns.map((turn) => ({
      id: turn.id,
      sourceIds: [turn.id],
      text: turn.text,
      timestampMs: turn.startMs,
      sequence: turn.sequence,
      speakerId: turn.speakerId ?? undefined,
      speakerLabel: turn.speakerLabel ?? copy.transcript.unknownSpeaker,
      hasAmbiguous: turn.hasAmbiguous ?? false,
      color: speakerColor(diarization, turn.speakerId ?? undefined),
    }));
    return groupTranscriptTurns(
      data.turns,
      new Map(diarization?.assignments.map(({ turn_id, speaker_id }) => [turn_id, speaker_id]) ?? []),
    ).map((turn) => {
      const speaker = diarization?.speakers.find((candidate) => candidate.id === turn.speakerId);
      const reviewedLabel = review?.items.find((item) => item.speakerId === turn.speakerId)?.currentLabel.trim();
      return {
        ...turn,
        speakerLabel: reviewedLabel || speaker?.label || copy.transcript.legacyUnknownSpeaker,
        color: speakerColor(diarization, turn.speakerId),
        hasAmbiguous: false,
      };
    });
  }, [data, diarization, review]);

  const playbackPassages = useMemo(() => {
    if (!data) return [];
    const source = data.presentation === "words" ? data.turns : data.segments;
    return source.map((passage) => {
      const turn = presentationTurns.find((candidate) => candidate.sourceIds.includes(passage.id));
      return {
        ...passage,
        speakerLabel: turn?.speakerLabel ?? copy.transcript.legacyUnknownSpeaker,
        speakerColor: turn?.color ?? UNRESOLVED_SPEAKER_COLOR,
      };
    });
  }, [data, presentationTurns]);
  const playbackIntervals = useMemo(() => createPlaybackIntervals(data?.turns ?? [], presentationTurns),
    [data, presentationTurns]);

  useEffect(() => {
    if (activeTurnId && activeTab === "transcript") {
      turnRefs.current.get(activeTurnId)?.scrollIntoView?.({ block: "nearest" });
    }
  }, [activeTurnId, activeTab]);

  function updateActiveTurn(event: React.SyntheticEvent) {
    if (!(event.target instanceof HTMLMediaElement)) return;
    if (playbackManifest?.video_presence !== "muxed" && event.target instanceof HTMLVideoElement) return;
    const timeMs = event.target.currentTime * 1000;
    const interval = playbackIntervals.find((item) => item.startMs <= timeMs && timeMs < item.endMs);
    setActiveTurnId(interval?.presentationTurnId ?? null);
  }

  const sourceTurnById = new Map(data?.turns.map((turn) => [turn.id, turn]));

  return (
    <section>
      <button onClick={onBack}>← Back to list</button>
      {speakerWaitExpired ? <p role="status">{copy.processing.speakerWaitExpired}</p> :
        <ProcessingStatus meeting={meeting} hasTranscript={Boolean(data)}
          diarizationNotFound={diarizationNotFound} error={statusError} />}
      {diarizationError && <p role="alert">{copy.processing.diarizationFailed}</p>}
      {error && <p role="alert" style={{ color: "red" }}>{error}</p>}
      {!loading && !data && !error && <p>{copy.processing.transcriptPending}</p>}
      <div id="meeting-playback" onTimeUpdate={updateActiveTurn} onSeeked={updateActiveTurn}>
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
      {data && <>
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
            const isActive = activeTurnId === turn.id;
            const lastSource = sourceTurnById.get(turn.sourceIds.at(-1) ?? "");
            const timestamp = lastSource && turn.sourceIds.length === 1
              ? `[${formatTimestamp(turn.timestampMs ?? 0)} – ${formatTimestamp(lastSource.endMs)}]`
              : `[${formatTimestamp(turn.timestampMs ?? 0)}]`;
            return (
              <li key={turn.id}
                aria-current={isActive ? "true" : undefined}
                style={isActive ? { backgroundColor: "#fef3c7", fontWeight: 600 } : undefined}
                ref={(element) => {
                  if (element) turnRefs.current.set(turn.id, element);
                  else turnRefs.current.delete(turn.id);
                }}
              >
                <span style={{ color: "#6b7280", marginRight: "0.5rem" }}>
                  {timestamp}
                </span>
                <span
                  data-testid="transcript-speaker-label"
                  style={{ color: turn.color, fontWeight: 600, marginRight: "0.5rem" }}
                >
                  {turn.speakerLabel}
                </span>
                <button
                  type="button"
                  aria-label={copy.transcript.playAt(formatTimestamp(turn.timestampMs ?? 0))}
                  disabled={turn.timestampMs === null}
                  onClick={() => {
                    if (turn.timestampMs !== null) seekToRef.current?.(turn.timestampMs);
                  }}
                >
                  {copy.transcript.play}
                </button>
                {turn.hasAmbiguous && <span title={copy.transcript.ambiguous}
                  aria-label={copy.transcript.ambiguous} style={{ color: UNRESOLVED_SPEAKER_COLOR }}> · ? </span>}
                {turn.text}
              </li>
            );
          })}
        </ol>
      )}
      </>}
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
