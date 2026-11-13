import React, { useEffect, useMemo, useRef, useState } from "react";
import type { PlaybackManifest, TimedPassage } from "../api";
import type { PresentationTurn } from "../transcript-turns";
import {
  PlaybackController,
  type MediaSourceOption,
  type PlaybackState,
} from "./PlaybackController";

interface PlaybackTranscriptPassage extends TimedPassage {
  presentationTurnId?: string;
  speakerLabel?: string;
  speakerColor?: string;
}

interface MeetingPlaybackViewProps {
  manifest: PlaybackManifest | null;
  passages: PlaybackTranscriptPassage[];
  presentationTurns?: Array<PresentationTurn & { speakerColor?: string }>;
  loading: boolean;
  error: string | null;
  onRefreshManifest?: (currentTimeMs: number) => Promise<PlaybackManifest>;
  onSeekToReady?: (seekTo: ((timeMs: number) => void) | undefined) => void;
}

const INITIAL_STATE: PlaybackState = {
  currentTimeMs: 0,
  durationMs: null,
  isPlaying: false,
  playbackRate: 1,
  volume: 1,
  muted: false,
  activePassageId: null,
  selectedSourceId: null,
};

const ACTIVE_PASSAGE_STYLE: React.CSSProperties = {
  backgroundColor: "#fef3c7",
  fontWeight: 600,
};

function isPlayablePassage(passage: TimedPassage): passage is TimedPassage & { startMs: number; endMs: number } {
  return passage.startMs !== null && passage.endMs !== null &&
    Number.isFinite(passage.startMs) && Number.isFinite(passage.endMs) &&
    passage.startMs >= 0 && passage.endMs > passage.startMs;
}

