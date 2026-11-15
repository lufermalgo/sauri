import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getDiarization,
  getMeeting,
  listMeetings,
  getPlaybackManifest,
  getSpeakerReview,
  getTranscript,
  newIdempotencyKey,
  submitSpeakerDisposition,
} from "../api";
import type { MeetingDiarization, MeetingState, MeetingTranscript, PlaybackManifest, SpeakerDisposition, SpeakerDispositionRequest, SpeakerReview } from "../api";
import { MeetingPlaybackView } from "./MeetingPlaybackView";
import type { MeetingSummary } from "@sauri/shared-types";
import { selectListeningInterval } from "../speaker-review-interval";
import { createPlaybackIntervals, groupTranscriptTurns } from "../transcript-turns";
import { ProcessingStatus } from "./ProcessingStatus";
import { SummaryPanel } from "./SummaryPanel";
import { MeetingHeader } from "./MeetingHeader";
import { ChatTab } from "./ChatTab";
import { Avatar, Button, Card, Tabs, TextField, Skeleton, SkeletonLines } from "./ui";
import { meeting as text } from "../copy/meeting";
import "../styles/meeting.css";
import { detectProcessingStage, type SummarySignal } from "../processing-estimate";
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

const UNRESOLVED_SPEAKER_COLOR = "var(--speaker-unresolved)";
// Wall-clock speaker wait limit, including hidden time; repeated polls do not reset it.
const SPEAKER_WAIT_TIMEOUT_MS = 15 * 60 * 1000;
// After speakers finish, the backend requests the summary on its own; wait this long to see that request.
const AUTO_SUMMARY_GRACE_MS = 10_000;
// How long the success state stays before the processing card goes away.
const SUCCESS_VISIBLE_MS = 3000;

function isReviewFailure(err: unknown, reason: "conflict" | "not_found"): boolean {
  return err instanceof Error && (err as { reason?: unknown }).reason === reason;
}

function speakerColor(diarization: MeetingDiarization | null, speakerId: string | undefined): string {
  const sequence = diarization?.speakers.find((speaker) => speaker.id === speakerId)?.sequence;
  if (sequence === undefined) return UNRESOLVED_SPEAKER_COLOR;
  return `var(--speaker-${(Math.max(1, sequence) - 1) % 6 + 1})`;
}

function displaySpeakerLabel(label: string, speakerId: string | undefined, review: SpeakerReview | null): string {
  const disposition = review?.items.find(item => item.speakerId === speakerId)?.disposition;
  const number = /^Speaker (\d+)$/.exec(label)?.[1];
  return number && disposition !== "named" && disposition !== "corrected"
    ? copy.transcript.numberedSpeaker(number) : label;
}

export function TranscriptView(props: TranscriptViewProps) {
  return <MeetingTranscriptView key={props.meetingId} {...props} />;
}

