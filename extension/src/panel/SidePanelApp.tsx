// Side_Panel composition — Req. 1.3, 1.4, 1.5, 1.6, 13.2, 13.3, 13.4
import React, { useCallback, useEffect, useRef, useState } from "react";
import { PanelHeader } from "./components/PanelHeader";
import { CaptureControls, type MicOption } from "./components/CaptureControls";
import { NotesList } from "./components/NotesList";
import { AuthView } from "./components/AuthView";
import { RecordingCompletionStatus } from "./components/RecordingCompletionStatus";
import { applyCaptureEvent, canCaptureCurrentTab } from "../core/capture";
import { deriveViewState } from "../core/view";
import {
  listMeetings,
  login as loginApi,
  deleteMeeting,
  renameMeeting,
  DEFAULT_BACKEND_URL,
} from "../core/api/client";
import { buildDetailUrl } from "../core/detailUrl";
import type { CaptureState, CaptureSource, CaptureStartResult, NoteDTO, RemoteRequest } from "../core/types";
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
  const [startingSource, setStartingSource] = useState<CaptureSource | null>(null);
  const selecting = startingSource !== null;
  const [currentTabAvailable, setCurrentTabAvailable] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const startPendingRef = useRef(false);
  const [elapsedTimeMs, setElapsedTimeMs] = useState(0);
  const [recordingSessionId, setRecordingSessionId] = useState<string | undefined>();
  const [projectionReady, setProjectionReady] = useState(false);
  const [microphonesReady, setMicrophonesReady] = useState(false);
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
    let selectionChanged = false;
    const loadProjection = async () => {
      try {
        const result = await chrome.storage.session.get(["sauriState", "sauriCaptureRequest"]);
        // A newer storage event wins over the initial asynchronous snapshot.
        if (cancelled || changed) return;
        const state = result.sauriState as SauriBackgroundState | undefined;
        if (!selectionChanged) setStartingSource(result.sauriCaptureRequest ? result.sauriCaptureRequest.state.pickerSource ?? "picker" : null);
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
      if (areaName === "session" && changes.sauriCaptureRequest) {
        selectionChanged = true;
        const request = changes.sauriCaptureRequest.newValue;
        setStartingSource(request ? request.state.pickerSource ?? "picker" : null);
      }
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
    let cancelled = false;
    const refresh = async () => {
      try {
        // Never prompt from the side panel. Permission is requested in the
        // full options tab when a capture with a configured microphone starts.
        const devices = await navigator.mediaDevices.enumerateDevices();
        if (cancelled) return;
        const options = devices.filter(device => device.kind === "audioinput").map((device, index) => ({
          deviceId: device.deviceId || "default", label: device.label || `Microphone ${index + 1}`,
        }));
        setMicrophones(options);
        setSelectedMicrophone(previous => previous ?? options[0]);
        setMicrophoneError(null);
      } catch (error) {
        if (cancelled) return;
        if (error instanceof DOMException && error.name === "NotAllowedError") {
          const fallback = { deviceId: "default", label: "Default microphone" };
          setMicrophones([fallback]);
          setSelectedMicrophone(previous => previous ?? fallback);
        } else {
          setMicrophoneError("Could not list microphones. Check Settings and try again.");
        }
      } finally {
        if (!cancelled) setMicrophonesReady(true);
      }
    };
    void refresh();
    window.addEventListener("focus", refresh);
    return () => { cancelled = true; window.removeEventListener("focus", refresh); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let latest = 0;
    const refresh = async () => {
      const request = ++latest;
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!cancelled && request === latest) setCurrentTabAvailable(canCaptureCurrentTab(tab?.url));
      } catch {
        if (!cancelled && request === latest) setCurrentTabAvailable(false);
      }
    };
    void refresh();
    chrome.tabs.onActivated.addListener(refresh);
    chrome.tabs.onUpdated.addListener(refresh);
    window.addEventListener("focus", refresh);
    return () => {
      cancelled = true;
      chrome.tabs.onActivated.removeListener(refresh);
      chrome.tabs.onUpdated.removeListener(refresh);
      window.removeEventListener("focus", refresh);
    };
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

  const openMicrophonePermission = useCallback(async () => {
    setStartError("Allow the microphone in the tab that opened, then click Record again.");
    try { await chrome.runtime.openOptionsPage(); }
    catch { setStartError("Open Settings to allow the microphone, then click Record again."); }
  }, []);

  const handleStartCapture = useCallback(async (source: CaptureSource) => {
    if (!microphonesReady || !projectionReady || startPendingRef.current || selecting || captureState !== "idle") return;
    if (source === "current-tab" && !currentTabAvailable) return;
    startPendingRef.current = true;
    setStartingSource(source);
    try {
      if (selectedMicrophone?.deviceId) {
        let granted = false;
        try {
          const permission = await navigator.permissions.query({ name: "microphone" as PermissionName });
          granted = permission.state === "granted";
        } catch { /* Unknown permission must not silently drop the configured microphone. */ }
        if (!granted) {
          await openMicrophonePermission();
          return;
        }
      }
      const result: CaptureStartResult = await chrome.runtime.sendMessage({
        type: "start-capture", source,
        resolution: { width: 1280, height: 720 },
        micDeviceId: selectedMicrophone?.deviceId ?? null,
      });
      if (result?.ok) setStartError(null);
      else if (result?.reason === "microphone-permission") {
        await openMicrophonePermission();
      } else if (result?.reason === "current-tab-unavailable" || (source === "current-tab" && result?.reason === "no-tab-audio")) {
        setStartError("Could not capture this tab. Open sauri from its toolbar icon on a web tab and try again.");
      } else if (result?.reason === "no-tab-audio") {
        setStartError('Choose the tab again and leave "Share tab audio" checked.');
      } else if (result?.reason === "unsupported-surface") {
        setStartError("Choose a Chrome tab, not a window or screen.");
      } else if (result?.reason !== "cancelled" && result?.reason !== "busy") {
        setStartError("Could not start recording. Please try again.");
      }
    } catch {
      setStartError("Could not start recording. Please try again.");
    } finally {
      startPendingRef.current = false;
      setStartingSource(null);
    }
  }, [selectedMicrophone, selecting, captureState, currentTabAvailable, openMicrophonePermission, microphonesReady, projectionReady]);

  const handleNewNote = useCallback(() => handleStartCapture("picker"), [handleStartCapture]);

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
      <PanelHeader captureState={captureState} onNewNote={handleNewNote} selecting={selecting || !microphonesReady || !projectionReady} />
      {selecting && <p role="status">{startingSource === "picker" ? "Choose the tab to record..." : "Starting recording..."}</p>}
      <CaptureControls
        captureState={captureState}
        microphones={microphones}
        selectedMicrophone={selectedMicrophone}
        onSelectMicrophone={setSelectedMicrophone}
        onToggleCapture={handleToggleCapture}
        onCaptureCurrentTab={() => { void handleStartCapture("current-tab"); }}
        currentTabAvailable={currentTabAvailable}
        onOpenSettings={handleOpenSettings}
        elapsedTimeMs={elapsedTimeMs}
        microphoneError={microphoneError}
        selecting={selecting || !microphonesReady || !projectionReady}
        startError={selecting ? null : startError}
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