function formatTime(milliseconds: number): string {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function MeetingPlaybackView({
  manifest,
  passages,
  presentationTurns,
  loading,
  error,
  onRefreshManifest,
  onSeekToReady,
}: MeetingPlaybackViewProps) {
  const [state, setState] = useState<PlaybackState>(INITIAL_STATE);
  const [mediaReady, setMediaReady] = useState(false);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const [currentManifest, setCurrentManifest] = useState(manifest);
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const controllerRef = useRef<PlaybackController | null>(null);
  const passageRefs = useRef(new Map<string, HTMLLIElement>());
  const previousActivePassage = useRef<string | null>(null);
  const savedTimeMs = useRef(0);
  const refreshAttempted = useRef(false);

  useEffect(() => {
    setCurrentManifest(manifest);
    setPlaybackError(null);
    setMediaReady(false);
    refreshAttempted.current = false;
  }, [manifest]);

  const mediaMode = currentManifest?.video_presence;
  const playableVideoSources = useMemo<MediaSourceOption[]>(() => {
    if (mediaMode !== "separate" || !currentManifest) return [];
    return currentManifest.video_sources.flatMap((source) => {
      if (source.video_offset_ms === null || source.video_offset_ms === undefined ||
          !Number.isFinite(source.video_offset_ms)) return [];
      return [{
        id: source.source_id,
        label: source.quality_label || source.width && source.height
          ? source.quality_label || `${source.width}×${source.height}`
          : source.source_id,
        videoSrc: source.url,
        audioSrc: currentManifest.audio_source.url,
        mimeType: source.mime_type,
        videoOffsetMs: source.video_offset_ms,
      }];
    });
  }, [currentManifest, mediaMode]);

  const isMuxed = mediaMode === "muxed" && currentManifest?.muxed_video_source !== null &&
    currentManifest?.muxed_video_source !== undefined;
  const isSeparateWithVideo = mediaMode === "separate" && playableVideoSources.length > 0;
  const needsAudio = mediaMode !== "muxed";
  const mediaElement = isMuxed ? videoRef.current : audioRef.current;

  useEffect(() => {
    const audio = audioRef.current;
    const video = isSeparateWithVideo ? videoRef.current : undefined;
    const clock = isMuxed ? videoRef.current : audio;
    if (!currentManifest || !clock || (needsAudio && !audio)) {
      controllerRef.current?.destroy();
      controllerRef.current = null;
      setState(INITIAL_STATE);
      return;
    }

    if (isMuxed && currentManifest.muxed_video_source) {
      clock.src = currentManifest.muxed_video_source.url;
    } else if (audio) {
      audio.src = currentManifest.audio_source.url;
    }

    const controller = new PlaybackController({
      videoPresence: currentManifest.video_presence,
      audioElement: isMuxed ? clock : audio!,
      ...(video ? { videoElement: video } : {}),
      passages: passages.filter(isPlayablePassage),
      mediaSources: playableVideoSources,
      onError: (cause) => {
        setPlaybackError(cause instanceof Error ? cause.message : "Playback failed");
      },
    });
    controllerRef.current = controller;
    onSeekToReady?.((timeMs) => controller.seekTo(timeMs));
    if (savedTimeMs.current > 0) controller.seekTo(savedTimeMs.current);
    setState(controller.getState());
    setMediaReady(false);

    const updateState = () => {
      const updated = controller.getState();
      savedTimeMs.current = updated.currentTimeMs;
      setState(updated);
    };
    const onMetadata = () => {
      setMediaReady(Number.isFinite(clock.duration) && clock.duration >= 0);
      updateState();
    };
    const events = ["timeupdate", "seeked", "play", "pause", "ended", "ratechange", "volumechange"];
    events.forEach((event) => clock.addEventListener(event, updateState));
    clock.addEventListener("loadedmetadata", onMetadata);
    clock.addEventListener("durationchange", onMetadata);
    if (Number.isFinite(clock.duration) && clock.duration >= 0) onMetadata();

    return () => {
      events.forEach((event) => clock.removeEventListener(event, updateState));
      clock.removeEventListener("loadedmetadata", onMetadata);
      clock.removeEventListener("durationchange", onMetadata);
      controller.destroy();
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        onSeekToReady?.(undefined);
      }
    };
  }, [currentManifest, isMuxed, isSeparateWithVideo, needsAudio, onSeekToReady, passages, playableVideoSources]);

  const activeSource = passages.find((passage) => passage.id === state.activePassageId);
  const activePresentationId = activeSource?.presentationTurnId ?? activeSource?.id ?? null;

  useEffect(() => {
    if (activePresentationId === previousActivePassage.current) return;
    previousActivePassage.current = activePresentationId;
    if (activePresentationId) passageRefs.current.get(activePresentationId)?.scrollIntoView?.({ block: "nearest" });
  }, [activePresentationId]);

  async function refreshSource() {
    if (refreshAttempted.current) {
      controllerRef.current?.pause();
      setPlaybackError("Unable to reload meeting media. Playback has stopped.");
      return;
    }
    refreshAttempted.current = true;
    if (!onRefreshManifest) {
      controllerRef.current?.pause();
      setPlaybackError("Unable to load meeting media.");
      return;
    }
    const currentTimeMs = controllerRef.current?.getState().currentTimeMs ?? savedTimeMs.current;
    savedTimeMs.current = currentTimeMs;
    try {
      const refreshedManifest = await onRefreshManifest(currentTimeMs);
      setCurrentManifest(refreshedManifest);
    } catch {
      controllerRef.current?.pause();
      setPlaybackError("Unable to reload meeting media. Playback has stopped.");
    }
  }

  function handleMediaError() {
    void refreshSource();
  }

  const controlsDisabled = loading || !mediaReady || !currentManifest || Boolean(error);
  if (loading && !currentManifest) return <p role="status">Loading meeting playback…</p>;
  if (!currentManifest) {
    return <p role="status">Meeting media is unavailable.</p>;
  }

  const activeError = error ?? playbackError;
  const hasPlayableMedia = isMuxed || needsAudio;
  const durationMs = state.durationMs;
  // Display rows never become clock intervals. Only the first original interval
  // is used for the row's play action; the controller keeps every source bound.
  const displayPassages = presentationTurns?.map((turn) => {
    const firstInterval = passages.find((passage) => passage.presentationTurnId === turn.id && isPlayablePassage(passage));
    return {
      id: turn.id,
      text: turn.text,
      sequence: turn.sequence,
      speakerLabel: turn.speakerLabel,
      speakerColor: turn.speakerColor,
      startMs: firstInterval?.startMs ?? null,
      endMs: firstInterval?.endMs ?? null,
    };
  }) ?? passages;
  const activePassage = displayPassages.find((passage) => passage.id === activePresentationId);
  const activePassagePreview = activePassage
    ? `${activePassage.speakerLabel ?? "Speaker N"} · ${formatTime(isPlayablePassage(activePassage) ? activePassage.startMs : state.currentTimeMs)} · ${activePassage.text}`
    : null;

  return (
    <section aria-label="Meeting playback">
      <h2>Meeting playback</h2>
      {loading && <p role="status">Loading playback metadata…</p>}
      {activeError && <p role="alert">{activeError}</p>}
      {!hasPlayableMedia && <p role="status">Meeting media is unavailable.</p>}
      {isMuxed ? (
        <video
          ref={videoRef}
          data-testid="playback-media"
          aria-label="Meeting recording"
          controls
          onError={handleMediaError}
        />
      ) : (
        <>
          <audio
            ref={audioRef}
            data-testid="playback-audio"
            aria-label="Meeting audio"
            onError={handleMediaError}
          />
          {isSeparateWithVideo && (
            <video
              ref={videoRef}
              data-testid="playback-video"
              aria-label="Meeting video"
              muted
              playsInline
              onError={handleMediaError}
            />
          )}
        </>
      )}
      {!isMuxed && isSeparateWithVideo && playableVideoSources.length > 1 && (
        <label>
          Video quality
          <select
            aria-label="Video quality"
            value={state.selectedSourceId ?? playableVideoSources[0]?.id ?? ""}
            disabled={controlsDisabled}
            onChange={(event) => controllerRef.current?.selectSource(event.currentTarget.value)}
          >
            {playableVideoSources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}
          </select>
        </label>
      )}
      <div aria-label="Playback controls">
        <button
          type="button"
          aria-label="Pause"
          disabled={controlsDisabled}
          onClick={() => {
            controllerRef.current?.pause();
            setState(controllerRef.current?.getState() ?? INITIAL_STATE);
          }}
        >Pause</button>
        <button
          type="button"
          aria-label="Play or resume playback"
          disabled={controlsDisabled}
          onClick={() => {
            void controllerRef.current?.resume();
            setState(controllerRef.current?.getState() ?? INITIAL_STATE);
          }}
        >Play</button>
        <label>
          Seek
          <input
            type="range"
            aria-label="Seek"
            min="0"
            max={durationMs ?? 0}
            step="100"
            value={state.currentTimeMs}
            disabled={controlsDisabled || durationMs === null}
            onChange={(event) => controllerRef.current?.seekTo(Number(event.currentTarget.value))}
          />
        </label>
        <span aria-live="off">{formatTime(state.currentTimeMs)} / {durationMs === null ? "--:--" : formatTime(durationMs)}</span>
        <label>
          Playback speed
          <select
            aria-label="Playback speed"
            value={state.playbackRate}
            disabled={controlsDisabled}
            onChange={(event) => controllerRef.current?.setPlaybackRate(Number(event.currentTarget.value))}
          >
            {[0.5, 0.75, 1, 1.25, 1.5, 2].map((rate) => <option key={rate} value={rate}>{rate}×</option>)}
          </select>
        </label>
        <label>
          Volume
          <input
            type="range"
            aria-label="Volume"
            min="0"
            max="1"
            step="0.05"
            value={state.volume}
            disabled={controlsDisabled}
            onChange={(event) => controllerRef.current?.setVolume(Number(event.currentTarget.value))}
          />
        </label>
        <button
          type="button"
          aria-label={state.muted ? "Unmute" : "Mute"}
          disabled={controlsDisabled}
          onClick={() => controllerRef.current?.setMuted(!state.muted)}
        >{state.muted ? "Unmute" : "Mute"}</button>
      </div>
      {displayPassages.length === 0 ? (
        <p>No transcript or empty transcript.</p>
      ) : (
        <details>
          <summary>
            Playback passages ({displayPassages.length})
            {activePassage && activePassagePreview && (
              <span
                aria-current="true"
                data-testid="active-playback-passage"
                title={`Current passage: ${activePassagePreview}`}
                style={{
                  ...ACTIVE_PASSAGE_STYLE,
                  display: "block",
                  marginTop: "0.25rem",
                  maxWidth: "min(100%, 48rem)",
                  overflow: "hidden",
                  padding: "0.25rem",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {activePassagePreview}
              </span>
            )}
          </summary>
          <ol aria-label="Transcript passages">
            {displayPassages.map((passage) => {
              const playable = isPlayablePassage(passage);
              const isActive = activePresentationId === passage.id;
              return (
                <li
                  key={passage.id}
                  style={isActive ? ACTIVE_PASSAGE_STYLE : undefined}
                  data-passage-id={passage.id}
                  data-active={isActive ? "true" : "false"}
                  ref={(element) => {
                    if (element) passageRefs.current.set(passage.id, element);
                    else passageRefs.current.delete(passage.id);
                  }}
                  aria-current={isActive ? "true" : undefined}
                >
                  <span
                    data-testid="transcript-speaker-label"
                    style={{ color: passage.speakerColor ?? "#6b7280", fontWeight: 600, marginRight: "0.5rem" }}
                  >
                    {passage.speakerLabel ?? "Speaker N"}
                  </span>
                  {playable && <span>{formatTime(passage.startMs)} </span>}
                  <span>{passage.text}</span>
                  {playable && (
                    <button
                      type="button"
                      aria-label={`Play ${passage.text}`}
                      disabled={controlsDisabled}
                      onClick={() => void controllerRef.current?.playPassage(passage)}
                    >Play passage</button>
                  )}
                </li>
              );
            })}
          </ol>
        </details>
      )}
    </section>
  );
}
