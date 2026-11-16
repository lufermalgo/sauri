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
import { isSignInRequired, onSessionChanged, readSessionToken } from "../core/session-token";
import { ensureAccessToken } from "../core/api/session-refresh";
import { portalDestination } from "./portal";
import { useT } from "../i18n";
import { MicrophoneWarning } from "./components/MicrophoneWarning";
import { DEFAULT_RECORDING_SETTINGS, parseRecordingSettings, readRecordingSettings, RECORDING_SETTINGS_KEY, writeRecordingSettings } from "./recordingSettings";
import { RESOLUTION_DIMENSIONS } from "../core/resolution";
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
  const { t } = useT();
  const [sessionExpired, setSessionExpired] = useState(false);
  const [settings, setSettings] = useState(DEFAULT_RECORDING_SETTINGS);
  const [settingsReady, setSettingsReady] = useState(false);
  const [settingsPending, setSettingsPending] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const settingsPendingCount = useRef(0);
  const settingsQueue = useRef<Promise<boolean>>(Promise.resolve(true));
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
    // After a reload or a browser restart only the refresh token is left: sign back in silently.
    const active = Boolean(await readSessionToken()) || (await ensureAccessToken(DEFAULT_BACKEND_URL)).status === "ok";
    // Queued uploads that found no valid token reuse the session-expired prompt.
    if (!active && await isSignInRequired()) setSessionExpired(true);
    setSessionActive(active);
  }, []);

  useEffect(() => {
    void loadSession();
    return onSessionChanged(() => { void loadSession(); });
  }, [loadSession]);


  useEffect(() => {
    let cancelled = false;
    let changed = false;
    const load = async () => {
      try {
        const loaded = await readRecordingSettings();
        if (!cancelled && !changed) setSettings(loaded);
      } catch { if (!cancelled) setSettingsError(t("panel:settingsLoadError")); }
      finally { if (!cancelled) setSettingsReady(true); }
    };
    const listener = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === "local" && changes[RECORDING_SETTINGS_KEY]) {
        changed = true;
        setSettings(parseRecordingSettings(changes[RECORDING_SETTINGS_KEY].newValue));
      }
    };
    chrome.storage.onChanged.addListener(listener);
    void load();
    return () => { cancelled = true; chrome.storage.onChanged.removeListener(listener); };
  }, []);

  // Changes are written one after another so a quick second choice never overwrites the first.
  const saveSettings = (change: Partial<RecordingSettings>): Promise<boolean> => {
    if (!settingsReady) return Promise.resolve(false);
    settingsPendingCount.current += 1;
    setSettingsPending(true);
    setSettingsError(null);
    const task = settingsQueue.current.then(async () => {
      try {
        setSettings(await writeRecordingSettings(change));
        return true;
      } catch { setSettingsError(t("panel:settingsError")); return false; }
      finally {
        settingsPendingCount.current -= 1;
        if (settingsPendingCount.current === 0) setSettingsPending(false);
      }
    });
    settingsQueue.current = task;
    return task;
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
          deviceId: device.deviceId || "default", label: device.label || `${t("panel:microphone")} ${index + 1}`,
        }));
        setMicrophones(options);
        setSelectedMicrophone(previous => previous ?? options[0]);
        setMicrophoneError(null);
      } catch (error) {
        if (cancelled) return;
        if (error instanceof DOMException && error.name === "NotAllowedError") {
          const fallback = { deviceId: "default", label: t("panel:defaultMicrophone") };
          setMicrophones([fallback]);
          setSelectedMicrophone(previous => previous ?? fallback);
        } else {
          setMicrophoneError(t("panel:microphoneListError"));
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
        // A stale 401 (sent before the user signed in again) leaves the newer token in
        // place: load with it instead of asking for credentials a second time.
        if (await readSessionToken()) { void loadNotes(); return; }
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
    setStartError(t("panel:permissionNeeded"));
    try { await chrome.runtime.openOptionsPage(); }
    catch { setStartError(t("panel:permissionOpenError")); }
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
        resolution: RESOLUTION_DIMENSIONS[settings.resolution],
        micDeviceId: enableMicrophone ? selectedMicrophone?.deviceId ?? "default" : null,
      });
      if (result?.ok) setStartError(null);
      else if (result?.reason === "microphone-permission") {
        await openMicrophonePermission();
      } else if (result?.reason === "current-tab-unavailable" || (source === "current-tab" && result?.reason === "no-tab-audio")) {
        setStartError(t("panel:tabError"));
      } else if (result?.reason === "no-tab-audio") {
        setStartError(t("panel:audioError"));
      } else if (result?.reason === "unsupported-surface") {
        setStartError(t("panel:surfaceError"));
      } else if (result?.reason !== "cancelled" && result?.reason !== "busy") {
        setStartError(t("panel:startError"));
      }
    } catch {
      setStartError(t("panel:startError"));
    } finally {
      startPendingRef.current = false;
      setStartingSource(null);
    }
  }, [selectedMicrophone, selecting, captureState, currentTabAvailable, openMicrophonePermission, microphonesReady, projectionReady, microphoneEnabled, settings, settingsReady]);

  const changeSettings = (change: Partial<RecordingSettings>) => {
    void saveSettings(change).then(saved => {
      // The floating bar lives on the recorded page: tell the service worker so it shows or hides at once.
      if (saved && captureState === "recording" && "showControlBar" in change) {
        void Promise.resolve(chrome.runtime.sendMessage({ type: "recording-settings-changed" })).catch(() => undefined);
      }
    });
  };

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
    } catch { setStartError(t("panel:commandError")); }
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
    } catch { setStartError(t("panel:commandError")); }
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
    catch { setStartError(t("panel:commandError")); }
  };

  const handleLogin = useCallback(
    async (email: string, password: string) => {
      await loginApi(email, password, DEFAULT_BACKEND_URL);
      setSessionExpired(false);
      setSessionActive(true);
      // Uploads queued while signed out resume now instead of waiting for the next alarm.
      void Promise.resolve(chrome.runtime.sendMessage({ type: "session-restored" })).catch(() => undefined);
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
      {selecting && <p role="status">{startingSource === "picker" ? t("panel:choosing") : t("panel:starting")}</p>}
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
        settings={settings}
        onChangeSettings={changeSettings}
        settingsDisabled={!settingsReady || selecting}
        settingsError={settingsError}
        onToggleCapture={() => { if (captureState === "idle") void handleNewNote(); else void sendControl("stop-capture"); }}
        currentTabAvailable={currentTabAvailable}
        onPause={() => { void sendControl(backgroundState.paused ? "resume-capture" : "pause-capture"); }}
        onCancel={() => { void sendControl("cancel-capture"); }}
        paused={backgroundState.paused}
        tabTitle={backgroundState.meetingTitle}
        overlayUnavailable={backgroundState.overlayAvailable === false}
        recordedVideo={backgroundState.videoPresence === "muxed"}
        recordedMicrophone={backgroundState.micDeviceId ? microphones.find(mic => mic.deviceId === backgroundState.micDeviceId)?.label ?? t("panel:microphone") : undefined}
        commandPending={commandPending}
        elapsedTimeMs={timerAvailable ? elapsedTimeMs : undefined}
        microphoneError={microphoneError}
        selecting={selecting || !microphonesReady || !projectionReady || !settingsReady || settingsPending || modePending}
        startError={selecting ? null : startError}
      />}
      {!completionVisible && captureState === "idle" && <NotesList state={notesViewState} notes={notesRequest.data ?? notesRequest.previous ?? []} onRetry={loadNotes} onOpenNote={handleOpenNote} />}
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
