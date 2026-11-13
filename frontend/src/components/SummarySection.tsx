import { useCallback, useEffect, useRef, useState } from "react";
import type { MeetingSummary, SummaryRequestStatus, SummaryTemplate } from "@sauri/shared-types";
import { getLatestSummaryRequest, getSummary, getSummaryRequest, listTemplates, requestSummary } from "../api";

interface Props {
  meetingId: string;
  hasTranscript: boolean;
}

const active = (request: SummaryRequestStatus | null) =>
  request?.status === "pending" || request?.status === "running";

export function SummarySection({ meetingId, hasTranscript }: Props) {
  const [summary, setSummary] = useState<MeetingSummary | null>(null);
  const [request, setRequest] = useState<SummaryRequestStatus | null>(null);
  const [templates, setTemplates] = useState<SummaryTemplate[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [summaryError, setSummaryError] = useState(false);
  const [requestError, setRequestError] = useState(false);
  const [statusError, setStatusError] = useState(false);
  const [templateError, setTemplateError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const lifecycle = useRef(0);

  useEffect(() => {
    const epoch = ++lifecycle.current;
    setLoading(true);
    setSummary(null);
    setRequest(null);
    setSummaryError(false);
    setRequestError(false);
    setStatusError(false);
    setTemplateError(false);
    setTemplates([]);
    setSelected("");
    void Promise.allSettled([getSummary(meetingId), getLatestSummaryRequest(meetingId), listTemplates()])
      .then(([artifact, latest, choices]) => {
        if (epoch !== lifecycle.current) return;
        if (artifact.status === "fulfilled") setSummary(artifact.value);
        else if (!(artifact.reason instanceof Error && artifact.reason.message.startsWith("Error 404"))) setSummaryError(true);
        if (latest.status === "fulfilled") setRequest(latest.value);
        else if (!(latest.reason instanceof Error && latest.reason.message.startsWith("Error 404"))) setRequestError(true);
        if (choices.status === "fulfilled") {
          setTemplates(choices.value);
          // The empty value means the API resolves the configured personal default.
          // Without one, the user must choose explicitly; never infer a fallback.
          setSelected(choices.value.some((item) => item.isDefault) ? "" : "unselected");
        } else setTemplateError(true);
        setLoading(false);
      });
    return () => { lifecycle.current++; };
  }, [meetingId]);

  const refreshStatus = useCallback(async (eventId: string) => {
    const epoch = lifecycle.current;
    try {
      const result = await getSummaryRequest(meetingId, eventId);
      if (epoch !== lifecycle.current) return;
      setRequest(result);
      setStatusError(false);
      if (result.status === "succeeded") {
        try {
          const updated = await getSummary(meetingId);
          if (epoch !== lifecycle.current) return;
          if (updated) {
            setSummary(updated);
            setSummaryError(false);
          } else setSummaryError(true);
        } catch { if (epoch === lifecycle.current) setSummaryError(true); }
      }
    } catch {
      // Network/status errors are not terminal generation failures.
      if (epoch === lifecycle.current) setStatusError(true);
    }
  }, [meetingId]);

  useEffect(() => {
    if (!active(request) || statusError) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      if (cancelled) return;
      void refreshStatus(request!.eventId);
    }, 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [request, statusError, refreshStatus]);

  async function submit() {
    const epoch = lifecycle.current;
    setSubmitting(true);
    setRequestError(false);
    try {
      const accepted = await requestSummary(meetingId, selected ? { templateId: selected } : {});
      if (epoch !== lifecycle.current) return;
      setStatusError(false);
      setRequest(accepted);
    } catch { if (epoch === lifecycle.current) setRequestError(true); }
    finally { if (epoch === lifecycle.current) setSubmitting(false); }
  }

  const hasDefault = templates.some((item) => item.isDefault);
  return (
    <section aria-label="Summary">
      <h2>Summary</h2>
      {loading ? <p>Loading summary...</p> : (
        <>
          {summary && <article>
            <h3>{summary.topic}</h3>
            <ol>{summary.keyPoints.map((point, index) => <li key={index}>{point}</li>)}</ol>
          </article>}
          {!summary && !summaryError && !requestError && !active(request) && request?.status !== "failed" &&
            <p>No summary available for this meeting yet.</p>}
          {summaryError && <p role="alert">Unable to load summary.</p>}
          {requestError && <p role="alert">Unable to load or request summary status.</p>}
          {request && <p role="status">{request.status === "failed" ? "Summary generation failed." : `Summary ${request.status}.`}</p>}
          {statusError && <div role="alert">Unable to check summary status.
            <button type="button" onClick={() => void refreshStatus(request!.eventId)}>Retry status</button>
          </div>}
          {templateError && <p role="alert">Unable to load templates.</p>}
          {hasTranscript && !templateError && <>
            <label htmlFor="summary-template">Template</label>
            <select id="summary-template" value={selected} onChange={(event) => setSelected(event.target.value)}>
              {hasDefault ? <option value="">{templates.find((item) => item.isDefault)!.name} (default)</option> :
                <option value="unselected">Select a template</option>}
              {templates.filter((item) => !item.isDefault).map((item) =>
                <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <button type="button" disabled={submitting || active(request) || selected === "unselected" || templates.length === 0}
              onClick={() => void submit()}>Request summary</button>
          </>}
        </>
      )}
    </section>
  );
}
