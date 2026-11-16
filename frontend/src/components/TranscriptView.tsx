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
import { createPlaybackIntervals } from "../transcript-turns";
import {
  UNRESOLVED_SPEAKER_COLOR, displaySpeakerLabel, presentTranscriptTurns, speakerColor,
} from "../transcript-presentation";
import { ProcessingStatus } from "./ProcessingStatus";
import { SummaryPanel } from "./SummaryPanel";
import { useStageStart } from "../useStageStart";
import { MeetingHeader } from "./MeetingHeader";
import { LIBRARY_CHANGED_EVENT } from "../library-events";
import { ChatTab } from "./ChatTab";
import { Avatar, Tabs, Skeleton, SkeletonLines } from "./ui";
import type { SpeakerRowModel } from "./SpeakerReviewPanel";
import { SpeakerDock } from "./SpeakerDock";
import { useSpeakerDock } from "./useSpeakerDock";
import "../styles/meeting.css";
import { NO_SPEECH_CAUSE, detectProcessingStage, type SummarySignal } from "../processing-estimate";
import { useT } from "../i18n";
import { toUpperLocale } from "../i18n/format";

interface TranscriptViewProps {
  meetingId: string;
  /** Shown as a back button in the header when the list is not beside this view (narrow screens). */
  onBack?: () => void;
  /** Reports whether the server knows this recording: "found" once it answers, "missing" on a 404. */
  onResolved?: (outcome: "found" | "missing") => void;
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

// Wall-clock speaker wait limit, including hidden time; repeated polls do not reset it.
const SPEAKER_WAIT_TIMEOUT_MS = 15 * 60 * 1000;
// After speakers finish, the backend requests the summary on its own; wait this long to see that request.
const AUTO_SUMMARY_GRACE_MS = 10_000;
// How long the success state stays before the processing card goes away.
const SUCCESS_VISIBLE_MS = 3000;

function isReviewFailure(err: unknown, reason: "conflict" | "not_found"): boolean {
  return err instanceof Error && (err as { reason?: unknown }).reason === reason;
}

export function TranscriptView(props: TranscriptViewProps) {
  return <MeetingTranscriptView key={props.meetingId} {...props} />;
}

function MeetingTranscriptView({ meetingId, onBack, onResolved }: TranscriptViewProps) {
  const { t } = useT();
  const onResolvedRef = useRef(onResolved);
  onResolvedRef.current = onResolved;
  const [meeting, setMeeting] = useState<MeetingState | null>(null);
  const [metadata, setMetadata] = useState<{
    title: string | null; createdAt: string | null; recordedAt: string | null; durationSeconds: number | null;
  }>({ title: null, createdAt: null, recordedAt: null, durationSeconds: null });
  const [metadataError, setMetadataError] = useState(false);
  const authorizedMeetingId = meeting?.meetingId;

  useEffect(() => {
    if (!authorizedMeetingId) return;
    let cancelled = false;
    void listMeetings().then(items => {
      if (cancelled) return;
      const item = items.find(candidate => candidate.id === meetingId);
      if (item) setMetadata({
        title: item.title ?? null, createdAt: item.createdAt, recordedAt: item.recordedAt ?? item.createdAt,
        durationSeconds: typeof item.durationSeconds === "number" ? item.durationSeconds : null,
      });
      else setMetadataError(true);
    }).catch(() => { if (!cancelled) setMetadataError(true); });
    return () => { cancelled = true; };
  }, [meetingId, authorizedMeetingId]);

  // The list pane beside this view can rename the recording: pick up the new title quietly.
  useEffect(() => {
    if (!authorizedMeetingId) return;
    let cancelled = false;
    const refresh = () => {
      listMeetings().then(items => {
        const item = items.find(candidate => candidate.id === meetingId);
        if (!cancelled && item) setMetadata(current => ({ ...current, title: item.title ?? null }));
      }).catch(() => undefined);
    };
    window.addEventListener(LIBRARY_CHANGED_EVENT, refresh);
    return () => {
      cancelled = true;
      window.removeEventListener(LIBRARY_CHANGED_EVENT, refresh);
    };
  }, [meetingId, authorizedMeetingId]);

  const [statusError, setStatusError] = useState(false);
  const [diarizationError, setDiarizationError] = useState(false);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const turnRefs = useRef(new Map<string, HTMLLIElement>());
  const [followPlayback, setFollowPlayback] = useState(true);
  const { open: reviewOpen, setOpen: setReviewOpen } = useSpeakerDock();
  // True only when the user just opened the panel: a panel restored from the stored choice keeps focus where it is.
  const dockFocusOnMount = useRef(false);
  const viewRef = useRef<HTMLElement>(null);
  const [playingSpeakerId, setPlayingSpeakerId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("summary");
  const [keyPointTimes, setKeyPointTimes] = useState<number[]>([]);
  // The summary the side panel already loaded feeds the key-point markers and the header's download.
  const [hasSummary, setHasSummary] = useState(false);
  const handleSummaryChange = useCallback((summary: MeetingSummary | null) => {
    setHasSummary(summary !== null);
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
  const pauseRef = useRef<(() => void) | undefined>(undefined);
  const registerPause = useCallback((pause: (() => void) | undefined) => { pauseRef.current = pause; }, []);
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
  const [submittingSpeakerIds, setSubmittingSpeakerIds] = useState<string[]>([]);
  const playbackRef = useRef<HTMLDivElement>(null);
  // Idempotency key of the last unsettled action per speaker, reused when that same action is retried.
  const pendingActions = useRef(new Map<string, { signature: string; key: string }>());
  // Latest review snapshot and the chain of saves: auto-saved edits run one after another so each
  // response (a full snapshot) includes the previous ones and no stale snapshot overwrites a newer one.
  const reviewRef = useRef<SpeakerReview | null>(null);
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());

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
        if (!cancelled) setPlaybackError(t("meeting:playbackLoadFailed"));
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
          setReviewError(t("speakerReview:loadFailed"));
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
          onResolvedRef.current?.("found");
          setMeeting(state.value);
          setStatusError(false);
          terminal = state.value.processState === "failed" ||
            (state.value.processState === "completed" && speakers.status === "fulfilled");
        } else {
          if (state.reason instanceof Error && state.reason.message === "Error 404") onResolvedRef.current?.("missing");
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
          setError(t("meeting:transcriptLoadFailed"));
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

  /** Queues one disposition save. Resolves to null on success or to the message to show when it failed. */
  function recordDisposition(speakerId: string, disposition: SpeakerDisposition, label?: string): Promise<string | null> {
    const run = saveQueue.current.then(() => applyDisposition(speakerId, disposition, label));
    saveQueue.current = run;
    return run;
  }

  async function applyDisposition(
    speakerId: string,
    disposition: SpeakerDisposition,
    label?: string
  ): Promise<string | null> {
    const current = reviewRef.current;
    const item = current?.items.find((candidate) => candidate.speakerId === speakerId);
    if (!current || !item) return t("speakerReview:notFound");
    const signature = JSON.stringify([current.revisionId, disposition, label ?? null, item.expectedVersion]);
    const previous = pendingActions.current.get(speakerId);
    const action = previous?.signature === signature ? previous : { signature, key: newIdempotencyKey() };
    pendingActions.current.set(speakerId, action);
    const request: SpeakerDispositionRequest = {
      disposition,
      expectedVersion: item.expectedVersion,
      idempotencyKey: action.key,
      ...(label === undefined ? {} : { label }),
    };

    setSubmittingSpeakerIds((ids) => [...ids, speakerId]);
    setReviewError(null);
    try {
      const updatedReview = await submitSpeakerDisposition(
        meetingId,
        current.revisionId,
        speakerId,
        request
      );
      pendingActions.current.delete(speakerId);
      reviewRef.current = updatedReview;
      setReview(updatedReview);
      return null;
    } catch (err) {
      // A conflict or a missing meeting will not succeed on retry; anything else keeps the key.
      if (isReviewFailure(err, "conflict") || isReviewFailure(err, "not_found")) pendingActions.current.delete(speakerId);
      return isReviewFailure(err, "conflict") ? t("speakerReview:conflict")
        : isReviewFailure(err, "not_found") ? t("speakerReview:notFound") : t("speakerReview:saveFailed");
    } finally {
      setSubmittingSpeakerIds((ids) => ids.filter((id) => id !== speakerId));
    }
  }

  /** Saves a typed name: "named" for a speaker that only had the generic label, "corrected" for a real name. */
  async function renameSpeaker(speakerId: string, name: string): Promise<string | null> {
    const generic = speakerRows.find((row) => row.speakerId === speakerId)?.generic ?? true;
    return recordDisposition(speakerId, generic ? "named" : "corrected", name);
  }

  async function acceptSuggestion(speakerId: string) {
    const message = await recordDisposition(speakerId, "confirmed");
    if (message) setReviewError(message);
  }

  /** Marks every pending speaker that still has the generic label as reviewed, keeping that label. */
  async function leaveUnnamed() {
    for (const row of speakerRows.filter((candidate) => candidate.generic && candidate.disposition === null)) {
      const message = await recordDisposition(row.speakerId, "confirmed");
      if (message) {
        setReviewError(message);
        return;
      }
    }
  }

  const intervalTurns = useMemo(() => {
    if (!data) return [];
    if (data.presentation === "words") return data.turns;
    const speakerByTurn = new Map(diarization?.assignments.map(({ turn_id, speaker_id }) => [turn_id, speaker_id]) ?? []);
    return data.turns.map((turn) => ({ ...turn, speakerId: speakerByTurn.get(turn.id) ?? null }));
  }, [data, diarization]);

  async function listenToSpeaker(speakerId: string, startMs: number, endMs: number) {
    setReviewError(null);
    if (playingSpeakerId === speakerId) {
      pauseRef.current?.();
      return;
    }
    const playInterval = playIntervalRef.current;
    if (!playInterval) {
      setReviewError(t("speakerReview:playbackUnavailable"));
      return;
    }
    setPlayingSpeakerId(speakerId);
    try {
      await playInterval(startMs, endMs);
    } catch {
      setPlayingSpeakerId(null);
      setReviewError(t("speakerReview:playbackFailed"));
    }
  }

  function toggleReview() {
    if (reviewOpen) {
      closeReview();
      return;
    }
    dockFocusOnMount.current = true;
    setReviewOpen(true);
  }

  function closeReview() {
    // An excerpt must not keep playing after its row is gone.
    if (playingSpeakerId) pauseRef.current?.();
    setPlayingSpeakerId(null);
    dockFocusOnMount.current = false;
    setReviewOpen(false);
    // The panel and the focus inside it disappear: land on the entry point again.
    viewRef.current?.querySelector<HTMLElement>(".meeting-speakers > button")?.focus();
  }

  const presentationTurns = useMemo(
    () => (data ? presentTranscriptTurns(data, diarization, review) : []),
    // `t` changes with the language, so the speaker labels follow it.
    [data, diarization, review, t],
  );

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
        speakerLabel: presentation?.speakerLabel ?? t("transcript:unknownSpeaker"),
        color: presentation?.color ?? UNRESOLVED_SPEAKER_COLOR,
      };
    });
  }, [intervalTurns, presentationTurns, t]);

  const sourceTurnById = new Map(data?.turns.map((turn) => [turn.id, turn]));

  // Nothing will ever be transcribed: the status card explains it, so no transcript placeholder.
  const noSpeech = meeting?.processState === "failed" && meeting.failureCause === NO_SPEECH_CAUSE && !statusError;

  reviewRef.current = review;
  const speakerRows: SpeakerRowModel[] = review?.items.map(item => {
    const raw = review.labelsBySpeakerId[item.speakerId]?.trim() || item.currentLabel;
    const label = displaySpeakerLabel(raw || t("transcript:legacyUnknownSpeaker"), item.speakerId, review);
    // Generic until a person typed a name: the numbered "Speaker N" label (or none) is not a name.
    const generic = !raw || (/^Speaker \d+$/.test(raw) && item.disposition !== "named" && item.disposition !== "corrected");
    return {
      speakerId: item.speakerId, label, generic, color: speakerColor(diarization, item.speakerId),
      disposition: item.disposition, interval: selectListeningInterval(intervalTurns, item.speakerId),
    };
  }) ?? [];
  const pendingCount = review?.items.filter(item => item.disposition === null).length ?? 0;
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
  const stageStartedAt = useStageStart(stage);
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
    <p role="status" className="meeting-sr-only">{t("meeting:opening")}</p>
    <div className="meeting-body" aria-hidden="true">
      <div className="meeting-main">
        <div className="meeting-playback-card">
          <div className="meeting-loading-heading"><Skeleton width="60%" height={20} /><Skeleton width="45%" height={12} /></div>
          <Skeleton className="meeting-video-skeleton" /><SkeletonLines lines={1} />
        </div>
        <div className="meeting-transcript"><TranscriptSkeleton /></div>
      </div>
      <div className="meeting-side-column"><div className="meeting-sidebar"><SkeletonLines lines={6} /></div></div>
    </div>
  </section>;

  const hasSpeakers = review !== null && review.items.length > 0 && !noSpeech;
  const dockOpen = hasSpeakers && reviewOpen;
  const speakerReview = hasSpeakers ? { pendingCount, open: dockOpen, onToggle: toggleReview } : undefined;
  const speakingId = presentationTurns.find(turn => turn.id === activeTurnId)?.speakerId ?? null;
  const hasNotices = metadataError || speakerWaitExpired || showProcessing ||
    diarizationError || Boolean(error);

  return (
    <section className="meeting-view" tabIndex={-1} ref={viewRef}>
      <MeetingHeader meetingId={meetingId} title={metadata.title} createdAt={metadata.createdAt} recordedAt={metadata.recordedAt}
        stage={statusError ? undefined : stage ?? undefined} processState={meeting?.processState}
        speakerCount={diarization?.speakers.length} manifest={playbackManifest} turns={presentationTurns} hasSummary={hasSummary}
        speakerReview={speakerReview} onBack={onBack} />
      {hasNotices && <div className="meeting-notices">
        {metadataError && <p role="alert" className="meeting-error">{t("meeting:metadataFailed")}</p>}
        {speakerWaitExpired ? <div className="meeting-processing"><p role="status">{t("processing:speakerWaitExpired")}</p></div> :
          showProcessing && <div className="meeting-processing">
            <ProcessingStatus meeting={meeting} hasTranscript={Boolean(data)}
              diarizationNotFound={diarizationNotFound} error={statusError}
              hasDiarization={diarization !== null} summary={summaryForStage}
              audioSeconds={playbackManifest?.duration_seconds ?? metadata.durationSeconds}
              createdAt={metadata.createdAt} />
          </div>}
        {diarizationError && <p role="alert">{t("processing:diarizationFailed")}</p>}
        {error && <p role="alert" className="meeting-error">{error}</p>}
      </div>}
      <div className={`meeting-body${dockOpen ? " meeting-body--dock" : ""}`}>
      <div className="meeting-main">
      <section className="meeting-playback-card" aria-label={t("meeting:playback")}>
      <div id="meeting-playback" ref={playbackRef} onTimeUpdate={updateActiveTurn} onSeeked={updateActiveTurn}
        onPause={() => setPlayingSpeakerId(null)} onEnded={() => setPlayingSpeakerId(null)}>
        <MeetingPlaybackView
          keyPointTimes={keyPointTimes}
          timelineTurns={timelineTurns}
          manifest={playbackManifest}
          loading={playbackLoading}
          error={playbackError}
          onRefreshManifest={() => getPlaybackManifest(meetingId)}
          onSeekToReady={registerSeekTo}
          onPlayIntervalReady={registerPlayInterval}
          onPauseReady={registerPause}
          sidePanel={dockOpen && review ? <SpeakerDock rows={speakerRows} complete={review.status === "complete"}
            busyIds={submittingSpeakerIds} playingId={playingSpeakerId} speakingId={speakingId}
            playbackReady={Boolean(playbackManifest) && !playbackLoading && !playbackError}
            playbackLoading={playbackLoading} error={reviewError} focusOnMount={dockFocusOnMount.current}
            onListen={row => { if (row.interval) void listenToSpeaker(row.speakerId, row.interval.startMs, row.interval.endMs); }}
            onRename={renameSpeaker} onAcceptSuggestion={id => void acceptSuggestion(id)} onLeaveUnnamed={leaveUnnamed}
            onClose={closeReview} /> : undefined}
        />
      </div>
      </section>
      <section className="meeting-transcript" aria-labelledby="meeting-transcript-heading">
      <div className="meeting-transcript-heading">
        <h2 id="meeting-transcript-heading">{t("meeting:transcript")}</h2>
        <label className="meeting-follow"><input type="checkbox" checked={followPlayback}
          onChange={event => setFollowPlayback(event.target.checked)} />{t("meeting:followPlayback")}</label>
      </div>
      <div className="meeting-transcript-body">
      {!data && !error && !noSpeech && <>
        <p role="status">{t("processing:transcriptPending")}</p>
        <p>{t("meeting:transcriptPlaceholder")}</p>
        <span role="status" className="meeting-sr-only">{t("meeting:loading")}</span>
        <TranscriptSkeleton />
      </>}
      {data && <>
      {presentationTurns.length === 0 ? (
        <p>{t("meeting:emptyTranscript")}</p>
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
                  aria-label={t("transcript:playAt", { time: formatTimestamp(turn.timestampMs ?? 0) })}
                  aria-describedby={`turn-${turn.id}-speaker turn-${turn.id}-text${turn.hasAmbiguous ? ` turn-${turn.id}-ambiguous` : ""}`}
                  aria-current={isActive ? "true" : undefined}
                  disabled={turn.timestampMs === null || !playbackManifest || playbackLoading || Boolean(playbackError)}
                  onClick={() => {
                    if (turn.timestampMs !== null) seekToRef.current?.(turn.timestampMs, true);
                  }}
                >
                  <Avatar initials={speakerInitials(turn.speakerLabel)} color={turn.color} size="sm" />
                  <span className="meeting-turn-meta">
                    <span id={`turn-${turn.id}-speaker`} data-testid="transcript-speaker-label" className="meeting-speaker">
                      {turn.speakerLabel}
                    </span>
                    <span className="meeting-timestamp">{timestamp}</span>
                    {turn.hasAmbiguous && <span title={t("transcript:ambiguous")}
                      id={`turn-${turn.id}-ambiguous`} aria-label={t("transcript:ambiguous")} className="meeting-ambiguous">
                      <span aria-hidden="true"> · ? </span>
                      <span className="meeting-sr-only">{t("transcript:ambiguous")}</span>
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
      </div>
      </section>
      </div>
      <aside className="meeting-side-column">
      <div className="meeting-sidebar">
        <Tabs aria-label={t("meeting:sideTabs")} activeId={activeTab} onChange={setActiveTab} tabs={[
          { id: "summary", label: t("meeting:summaryTab"), panel: meeting
            // Stays mounted behind the other tab so summary-status polling (and the header) keeps going.
            ? <SummaryPanel meetingId={meetingId} onSeek={timeMs => seekToRef.current?.(timeMs)} transcriptReady={data !== null} onSummaryChange={handleSummaryChange}
              expectAutoRequest={expectSummary} onSignalChange={handleSummarySignal}
              progress={{ audioSeconds: playbackManifest?.duration_seconds ?? metadata.durationSeconds,
                createdAt: metadata.createdAt, stageStartedAt: stage === "summary" ? stageStartedAt : null }} /> : null },
          { id: "chat", label: t("meeting:chatTab"), panel: <ChatTab /> },
        ]} />
      </div>
      {reviewError && !dockOpen && <p role="alert" className="meeting-error">{reviewError}</p>}
      </aside>
      </div>
    </section>
  );
}

function speakerInitials(label: string): string {
  return toUpperLocale(label.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join(""));
}

function TranscriptSkeleton() {
  return <div className="meeting-transcript-skeleton" aria-hidden="true">
    {[0, 1, 2].map(index => <div className="meeting-skeleton-turn" key={index}>
      <Skeleton width={36} height={36} radius="full" />
      <div><Skeleton width="40%" height={12} /><SkeletonLines lines={2} /></div>
    </div>)}
  </div>;
}
