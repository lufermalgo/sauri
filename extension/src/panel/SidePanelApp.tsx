// Side_Panel composition — Req. 1.3, 1.4, 1.5, 1.6, 13.2, 13.3, 13.4
import React, { useCallback, useEffect, useRef, useState } from "react";
import { PanelHeader } from "./components/PanelHeader";
import { CaptureControls, type CaptureSourceChoice, type MicOption } from "./components/CaptureControls";
import { NotesList } from "./components/NotesList";
import { AuthView } from "./components/AuthView";
import { RecordingCompletionStatus } from "./components/RecordingCompletionStatus";
import { applyCaptureEvent, canCaptureCurrentTab } from "../core/capture";
import { deriveViewState } from "../core/view";
import {
  listMeetings,
  login as loginApi,
  InvalidSessionError,
  DEFAULT_BACKEND_URL,
} from "../core/api/client";
import { portalDestination } from "./portal";
import { panelCopy as copy } from "./copy";
import { RecordingSettingsView } from "./components/RecordingSettingsView";
import { MicrophoneWarning } from "./components/MicrophoneWarning";
import { DEFAULT_RECORDING_SETTINGS, parseRecordingSettings } from "./recordingSettings";
import type { RecordingSettings } from "../core/types";
import "./panel.css";
import type { CaptureState, CaptureSource, CaptureStartResult, NoteDTO, RemoteRequest } from "../core/types";
import "../core/design/base.css";

interface SauriBackgroundState {
  status: "idle" | "pending" | "recording";
  sessionId?: string;
  paused?: boolean;
  meetingTitle?: string;
  captureMode?: "screen_audio" | "audio_only";
  micDeviceId?: string | null;
  videoPresence?: "muxed" | "absent";
  overlayAvailable?: boolean;
}

function mapCaptureState(status: SauriBackgroundState["status"]): CaptureState {
  if (status === "recording") return "recording";
  return "idle";
}