function MeetingTranscriptView({ meetingId, onBack }: TranscriptViewProps) {
  const [meeting, setMeeting] = useState<MeetingState | null>(null);
  const [metadata, setMetadata] = useState<{ title: string | null; createdAt: string | null; durationSeconds: number | null }>(
    { title: null, createdAt: null, durationSeconds: null });
  const [metadataError, setMetadataError] = useState(false);
  const authorizedMeetingId = meeting?.meetingId;

  useEffect(() => {
    if (!authorizedMeetingId) return;
    let cancelled = false;
    void listMeetings().then(items => {
      if (cancelled) return;
      const item = items.find(candidate => candidate.id === meetingId);
      if (item) setMetadata({
        title: item.title ?? null, createdAt: item.createdAt,
        durationSeconds: typeof item.durationSeconds === "number" ? item.durationSeconds : null,
      });
      else setMetadataError(true);
    }).catch(() => { if (!cancelled) setMetadataError(true); });
    return () => { cancelled = true; };
  }, [meetingId, authorizedMeetingId]);

  const [statusError, setStatusError] = useState(false);
  const [diarizationError, setDiarizationError] = useState(false);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const turnRefs = useRef(new Map<string, HTMLLIElement>());
  const [followPlayback, setFollowPlayback] = useState(true);
  const [selectedSpeakerId, setSelectedSpeakerId] = useState<string | null>(null);
  const speakerCardRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState("summary");
  const [keyPointTimes, setKeyPointTimes] = useState<number[]>([]);
  // Key-point markers come from the summary the side panel already loaded.
  const handleSummaryChange = useCallback((summary: MeetingSummary | null) => {
    const times: number[] = [];
    for (const point of summary?.keyPoints ?? []) {
      if (typeof point !== "string" && point.sources.length > 0) times.push(point.sources[0].startMs);
    }
    setKeyPointTimes(times);
  }, []);
  const [summarySignal, setSummarySignal] = useState<SummarySignal>("none");
  const [workSeen, setWorkSeen] = useState(false);
  const [summaryWatch, setSummaryWatch] = useState<"idle" | "armed" | "over">("idle");
  const [success, setSuccess] = useState<"pending" | "showing" | "shown">("pending");
  const handleSummarySignal = useCallback((signal: SummarySignal) => setSummarySignal(signal), []);
  const seekToRef = useRef<((timeMs: number, play?: boolean) => void) | undefined>(undefined);
  const registerSeekTo = useCallback((seekTo: ((timeMs: number, play?: boolean) => void) | undefined) => {
    seekToRef.current = seekTo;
  }, []);
  const playIntervalRef = useRef<((startMs: number, endMs: number) => Promise<void>) | undefined>(undefined);
  const registerPlayInterval = useCallback(
    (playInterval: ((startMs: number, endMs: number) => Promise<void>) | undefined) => {
      playIntervalRef.current = playInterval;
    },
    [],
  );
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
  const playbackRef = useRef<HTMLDivElement>(null);
  // Idempotency key of the last unsettled action per speaker, reused when that same action is retried.
  const pendingActions = useRef(new Map<string, { signature: string; key: string }>());

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
      } catch {
        if (!cancelled) setPlaybackError(text.playbackLoadFailed);
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
        const notFound = isReviewFailure(err, "not_found") || (err instanceof Error && err.message === "Error 404");
        if (!cancelled && !notFound) {
          setReviewError(copy.speakerReview.loadFailed);
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
          setError(text.transcriptLoadFailed);
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
    const signature = JSON.stringify([review.revisionId, disposition, label ?? null, item.expectedVersion]);
    const previous = pendingActions.current.get(speakerId);
    const action = previous?.signature === signature ? previous : { signature, key: newIdempotencyKey() };
    pendingActions.current.set(speakerId, action);
    const request: SpeakerDispositionRequest = {
      disposition,
      expectedVersion: item.expectedVersion,
      idempotencyKey: action.key,
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
      pendingActions.current.delete(speakerId);
      setReview(updatedReview);
    } catch (err) {
      // A conflict or a missing meeting will not succeed on retry; anything else keeps the key.
      if (isReviewFailure(err, "conflict") || isReviewFailure(err, "not_found")) pendingActions.current.delete(speakerId);
      setReviewError(isReviewFailure(err, "conflict") ? copy.speakerReview.conflict
        : isReviewFailure(err, "not_found") ? copy.speakerReview.notFound : copy.speakerReview.saveFailed);
    } finally {
      setSubmittingSpeakerId(null);
    }
  }

  const intervalTurns = useMemo(() => {
    if (!data) return [];
    if (data.presentation === "words") return data.turns;
    const speakerByTurn = new Map(diarization?.assignments.map(({ turn_id, speaker_id }) => [turn_id, speaker_id]) ?? []);
    return data.turns.map((turn) => ({ ...turn, speakerId: speakerByTurn.get(turn.id) ?? null }));
  }, [data, diarization]);

  async function listenToSpeaker(startMs: number, endMs: number) {
    setReviewError(null);
    const playInterval = playIntervalRef.current;
    if (!playInterval) {
      setReviewError(copy.speakerReview.playbackUnavailable);
      return;
    }
    try {
      await playInterval(startMs, endMs);
    } catch {
      setReviewError(copy.speakerReview.playbackFailed);
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
      speakerLabel: displaySpeakerLabel(
        (turn.speakerId ? review?.labelsBySpeakerId[turn.speakerId]?.trim() : undefined) ||
          turn.speakerLabel || copy.transcript.unknownSpeaker, turn.speakerId ?? undefined, review),
      hasAmbiguous: turn.hasAmbiguous ?? false,
      color: speakerColor(diarization, turn.speakerId ?? undefined),
    }));
    return groupTranscriptTurns(
      data.turns,
      new Map(diarization?.assignments.map(({ turn_id, speaker_id }) => [turn_id, speaker_id]) ?? []),
    ).map((turn) => {
      const speaker = diarization?.speakers.find((candidate) => candidate.id === turn.speakerId);
      const reviewedLabel = turn.speakerId ? review?.labelsBySpeakerId[turn.speakerId]?.trim() : undefined;
      return {
        ...turn,
        speakerLabel: displaySpeakerLabel(reviewedLabel || speaker?.label || copy.transcript.legacyUnknownSpeaker, turn.speakerId, review),
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
    if (followPlayback && activeTurnId) {
      turnRefs.current.get(activeTurnId)?.scrollIntoView?.({ block: "nearest" });
    }
  }, [activeTurnId, followPlayback]);

  function updateActiveTurn(event: React.SyntheticEvent) {
    if (!(event.target instanceof HTMLMediaElement)) return;
    if (playbackManifest?.video_presence !== "muxed" && event.target instanceof HTMLVideoElement) return;
    const timeMs = event.target.currentTime * 1000;
    const interval = playbackIntervals.find((item) => item.startMs <= timeMs && timeMs < item.endMs);
    setActiveTurnId(interval?.presentationTurnId ?? null);
  }

  const timelineTurns = useMemo(() => {
    const presentationById = new Map(presentationTurns.flatMap(turn => turn.sourceIds.map(id => [id, turn] as const)));
    return intervalTurns.map(turn => {
      const presentation = presentationById.get(turn.id);
      return {
        id: turn.id, startMs: turn.startMs, endMs: turn.endMs,
        speakerId: turn.speakerId ?? undefined,
        speakerLabel: presentation?.speakerLabel ?? copy.transcript.unknownSpeaker,
        color: presentation?.color ?? UNRESOLVED_SPEAKER_COLOR,
      };
    });
  }, [intervalTurns, presentationTurns]);

  const sourceTurnById = new Map(data?.turns.map((turn) => [turn.id, turn]));

  const completed = meeting?.processState === "completed" && !statusError;

  const pendingCount = review?.items.filter(item => item.disposition === null).length ?? 0;
  const selectedId = selectedSpeakerId ?? review?.items[0]?.speakerId;
  const stageSignals = meeting ? {
    processState: meeting.processState, hasTranscript: Boolean(data), diarizationNotFound,
    hasDiarization: diarization !== null,
  } : null;
  // Stage ignoring the summary: tells whether this visit saw real work and when speakers finished.
  const workStage = stageSignals ? detectProcessingStage({ ...stageSignals, summary: "none" }) : null;
  // Render-time updates (React's derived-state pattern); local values keep this render consistent.
  const sawWork = workSeen || workStage === "transcription" || workStage === "speakers";
  if (sawWork && !workSeen) setWorkSeen(true);
  const armNow = sawWork && summaryWatch === "idle" && workStage === "done" && diarization !== null;
  if (armNow) setSummaryWatch("armed");
  const expectSummary = summaryWatch === "armed" || armNow;
  const summaryForStage: SummarySignal = summarySignal === "waiting" ? "waiting"
    : expectSummary && summarySignal !== "settled" ? "expected" : summarySignal;
  const stage = stageSignals ? detectProcessingStage({ ...stageSignals, summary: summaryForStage }) : null;
  // Only work finished during this visit earns the brief success state; a meeting opened done shows none.
  const successNow = sawWork && stage === "done" && success === "pending";
  if (successNow) setSuccess("showing");
  const showProcessing = statusError || stage !== "done" || success === "showing" || successNow;

  useEffect(() => {
    if (summaryWatch !== "armed") return;
    const timer = setTimeout(() => setSummaryWatch("over"), AUTO_SUMMARY_GRACE_MS);
    return () => clearTimeout(timer);
  }, [summaryWatch]);
  useEffect(() => {
    if (success !== "showing") return;
    const timer = setTimeout(() => setSuccess("shown"), SUCCESS_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [success]);

  if (loading) return <section className="meeting-view" aria-busy="true">
    <p role="status">{text.opening}</p>
    <header className="meeting-loading-heading" aria-hidden="true">
      <Skeleton width="60%" height={34} /><Skeleton width="45%" height={16} />
    </header>
    <div className="meeting-grid" aria-hidden="true">
      <Card className="meeting-playback-card"><Skeleton className="meeting-video-skeleton" /><SkeletonLines lines={1} /></Card>
      <div className="meeting-side-column"><Card><SkeletonLines lines={6} /></Card></div>
      <Card className="meeting-transcript"><TranscriptSkeleton /></Card>
    </div>
  </section>;

  return (
    <section className="meeting-view">
      <MeetingHeader meetingId={meetingId} title={metadata.title} createdAt={metadata.createdAt}
        onBack={onBack} completed={completed} processState={statusError ? undefined : meeting?.processState}
        speakerCount={diarization?.speakers.length} manifest={playbackManifest} turns={presentationTurns} />
      {pendingCount > 0 && <div className="meeting-pending-speakers">
        <span role="status">{text.pendingSpeakers(pendingCount)}</span>
        <Button variant="ghost" onClick={() => {
          speakerCardRef.current?.focus();
          speakerCardRef.current?.scrollIntoView?.({ block: "nearest" });
        }}>{text.reviewSpeakers}</Button>
      </div>}
      {metadataError && <p role="alert" className="meeting-error">{text.metadataFailed}</p>}
      {speakerWaitExpired ? <div className="meeting-processing"><p role="status">{copy.processing.speakerWaitExpired}</p></div> :
        showProcessing && <div className="meeting-processing">
          <ProcessingStatus meeting={meeting} hasTranscript={Boolean(data)}
            diarizationNotFound={diarizationNotFound} error={statusError}
            hasDiarization={diarization !== null} summary={summaryForStage}
            audioSeconds={playbackManifest?.duration_seconds ?? metadata.durationSeconds}
            createdAt={metadata.createdAt} />
        </div>}
      {diarizationError && <p role="alert">{copy.processing.diarizationFailed}</p>}
      {error && <p role="alert" className="meeting-error">{error}</p>}
      <div className="meeting-grid">
      <Card className="meeting-playback-card">
      <div id="meeting-playback" ref={playbackRef} onTimeUpdate={updateActiveTurn} onSeeked={updateActiveTurn}>
        <MeetingPlaybackView
          keyPointTimes={keyPointTimes}
          followPlayback={followPlayback}
          timelineTurns={timelineTurns}
          manifest={playbackManifest}
          passages={playbackPassages}
          loading={playbackLoading}
          error={playbackError}
          onRefreshManifest={() => getPlaybackManifest(meetingId)}
          onSeekToReady={registerSeekTo}
          onPlayIntervalReady={registerPlayInterval}
        />
      </div>
      </Card>
      <aside className="meeting-side-column">
      <Card className="meeting-sidebar">
        <Tabs aria-label={text.sideTabs} activeId={activeTab} onChange={setActiveTab} tabs={[
          { id: "summary", label: text.summaryTab, panel: meeting && activeTab === "summary"
            ? <SummaryPanel meetingId={meetingId} onSeek={timeMs => seekToRef.current?.(timeMs)} transcriptReady={data !== null} onSummaryChange={handleSummaryChange}
              expectAutoRequest={expectSummary} onSignalChange={handleSummarySignal} /> : null },
          { id: "chat", label: text.chatTab, panel: <ChatTab /> },
        ]} />
      </Card>
      {reviewError && <p role="alert" className="meeting-error">{reviewError}</p>}
      {review && (
        <Card className="meeting-speaker-review" aria-labelledby="speaker-review-heading">
          <div ref={speakerCardRef} tabIndex={-1}>
          <h3 id="speaker-review-heading">{copy.speakerReview.heading}</h3>
          <p role="status" className="meeting-sr-only">{review.status === "complete" ? copy.speakerReview.complete : copy.speakerReview.pending}</p>
          {review.items.map((item) => {
            const label = displaySpeakerLabel(review.labelsBySpeakerId[item.speakerId]?.trim() || item.currentLabel ||
              copy.transcript.legacyUnknownSpeaker, item.speakerId, review);
            const busy = submittingSpeakerId === item.speakerId;
            const name = names[item.speakerId]?.trim() ?? "";
            const interval = selectListeningInterval(intervalTurns, item.speakerId);
            const playbackReady = Boolean(playbackManifest) && !playbackLoading && !playbackError;
            const inputId = `speaker-name-${item.speakerId}`;
            return (
              <article className="meeting-review-item" key={item.speakerId} aria-busy={busy || undefined}>
                <div className="meeting-review-row">
                <Avatar initials={speakerInitials(label)} color={speakerColor(diarization, item.speakerId)} size="sm" />
                <div className="meeting-review-identity">
                  <h4><button type="button" className="meeting-speaker-select"
                    aria-label={copy.speakerReview.selectSpeaker(label)} aria-expanded={selectedId === item.speakerId}
                    aria-controls={`speaker-editor-${item.speakerId}`}
                    onClick={() => setSelectedSpeakerId(item.speakerId)}>{label}</button></h4>
                  <span className={item.disposition === null ? "meeting-review-pending" : "meeting-review-confirmed"}>
                    {item.disposition === null ? copy.speakerReview.pendingState : copy.speakerReview.confirmedState}
                  </span>
                </div>
                <Button variant="secondary"
                  type="button"
                  aria-label={copy.speakerReview.listenTo(label)}
                  onClick={() => { if (interval) void listenToSpeaker(interval.startMs, interval.endMs); }}
                  disabled={!interval || !playbackReady}
                >
                  {copy.speakerReview.listen}
                </Button>
                </div>
                {!interval && <p>{copy.speakerReview.noInterval}</p>}
                {interval?.short && <p>{copy.speakerReview.shortInterval}</p>}
                {interval && !playbackReady && !playbackLoading && <p>{copy.speakerReview.playbackUnavailable}</p>}
                {selectedId === item.speakerId && <div className="meeting-review-actions" id={`speaker-editor-${item.speakerId}`}>
                  <TextField label={copy.speakerReview.nameFor(label)}
                    id={inputId}
                    type="text"
                    value={names[item.speakerId] ?? ""}
                    onChange={(event) => setNames((current) => ({
                      ...current,
                      [item.speakerId]: event.target.value,
                    }))}
                    disabled={busy}
                  />
                  <Button variant="secondary"
                    type="button"
                    aria-label={copy.speakerReview.saveNameFor(label)}
                    onClick={() => void recordDisposition(item.speakerId, "named", name)}
                    disabled={busy || !name}
                  >
                    {copy.speakerReview.saveName}
                  </Button>
                  <Button variant="secondary"
                    type="button"
                    aria-label={copy.speakerReview.confirmFor(label)}
                    onClick={() => void recordDisposition(item.speakerId, "confirmed")}
                    disabled={busy}
                  >
                    {copy.speakerReview.confirm}
                  </Button>
                  <Button variant="secondary"
                    type="button"
                    aria-label={copy.speakerReview.correctFor(label)}
                    onClick={() => void recordDisposition(item.speakerId, "corrected", name)}
                    disabled={busy || !name}
                  >
                    {copy.speakerReview.correct}
                  </Button>
                  {busy && <span role="status">{copy.speakerReview.saving}</span>}
                </div>}
              </article>
            );
          })}
          </div>
        </Card>
      )}
      </aside>
      <Card className="meeting-transcript" aria-labelledby="meeting-transcript-heading">
      <div className="meeting-transcript-heading">
        <h2 id="meeting-transcript-heading">{text.transcript}</h2>
        <label className="meeting-follow"><input type="checkbox" checked={followPlayback}
          onChange={event => setFollowPlayback(event.target.checked)} />{text.followPlayback}</label>
      </div>
      {!data && !error && <>
        <p role="status">{copy.processing.transcriptPending}</p>
        <p>{text.transcriptPlaceholder}</p>
        <span role="status" className="meeting-sr-only">{text.loading}</span>
        <TranscriptSkeleton />
      </>}
      {data && <>
      {presentationTurns.length === 0 ? (
        <p>{text.emptyTranscript}</p>
      ) : (
        <ol className="meeting-turns">
          {presentationTurns.map((turn) => {
            const isActive = activeTurnId === turn.id;
            const lastSource = sourceTurnById.get(turn.sourceIds.at(-1) ?? "");
            const timestamp = lastSource && turn.sourceIds.length === 1
              ? `[${formatTimestamp(turn.timestampMs ?? 0)} – ${formatTimestamp(lastSource.endMs)}]`
              : `[${formatTimestamp(turn.timestampMs ?? 0)}]`;
            return (
              <li key={turn.id}
                aria-current={isActive ? "true" : undefined}
                className={`meeting-turn${isActive ? " meeting-turn--active" : ""}`}
                style={{ "--meeting-speaker": turn.color } as React.CSSProperties}
                ref={(element) => {
                  if (element) turnRefs.current.set(turn.id, element);
                  else turnRefs.current.delete(turn.id);
                }}
              >
                <button className="meeting-turn-action" type="button"
                  aria-label={copy.transcript.playAt(formatTimestamp(turn.timestampMs ?? 0))}
                  aria-describedby={`turn-${turn.id}-speaker turn-${turn.id}-text${turn.hasAmbiguous ? ` turn-${turn.id}-ambiguous` : ""}`}
                  aria-current={isActive ? "true" : undefined}
                  disabled={turn.timestampMs === null || !playbackManifest || playbackLoading || Boolean(playbackError)}
                  onClick={() => {
                    if (turn.timestampMs !== null) seekToRef.current?.(turn.timestampMs, true);
                  }}
                >
                  <Avatar initials={speakerInitials(turn.speakerLabel)} color={turn.color} />
                  <span className="meeting-turn-meta">
                    <span id={`turn-${turn.id}-speaker`} data-testid="transcript-speaker-label" className="meeting-speaker">
                      {turn.speakerLabel}
                    </span>
                    <span className="meeting-timestamp">{timestamp}</span>
                    {turn.hasAmbiguous && <span title={copy.transcript.ambiguous}
                      id={`turn-${turn.id}-ambiguous`} aria-label={copy.transcript.ambiguous} className="meeting-ambiguous">
                      <span aria-hidden="true"> · ? </span>
                      <span className="meeting-sr-only">{copy.transcript.ambiguous}</span>
                    </span>}
                    <svg className="meeting-turn-play" aria-hidden="true" width="14" height="14" viewBox="0 0 16 16">
                      <path d="M5 3 13 8 5 13Z" fill="currentColor" />
                    </svg>
                  </span>
                  <span id={`turn-${turn.id}-text`} className="meeting-turn-text">{turn.text}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
      </>}
      </Card>
      </div>
    </section>
  );
}

function speakerInitials(label: string): string {
  return label.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join("").toLocaleUpperCase("es");
}

function TranscriptSkeleton() {
  return <div className="meeting-transcript-skeleton" aria-hidden="true">
    {[0, 1, 2].map(index => <div className="meeting-skeleton-turn" key={index}>
      <Skeleton width={36} height={36} radius="full" />
      <div><Skeleton width="40%" height={12} /><SkeletonLines lines={2} /></div>
    </div>)}
  </div>;
}
