// Detail_View composition — Req. 6.1-6.6, 7.1-7.6, 14.3
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { SummarySpace } from "./SummarySpace";
import { TranscriptPanel } from "./TranscriptPanel";
import { TranscriptSearch } from "./TranscriptSearch";
import { SpeakingTimeView } from "./SpeakingTimeView";
import { readMeetingId } from "../core/detailUrl";
import { deriveViewState } from "../core/view";
import {
  getTranscript,
  getDiarization,
  getMeeting,
  DEFAULT_BACKEND_URL,
  NotFoundError,
} from "../core/api/client";
import { attributeSpeaker } from "../core/interventions";
import { sortInterventions } from "../core/order";
import { calculateSpeakingTime } from "../core/speakerTime";
import { displayTitle } from "../core/notes";
import type {
  RemoteRequest,
  SpeechTurnDTO,
  SpeakerDTO,
  SpeakerAssignmentDTO,
} from "../core/types";
import type { TranscriptSearchResult } from "../core/search";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS } from "../core/design/tokens";
import "../core/design/tokens.css";

const INITIAL_REQUEST = { phase: "initial", data: null, previous: null } as const;
// Stable empty references: avoids `?? []` creating a new array on every
// render, which would break downstream memoization and cause a render loop
// (effect -> setState -> render -> new reference -> effect...).
const NO_TURNS: SpeechTurnDTO[] = [];
const NO_SPEAKERS: SpeakerDTO[] = [];

// While the Meeting is still processing (queued/joining/recording/
// transcribing), the transcript/diarization don't exist yet (404) without
// that meaning "unavailable" — it just means "not yet". It retries silently
// (without going through the "loading" state) until a terminal state.
const TERMINAL_STATES = new Set(["completed", "failed"]);
const POLLING_INTERVAL_MS = 3000;
const MAX_POLLING_ATTEMPTS = 20; // ~60s

export function DetailApp() {
  const meetingId = useMemo(() => readMeetingId(window.location.href), []);

  const [transcriptRequest, setTranscriptRequest] = useState<RemoteRequest<SpeechTurnDTO>>(
    INITIAL_REQUEST
  );
  const [diarizationRequest, setDiarizationRequest] = useState<RemoteRequest<SpeakerDTO>>(
    INITIAL_REQUEST
  );
  const [assignments, setAssignments] = useState<SpeakerAssignmentDTO[]>([]);
  const [searchResult, setSearchResult] = useState<TranscriptSearchResult>({
    interventions: [],
    matchingTurnIds: [],
    firstMatchId: null,
  });

  const loadTranscript = useCallback(
    async (silent = false) => {
      if (!meetingId) return;
      if (!silent) {
        setTranscriptRequest((prev) => ({ phase: "in_progress", data: null, previous: prev.data }));
      }
      try {
        const transcript = await getTranscript(meetingId, DEFAULT_BACKEND_URL);
        setTranscriptRequest({ phase: "success", data: transcript.segments, previous: null });
      } catch (err) {
        if (err instanceof NotFoundError) {
          setTranscriptRequest({ phase: "success", data: [], previous: null });
        } else {
          setTranscriptRequest((prev) => ({ phase: "failure", data: null, previous: prev.data }));
        }
      }
    },
    [meetingId]
  );

  const loadDiarization = useCallback(
    async (silent = false) => {
      if (!meetingId) return;
      if (!silent) {
        setDiarizationRequest((prev) => ({ phase: "in_progress", data: null, previous: prev.data }));
      }
      try {
        const diarization = await getDiarization(meetingId, DEFAULT_BACKEND_URL);
        setDiarizationRequest({ phase: "success", data: diarization.speakers, previous: null });
        setAssignments(diarization.assignments);
      } catch (err) {
        if (err instanceof NotFoundError) {
          setDiarizationRequest({ phase: "success", data: [], previous: null });
          setAssignments([]);
        } else {
          setDiarizationRequest((prev) => ({ phase: "failure", data: null, previous: prev.data }));
        }
      }
    },
    [meetingId]
  );

  useEffect(() => {
    if (!meetingId) return;
    let canceled = false;

    async function pollingCycle() {
      await loadTranscript();
      await loadDiarization();

      for (let attempt = 0; attempt < MAX_POLLING_ATTEMPTS && !canceled; attempt++) {
        const meeting = await getMeeting(meetingId!, DEFAULT_BACKEND_URL).catch(() => null);
        // If the status query fails (missing note, network error), retrying
        // for 60s makes no sense — polling stops.
        if (canceled || !meeting || TERMINAL_STATES.has(meeting.processState)) break;

        await new Promise((resolve) => setTimeout(resolve, POLLING_INTERVAL_MS));
        if (canceled) break;
        await loadTranscript(true);
        await loadDiarization(true);
      }
    }

    pollingCycle();
    return () => {
      canceled = true;
    };
  }, [meetingId, loadTranscript, loadDiarization]);

  const turns = transcriptRequest.data ?? transcriptRequest.previous ?? NO_TURNS;
  const speakers = diarizationRequest.data ?? diarizationRequest.previous ?? NO_SPEAKERS;

  const interventions = useMemo(
    () => sortInterventions(turns.map((turn) => attributeSpeaker(turn, assignments, speakers))),
    [turns, assignments, speakers]
  );

  const speakingTimeEntries = useMemo(
    () => calculateSpeakingTime(turns, assignments, speakers),
    [turns, assignments, speakers]
  );

  if (!meetingId) {
    return (
      <div style={{ padding: SPACING_TOKENS.space5, color: COLOR_TOKENS.text }}>
        <p style={{ color: COLOR_TOKENS.error }}>This note doesn't exist.</p>
      </div>
    );
  }

  const transcriptState = deriveViewState(transcriptRequest);
  const diarizationState = deriveViewState(diarizationRequest);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: SPACING_TOKENS.space5,
        padding: SPACING_TOKENS.space5,
        color: COLOR_TOKENS.text,
        backgroundColor: COLOR_TOKENS.background,
        minHeight: "100vh",
      }}
    >
      <h1 style={{ fontSize: TYPOGRAPHY_TOKENS.textXl, margin: 0 }}>{displayTitle(null)}</h1>

      <SummarySpace />

      <div style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space3 }}>
        <TranscriptSearch interventions={interventions} onResult={setSearchResult} />
        <TranscriptPanel
          state={transcriptState}
          interventions={interventions}
          matchingTurnIds={searchResult.matchingTurnIds}
          firstMatchId={searchResult.firstMatchId}
          onRetry={loadTranscript}
        />
      </div>

      <SpeakingTimeView
        state={diarizationState}
        entries={speakingTimeEntries}
        onRetry={loadDiarization}
      />
    </div>
  );
}