export function SidePanelApp() {
  const [sessionExpired, setSessionExpired] = useState(false);
  const [settings, setSettings] = useState(DEFAULT_RECORDING_SETTINGS);
  const [settingsReady, setSettingsReady] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsPending, setSettingsPending] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const settingsPendingRef = useRef(false);
  const [microphoneEnabled, setMicrophoneEnabled] = useState(true);
  const [captureMode, setCaptureMode] = useState<"screen_audio" | "audio_only">("screen_audio");
  const [currentTabSelected, setCurrentTabSelected] = useState(false);
  const [modePending, setModePending] = useState(false);
  const modePendingRef = useRef(false);
  const [warningSource, setWarningSource] = useState<CaptureSource | null>(null);
  const [skipWarning, setSkipWarning] = useState(false);
  const [backgroundState, setBackgroundState] = useState<SauriBackgroundState>({ status: "idle" });
  const [commandPending, setCommandPending] = useState(false);
  const commandPendingRef = useRef(false);
  const [completionVisible, setCompletionVisible] = useState(false);
  const [sessionActive, setSessionActive] = useState<boolean | null>(null);
  const [captureState, setCaptureState] = useState<CaptureState>("idle");
  const [startingSource, setStartingSource] = useState<CaptureSource | null>(null);
  const selecting = startingSource !== null;
  const [currentTabAvailable, setCurrentTabAvailable] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const startPendingRef = useRef(false);
  const [timerAvailable, setTimerAvailable] = useState(false);
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
  const recordingElapsedRef = useRef(0);

  const loadSession = useCallback(async () => {
    const result = await chrome.storage.sync.get("authToken");
    setSessionActive(Boolean(result.authToken));
  }, []);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);


  useEffect(() => {
    let cancelled = false;
    let changed = false;
    const load = async () => {
      try {
        const result = await chrome.storage.local.get("recordingSettings");
        if (!cancelled && !changed) setSettings(parseRecordingSettings(result.recordingSettings));
      } catch { if (!cancelled) setSettingsError(copy.settingsLoadError); }
      finally { if (!cancelled) setSettingsReady(true); }
    };
    const listener = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === "local" && changes.recordingSettings) {
        changed = true;
        setSettings(parseRecordingSettings(changes.recordingSettings.newValue));
      }
    };
    chrome.storage.onChanged.addListener(listener);
    void load();
    return () => { cancelled = true; chrome.storage.onChanged.removeListener(listener); };
  }, []);

  const saveSettings = async (change: Partial<RecordingSettings>): Promise<boolean> => {
    if (settingsPendingRef.current || !settingsReady) return false;
    settingsPendingRef.current = true;
    setSettingsPending(true);
    setSettingsError(null);
    try {
      const result = await chrome.storage.local.get("recordingSettings");
      const next = { ...parseRecordingSettings(result.recordingSettings), ...change };
      await chrome.storage.local.set({ recordingSettings: next });
      setSettings(next);
      return true;
    } catch { setSettingsError(copy.settingsError); return false; }
    finally { settingsPendingRef.current = false; setSettingsPending(false); }
  };

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
        setCaptureMode(state?.captureMode ?? "screen_audio");
        setBackgroundState(state ?? { status: "idle" });
        if (state?.status === "recording") setSettingsOpen(false);
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
        // An already-active snapshot has no start time. Only time an observed start.
        if (state?.status !== "recording") setTimerAvailable(false);
        else if (changes.sauriState.oldValue?.status !== "recording") setTimerAvailable(true);
        setBackgroundState(state ?? { status: "idle" });
        if (state?.captureMode) setCaptureMode(state.captureMode);
        if (state?.status === "recording") setSettingsOpen(false);
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
          deviceId: device.deviceId || "default", label: device.label || `${copy.microphone} ${index + 1}`,
        }));
        setMicrophones(options);
        setSelectedMicrophone(previous => previous ?? options[0]);
        setMicrophoneError(null);
      } catch (error) {
        if (cancelled) return;
        if (error instanceof DOMException && error.name === "NotAllowedError") {
          const fallback = { deviceId: "default", label: copy.defaultMicrophone };
          setMicrophones([fallback]);
          setSelectedMicrophone(previous => previous ?? fallback);
        } else {
          setMicrophoneError(copy.microphoneListError);
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

  // This local stopwatch excludes pauses; it is not a persisted media duration.
  useEffect(() => {
    if (captureState !== "recording") {
      if (captureState === "idle") {
        recordingElapsedRef.current = 0;
        setElapsedTimeMs(0);
      }
      return;
    }
    if (backgroundState.paused || !timerAvailable) return;
    const started = Date.now();
    const previous = recordingElapsedRef.current;
    const interval = setInterval(() => setElapsedTimeMs(previous + Date.now() - started), 1000);
    return () => {
      clearInterval(interval);
      recordingElapsedRef.current = previous + Date.now() - started;
    };
  }, [captureState, backgroundState.paused, timerAvailable]);

  const loadNotes = useCallback(async () => {
    setNotesRequest((prev) => ({ phase: "in_progress", data: null, previous: prev.data }));
    try {
      const notes = await listMeetings(DEFAULT_BACKEND_URL);
      setNotesRequest({ phase: "success", data: notes, previous: null });
    } catch (error) {
      if (error instanceof InvalidSessionError) {
        setSessionExpired(true);
        setSessionActive(false);
        setNotesRequest({ phase: "initial", data: null, previous: null });
        return;
      }
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
    setStartError(copy.permissionNeeded);
    try { await chrome.runtime.openOptionsPage(); }
    catch { setStartError(copy.permissionOpenError); }
  }, []);

  const handleStartCapture = useCallback(async (source: CaptureSource, enableMicrophone = microphoneEnabled, confirmed = false) => {
    if (modePendingRef.current || !settingsReady || !microphonesReady || !projectionReady || startPendingRef.current || selecting || captureState !== "idle") return;
    if (source === "current-tab" && !currentTabAvailable) return;
    if (!enableMicrophone && !settings.skipMicWarning && !confirmed) {
      setSkipWarning(false);
      setWarningSource(source);
      return;
    }
    startPendingRef.current = true;
    setStartingSource(source);
    try {
      if (enableMicrophone) {
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
        micDeviceId: enableMicrophone ? selectedMicrophone?.deviceId ?? "default" : null,
      });
      if (result?.ok) setStartError(null);
      else if (result?.reason === "microphone-permission") {
        await openMicrophonePermission();
      } else if (result?.reason === "current-tab-unavailable" || (source === "current-tab" && result?.reason === "no-tab-audio")) {
        setStartError(copy.tabError);
      } else if (result?.reason === "no-tab-audio") {
        setStartError(copy.audioError);
      } else if (result?.reason === "unsupported-surface") {
        setStartError(copy.surfaceError);
      } else if (result?.reason !== "cancelled" && result?.reason !== "busy") {
        setStartError(copy.startError);
      }
    } catch {
      setStartError(copy.startError);
    } finally {
      startPendingRef.current = false;
      setStartingSource(null);
    }
  }, [selectedMicrophone, selecting, captureState, currentTabAvailable, openMicrophonePermission, microphonesReady, projectionReady, microphoneEnabled, settings, settingsReady]);

  const handleNewNote = useCallback(() => handleStartCapture(currentTabSelected ? "current-tab" : "picker"), [handleStartCapture, currentTabSelected]);

  const sendControl = async (type: "stop-capture" | "pause-capture" | "resume-capture" | "cancel-capture") => {
    if (commandPendingRef.current) return;
    commandPendingRef.current = true;
    setCommandPending(true);

    setStartError(null);
    try {
      const result = await chrome.runtime.sendMessage({ type });
      if (!result?.ok) throw new Error("Control rejected");
      if (type === "stop-capture") setCaptureState(previous => previous === "recording" ? applyCaptureEvent(previous, "stop") : previous);
    } catch { setStartError(copy.commandError); }
    finally { commandPendingRef.current = false; setCommandPending(false); }
  };

  const changeMode = async (mode: "screen_audio" | "audio_only") => {
    if (modePendingRef.current) return;
    modePendingRef.current = true;
    setModePending(true);
    try {
      const result = await chrome.runtime.sendMessage({ type: "set-capture-mode", captureMode: mode });
      if (!result?.ok) throw new Error("Mode rejected");
      setCaptureMode(mode);
      setStartError(null);
    } catch { setStartError(copy.commandError); }
    finally { modePendingRef.current = false; setModePending(false); }
  };

  // "This tab" is a start shortcut, not a background capture mode: it records the tab with video.
  const changeSource = (source: CaptureSourceChoice) => {
    setCurrentTabSelected(source === "current-tab");
    const mode = source === "current-tab" ? "screen_audio" : source;
    if (mode !== captureMode) void changeMode(mode);
  };

  const handleOpenNote = async (meetingId: string) => {
    try { await chrome.tabs.create({ url: portalDestination(meetingId) }); }
    catch { setStartError(copy.commandError); }
  };

  const handleLogin = useCallback(
    async (email: string, password: string) => {
      await loginApi(email, password, DEFAULT_BACKEND_URL);
      setSessionExpired(false);
      setSessionActive(true);
    },
    []
  );

  if (sessionActive === null) {
    return null;
  }

  if (!sessionActive) {
    return <AuthView onLogin={handleLogin} sessionExpired={sessionExpired} />;
  }

  const notesViewState = deriveViewState(notesRequest);

  return <div className="panel-app">
    <PanelHeader captureState={captureState} paused={backgroundState.paused} />
    <main className="panel-main panel-stack">
      {settingsOpen ? <RecordingSettingsView settings={settings} onChange={change => { void saveSettings(change); }} onBack={() => setSettingsOpen(false)} pending={settingsPending || !settingsReady} error={settingsError} /> : <>
        {selecting && <p role="status">{startingSource === "picker" ? copy.choosing : copy.starting}</p>}
        {projectionReady && captureState === "idle" && <RecordingCompletionStatus sessionId={recordingSessionId} onVisibleChange={setCompletionVisible} />}
        {(!completionVisible || captureState !== "idle") && <CaptureControls
          captureState={captureState}
          microphones={microphones}
          selectedMicrophone={selectedMicrophone}
          onSelectMicrophone={setSelectedMicrophone}
          microphoneEnabled={microphoneEnabled}
          onToggleMicrophone={() => setMicrophoneEnabled(value => !value)}
          source={currentTabSelected ? "current-tab" : captureMode}
          onChangeSource={changeSource}
          onOpenSettings={() => setSettingsOpen(true)}
          onToggleCapture={() => { if (captureState === "idle") void handleNewNote(); else void sendControl("stop-capture"); }}
          currentTabAvailable={currentTabAvailable}
          onPause={() => { void sendControl(backgroundState.paused ? "resume-capture" : "pause-capture"); }}
          onCancel={() => { void sendControl("cancel-capture"); }}
          paused={backgroundState.paused}
          tabTitle={backgroundState.meetingTitle}
          overlayUnavailable={backgroundState.overlayAvailable === false}
          recordedVideo={backgroundState.videoPresence === "muxed"}
          recordedMicrophone={backgroundState.micDeviceId ? microphones.find(mic => mic.deviceId === backgroundState.micDeviceId)?.label ?? copy.microphone : undefined}
          commandPending={commandPending}
          elapsedTimeMs={timerAvailable ? elapsedTimeMs : undefined}
          microphoneError={microphoneError}
          selecting={selecting || !microphonesReady || !projectionReady || !settingsReady || settingsPending || modePending}
          startError={selecting ? null : startError}
        />}
        {!completionVisible && captureState === "idle" && <NotesList state={notesViewState} notes={notesRequest.data ?? notesRequest.previous ?? []} onRetry={loadNotes} onOpenNote={handleOpenNote} />}
        {settingsError && <p role="alert">{settingsError}</p>}
      </>}
    </main>
    {warningSource && <MicrophoneWarning pending={settingsPending} error={settingsError} skip={skipWarning} onSkip={setSkipWarning} onDismiss={() => setWarningSource(null)} onContinue={enable => { void (async () => {
      if (skipWarning && !await saveSettings({ skipMicWarning: true })) return;
      const source = warningSource;
      setWarningSource(null);
      setMicrophoneEnabled(enable);
      await handleStartCapture(source, enable, true);
    })(); }} />}
  </div>;
}
