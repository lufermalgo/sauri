import { useEffect, useRef, useState } from "react";
import type { MeetingSummary, SummaryRequestStatus, SummarySource } from "@sauri/shared-types";
import type { SummarySignal } from "../processing-estimate";
import { getLatestSummaryRequest, getMeetingSummary, requestMeetingSummary } from "../api";
import { summaryFailureText } from "../summary-failure";
import { isBlock } from "../summary-export";
import { StageProgress } from "./StageProgress";
import { Button, Skeleton, SkeletonLines, StatusBadge } from "./ui";
import "../styles/summary.css";
import { useT } from "../i18n";

interface SummaryPanelProps {
  meetingId: string;
  onSeek: (startMs: number) => void;
  // False while the transcript is still being produced: summary generation starts on its own then.
  transcriptReady?: boolean;
  // Lets the meeting view reuse the loaded summary (e.g. key-point markers) without a second request.
  onSummaryChange?: (summary: MeetingSummary | null) => void;
  // True right after speaker identification: the automatic request may appear any second, so keep checking.
  expectAutoRequest?: boolean;
  // Lets the meeting view show summary progress without a second request.
  onSignalChange?: (signal: SummarySignal) => void;
  // Inputs of the generation progress shown while the summary is being written.
  progress?: { audioSeconds: number | null; createdAt: string | null; stageStartedAt: number | null };
  // Bumped by the meeting view when speaker names change: the backend applies the names when it serves the summary.
  refreshKey?: number;
}

const SKELETON_POINT_WIDTHS = ["72%", "58%", "66%"];

