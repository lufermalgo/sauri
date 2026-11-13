// Side_Panel composition — Req. 1.3, 1.4, 1.5, 1.6, 13.2, 13.3, 13.4
import React, { useCallback, useEffect, useRef, useState } from "react";
import { PanelHeader } from "./components/PanelHeader";
import { CaptureControls, type MicOption } from "./components/CaptureControls";
import { NotesList } from "./components/NotesList";
import { AuthView } from "./components/AuthView";
import { RecordingCompletionStatus } from "./components/RecordingCompletionStatus";
import { applyCaptureEvent } from "../core/capture";
import { deriveViewState } from "../core/view";
import {
  listMeetings,
  login as loginApi,
  deleteMeeting,
  renameMeeting,
  DEFAULT_BACKEND_URL,
} from "../core/api/client";
import { buildDetailUrl } from "../core/detailUrl";
import type { CaptureState, NoteDTO, RemoteRequest } from "../core/types";
import "../core/design/tokens.css";

interface SauriBackgroundState {
  status: "idle" | "pending" | "recording";
  sessionId?: string;
}

function mapCaptureState(status: SauriBackgroundState["status"]): CaptureState {
  if (status === "recording") return "recording";
  return "idle";
}

export function SidePanelApp() {
  const [sessionActive, setSessionActive] = useState<boolean | null>(null);
  const [captureState, setCaptureState] = useState<CaptureState>("idle");
  const [elapsedTimeMs, setElapsedTimeMs] = useState(0);
  const [recordingSessionId, setRecordingSessionId] = useState<string | undefined>();
  const [projectionReady, setProjectionReady] = useState(false);
  const [microphones, setMicrophones] = useState<MicOption[]>([]);
  const [selectedMicrophone, setSelectedMicrophone] = useState<MicOption | undefined>(undefined);
  const [microphoneError, setMicrophoneError] = useState<string | null>(null);
  const [notesRequest, setNotesRequest] = useState<RemoteRequest<NoteDTO>>({
    phase: "initial",
    data: null,
    previous: null,
  });
  const recordingStartRef = useRef<number | null>(null);

  const loadSession = useCallback(async () => {
    const result = await chrome.storage.sync.get("authToken");
    setSessionActive(Boolean(result.authToken));
  }, []);

  useEffect(() => {
    loadSession();
  }, [loadSession]);

  useEffect(() => {
    let cancelled = false;
    let changed = false;
    const loadProjection = async () => {
      try {
        const result = await chrome.storage.session.get("sauriState");
        // A newer storage event wins over the initial asynchronous snapshot.
        if (cancelled || changed) return;
        const state = result.sauriState as SauriBackgroundState | undefined;
        setCaptureState(mapCaptureState(state?.status ?? "idle"));
        setRecordingSessionId(state?.sessionId);
        setProjectionReady(true);
      } catch {
        // No volatile hint: the status component can recover the durable record.
        if (!cancelled && !changed) setProjectionReady(true);
      }
    };
    void loadProjection();

    const listener = (changes: { [key: string]: chrome.storage.StorageChange }, areaName: string) => {
      if (areaName === "session" && changes.sauriState) {
        changed = true;
        const state = changes.sauriState.newValue as SauriBackgroundState | undefined;
        setCaptureState(mapCaptureState(state?.status ?? "idle"));
        setRecordingSessionId(state?.sessionId);
        setProjectionReady(true);
      }
    };
    chrome.storage.onChanged.addListener(listener);
    return () => { cancelled = true; chrome.storage.onChanged.removeListener(listener); };
  }, []);

  useEffect(() => {
    // enumerateDevices() only returns real deviceId/label values if the
    // origin already has microphone permission granted — otherwise they
    // come back empty and offscreen.ts ends up treating the recording as
    // "no microphone" even though the panel shows one selected. That's why
    // the permission is requested first.
    navigator.mediaDevices
      ?.getUserMedia({ audio: true })
      .then((stream) => {
        stream.getTracks().forEach((track) => track.stop());
        return navigator.mediaDevices.enumerateDevices();
      })
      .then((devices) => {
        const audioInputs = devices.filter((d) => d.kind === "audioinput");
        const options = audioInputs.map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Microphone ${i + 1}` }));
        setMicrophones(options);
        setSelectedMicrophone((prev) => prev ?? options[0]);
      })
      .catch((error) => {
        const name = error instanceof DOMException ? error.name : String(error);
        console.error("[sauri] Could not access the microphone:", name, error);
        setMicrophones([]);
        setMicrophoneError(
          name === "NotAllowedError"
            ? "Microphone permission blocked for sauri. Go to chrome://settings/content/microphone, find the sauri extension, set the permission to 'Allow', then reload the extension."
            : name === "NotFoundError"
              ? "No microphone was detected."
              : `Could not access the microphone (${name}).`
        );
      });
  }, []);

  // Recording stopwatch (Req. 3.9)
  useEffect(() => {
    if (captureState === "recording") {
      if (recordingStartRef.current === null) recordingStartRef.current = Date.now();
      const interval = setInterval(() => {
        setElapsedTimeMs(Date.now() - (recordingStartRef.current ?? Date.now()));
      }, 1000);
      return () => clearInterval(interval);
    }
    recordingStartRef.current = null;
    setElapsedTimeMs(0);
  }, [captureState]);

  const loadNotes = useCallback(async () => {
    setNotesRequest((prev) => ({ phase: "in_progress", data: null, previous: prev.data }));
    try {
      const notes = await listMeetings(DEFAULT_BACKEND_URL);
      setNotesRequest({ phase: "success", data: notes, previous: null });
    } catch {
      setNotesRequest((prev) => ({ phase: "failure", data: null, previous: prev.data }));
    }
  }, []);

  useEffect(() => {
    if (sessionActive) loadNotes();
  }, [sessionActive, loadNotes]);

  // Refreshes "My Notes" when a recording finishes (recording/stopping → idle),
  // since the upload is processed in the background without the panel knowing otherwise.
  const previousStateRef = useRef<CaptureState>("idle");
  useEffect(() => {
    if (previousStateRef.current !== "idle" && captureState === "idle") {
      loadNotes();
    }
    previousStateRef.current = captureState;
  }, [captureState, loadNotes]);

  const handleNewNote = useCallback(() => {
    setCaptureState((prev) => applyCaptureEvent(prev, "start"));
    chrome.runtime.sendMessage({
      type: "start-capture",
      resolution: { width: 1280, height: 720 },
      micDeviceId: selectedMicrophone?.deviceId ?? null,
    });
  }, [selectedMicrophone]);

  const handleToggleCapture = useCallback(() => {
    if (captureState === "idle") {
      handleNewNote();
    } else if (captureState === "recording") {
      setCaptureState((prev) => applyCaptureEvent(prev, "stop"));
      chrome.runtime.sendMessage({ type: "stop-capture" });
    }
  }, [captureState, handleNewNote]);

  const handleOpenSettings = useCallback(() => {
    chrome.runtime.openOptionsPage?.();
  }, []);

  const handleOpenNote = useCallback((meetingId: string) => {
    const url = buildDetailUrl(meetingId);
    chrome.tabs.create({ url: chrome.runtime.getURL(url) });
  }, []);

  const handleDeleteNote = useCallback(
    async (meetingId: string) => {
      try {
        await deleteMeeting(meetingId, DEFAULT_BACKEND_URL);
        await loadNotes();
      } catch (error) {
        console.error("[sauri] Could not delete the note:", error);
      }
    },
    [loadNotes]
  );

  const handleRenameNote = useCallback(
    async (meetingId: string, newTitle: string) => {
      try {
        await renameMeeting(meetingId, newTitle, DEFAULT_BACKEND_URL);
        await loadNotes();
      } catch (error) {
        console.error("[sauri] Could not rename the note:", error);
      }
    },
    [loadNotes]
  );

  const handleLogin = useCallback(
    async (email: string, password: string) => {
      await loginApi(email, password, DEFAULT_BACKEND_URL);
      setSessionActive(true);
    },
    []
  );

  if (sessionActive === null) {
    return null;
  }

  if (!sessionActive) {
    return <AuthView onLogin={handleLogin} />;
  }

  const notesViewState = deriveViewState(notesRequest);

  return (
    <div
      style={{
        minWidth: "320px",
        overflowX: "auto",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <PanelHeader captureState={captureState} onNewNote={handleNewNote} />
      <CaptureControls
        captureState={captureState}
        microphones={microphones}
        selectedMicrophone={selectedMicrophone}
        onSelectMicrophone={setSelectedMicrophone}
        onToggleCapture={handleToggleCapture}
        onOpenSettings={handleOpenSettings}
        elapsedTimeMs={elapsedTimeMs}
        microphoneError={microphoneError}
      />
      {projectionReady && <RecordingCompletionStatus sessionId={recordingSessionId} />}
      <NotesList
        state={notesViewState}
        notes={notesRequest.data ?? notesRequest.previous ?? []}
        onRetry={loadNotes}
        onOpenNote={handleOpenNote}
        onDeleteNote={handleDeleteNote}
        onRenameNote={handleRenameNote}
      />
    </div>
  );
}