function GeneratingSkeleton({ progress }: { progress: NonNullable<SummaryPanelProps["progress"]> }) {
  const { t } = useT();
  return (
    <>
      <div className="summary-generating">
        <div className="summary-generating-head">
          <StatusBadge tone="progress">{t("summary:generatingBadge")}</StatusBadge>
          <span role="status" className="summary-generating-status">{t("summary:generating")}</span>
        </div>
        <StageProgress stage="summary" label={t("processing:summarizing")} {...progress} />
        <div className="summary-skeleton-block" aria-hidden="true">
          <Skeleton width={60} height={12} />
          <Skeleton height={16} />
          <Skeleton width="70%" height={16} />
        </div>
        <ul className="summary-skeleton-points" aria-hidden="true">
          {SKELETON_POINT_WIDTHS.map((width) => (
            <li key={width} className="summary-skeleton-point">
              <Skeleton width={16} height={16} radius="full" className="summary-skeleton-bullet" />
              <span className="summary-skeleton-body">
                <Skeleton height={14} />
                <Skeleton width={width} height={14} />
                <Skeleton width={110} height={18} radius="full" />
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="summary-help">{t("summary:generatingHelp")}</p>
    </>
  );
}

function timestamp(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

function SourceChips({ sources, onSeek }: { sources: SummarySource[]; onSeek: (startMs: number) => void }) {
  const { t } = useT();
  if (sources.length === 0) return null;
  return (
    <ul aria-label={t("summary:sources")} className="summary-sources">
      {sources.map((source) => (
        <li key={source.passageId}>
          <a
            href="#meeting-playback"
            className="summary-source"
            aria-label={t("summary:sourceAt", { time: timestamp(source.startMs) })}
            onClick={(event) => { event.preventDefault(); onSeek(source.startMs); }}
          >{timestamp(source.startMs)}</a>
        </li>
      ))}
    </ul>
  );
}

function StructuredSummary({ summary, onSeek }: { summary: MeetingSummary; onSeek: (startMs: number) => void }) {
  const { t } = useT();
  return (
    <>
      <h3 className="summary-label">{t("summary:mainTopic")}</h3>
      <p className="summary-paragraph">{summary.topic}</p>
      <h3 className="summary-label">{t("summary:detailedKeyPoints")}</h3>
      <ol className="summary-blocks">
        {summary.keyPoints.filter(isBlock).map((block, index) => (
          <li key={index} className="summary-block">
            <h4 className="summary-block-title">{block.title}</h4>
            <ul className="summary-items">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  {item.text}
                  {item.subItems.length > 0 && (
                    <ul className="summary-subitems">
                      {item.subItems.map((sub, subIndex) => <li key={subIndex}>{sub}</li>)}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
            <SourceChips sources={block.sources} onSeek={onSeek} />
          </li>
        ))}
      </ol>
      {summary.conclusion && (
        <>
          <h3 className="summary-label">{t("summary:conclusion")}</h3>
          <p className="summary-paragraph">{summary.conclusion}</p>
        </>
      )}
    </>
  );
}

// A meeting change also cancels pending requests.
export function SummaryPanel(props: SummaryPanelProps) {
  return <MeetingSummaryPanel key={props.meetingId} {...props} />;
}

function MeetingSummaryPanel({
  meetingId, onSeek, transcriptReady = true, onSummaryChange, expectAutoRequest = false, onSignalChange,
  progress = { audioSeconds: null, createdAt: null, stageStartedAt: null }, refreshKey = 0,
}: SummaryPanelProps) {
  const { t } = useT();
  const [summary, setSummary] = useState<MeetingSummary | null>(null);
  useEffect(() => { onSummaryChange?.(summary); }, [summary, onSummaryChange]);
  const [request, setRequest] = useState<SummaryRequestStatus | null>(null);
  const [acceptedRequest, setAcceptedRequest] = useState<SummaryRequestStatus | null>(null);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [requestError, setRequestError] = useState(false);
  const mounted = useRef(false);
  const expectRef = useRef(expectAutoRequest);
  expectRef.current = expectAutoRequest;
  const summaryRef = useRef<MeetingSummary | null>(null);
  summaryRef.current = summary;
  const seenRefreshKey = useRef(refreshKey);

  // Look again as soon as an automatic request becomes likely (not on mount: the first load covers it).
  const expectedBefore = useRef(expectAutoRequest);
  useEffect(() => {
    if (expectAutoRequest && !expectedBefore.current) setReload((value) => value + 1);
    expectedBefore.current = expectAutoRequest;
  }, [expectAutoRequest]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // A refresh caused by a new speaker name is silent: if it fails, the summary already shown stays.
    const keepOnError = seenRefreshKey.current !== refreshKey;
    seenRefreshKey.current = refreshKey;
    setLoadError(false);

    async function refresh() {
      if (cancelled || document.hidden || inFlight) return;
      clearTimeout(timer);
      inFlight = true;
      try {
        const [artifact, latest] = await Promise.all([
          getMeetingSummary(meetingId), getLatestSummaryRequest(meetingId),
        ]);
        if (cancelled) return;
        setSummary(artifact);
        setRequest(latest);
        setLoadError(false);
        const awaitingAuto = expectRef.current && !artifact && !latest;
        if ((latest?.status === "pending" || latest?.status === "running" || awaitingAuto) && !document.hidden) {
          timer = setTimeout(() => void refresh(), 5000);
        }
      } catch {
        if (!cancelled && !(keepOnError && summaryRef.current)) setLoadError(true);
      } finally {
        inFlight = false;
        if (!cancelled) setLoading(false);
      }
    }

    function onVisibilityChange() {
      clearTimeout(timer);
      if (!document.hidden) void refresh();
    }

    if (acceptedRequest && (acceptedRequest.status === "pending" || acceptedRequest.status === "running")) {
      if (!document.hidden) timer = setTimeout(() => void refresh(), 5000);
    } else {
      void refresh();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [meetingId, acceptedRequest, reload, refreshKey]);

  async function generate() {
    setSubmitting(true);
    setRequestError(false);
    try {
      const accepted = await requestMeetingSummary(meetingId);
      if (!mounted.current) return;
      setRequest(accepted);
      setAcceptedRequest(accepted);
      setLoading(false);
    } catch {
      if (mounted.current) setRequestError(true);
    } finally {
      if (mounted.current) setSubmitting(false);
    }
  }

  const currentRequest = request && (!summary || request.generation > summary.generation) ? request : null;
  const waiting = currentRequest?.status === "pending" || currentRequest?.status === "running";
  const resultUnavailable = currentRequest?.status === "succeeded";
  const signal: SummarySignal | null = loading ? null
    : waiting || submitting ? "waiting"
      : summary || currentRequest || loadError ? "settled" : "none";
  useEffect(() => { if (signal) onSignalChange?.(signal); }, [signal, onSignalChange]);

  if (loading) return (
    <div className="summary-panel">
      <p role="status" className="summary-state">{t("summary:loading")}</p>
    </div>
  );
  if (loadError || resultUnavailable) return (
    <div className="summary-panel">
      <div className="summary-notice summary-notice--error">
        <p role="alert">{loadError ? t("summary:loadFailed") : t("summary:resultUnavailable")}</p>
        <Button variant="secondary" size="sm" onClick={() => {
          setAcceptedRequest(null);
          setReload((value) => value + 1);
        }}>{t("summary:retry")}</Button>
      </div>
    </div>
  );

  return (
    <section aria-label={t("summary:tab")} className="summary-panel">
      {requestError && <p role="alert" className="summary-notice summary-notice--error">{t("summary:requestFailed")}</p>}
      {submitting ? <p role="status" className="summary-state">{t("summary:submitting")}</p> : waiting ? (
        <GeneratingSkeleton progress={progress} />
      ) : currentRequest?.status === "failed" ? (
        <div className="summary-notice summary-notice--error">
          <p role="alert">{t("summary:failed")} {summaryFailureText(currentRequest.failureCause)}</p>
          {transcriptReady && <Button variant="secondary" size="sm" onClick={() => void generate()}>{t("summary:retry")}</Button>}
        </div>
      ) : summary ? (
        <>
          {summary.schemaVersion === 2 ? <StructuredSummary summary={summary} onSeek={onSeek} /> : (
            <>
              <h3 className="summary-label">{t("summary:topic")}</h3>
              <p className="summary-topic">{summary.topic}</p>
              <h3 className="summary-label">{t("summary:keyPoints")}</h3>
              <ul className="summary-points">
                {summary.keyPoints.map((point, index) => (
                  <li key={index} className="summary-point">
                    <p>{typeof point === "string" ? point : isBlock(point) ? point.title : point.text}</p>
                    {typeof point !== "string" && <SourceChips sources={point.sources} onSeek={onSeek} />}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : transcriptReady ? (
        <div className="summary-empty">
          <p>{t("summary:empty")}</p>
          <Button variant="primary" size="sm" onClick={() => void generate()}>{t("summary:generate")}</Button>
        </div>
      ) : (
        <div className="summary-waiting">
          <p className="summary-waiting-note"><strong>{t("summary:waitingTitle")}</strong> {t("summary:waitingBody")}</p>
          <SkeletonLines lines={5} lastWidth="84%" />
        </div>
      )}
    </section>
  );
}
