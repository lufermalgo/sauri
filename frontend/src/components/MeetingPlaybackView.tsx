import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "./ui";
import { meeting as text } from "../copy/meeting";
import "../styles/meeting.css";
import type { PlaybackManifest, TimedPassage } from "../api";
import {
  PlaybackController,
  type MediaSourceOption,
  type PlaybackState,
} from "./PlaybackController";

interface PlaybackTranscriptPassage extends TimedPassage {
  speakerLabel?: string;
  speakerColor?: string;
}

interface MeetingPlaybackViewProps {
  manifest: PlaybackManifest | null;
  passages: PlaybackTranscriptPassage[];
  loading: boolean;
  error: string | null;
  onRefreshManifest?: (currentTimeMs: number) => Promise<PlaybackManifest>;
  onSeekToReady?: (seekTo: ((timeMs: number) => void) | undefined) => void;
  onPlayIntervalReady?: (playInterval: ((startMs: number, endMs: number) => Promise<void>) | undefined) => void;
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
  loading,
  error,
  onRefreshManifest,
  onSeekToReady,
  onPlayIntervalReady,
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
      onError: () => {
        setPlaybackError(text.playbackFailed);
      },
    });
    controllerRef.current = controller;
    onSeekToReady?.((timeMs) => controller.seekTo(timeMs));
    onPlayIntervalReady?.((startMs, endMs) => controller.playInterval(startMs, endMs));
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
        onPlayIntervalReady?.(undefined);
      }
    };
  }, [currentManifest, isMuxed, isSeparateWithVideo, needsAudio, onSeekToReady, onPlayIntervalReady, passages, playableVideoSources]);

  useEffect(() => {
    if (state.activePassageId === previousActivePassage.current) return;
    previousActivePassage.current = state.activePassageId;
    if (state.activePassageId) passageRefs.current.get(state.activePassageId)?.scrollIntoView?.({ block: "nearest" });
  }, [state.activePassageId]);

  async function refreshSource() {
    if (refreshAttempted.current) {
      controllerRef.current?.pause();
      setPlaybackError(text.playbackReloadFailed);
      return;
    }
    refreshAttempted.current = true;
    if (!onRefreshManifest) {
      controllerRef.current?.pause();
      setPlaybackError(text.playbackLoadFailed);
      return;
    }
    const currentTimeMs = controllerRef.current?.getState().currentTimeMs ?? savedTimeMs.current;
    savedTimeMs.current = currentTimeMs;
    try {
      const refreshedManifest = await onRefreshManifest(currentTimeMs);
      setCurrentManifest(refreshedManifest);
    } catch {
      controllerRef.current?.pause();
      setPlaybackError(text.playbackReloadFailed);
    }
  }

  function handleMediaError() {
    void refreshSource();
  }

  const controlsDisabled = loading || !mediaReady || !currentManifest || Boolean(error);
  if (loading && !currentManifest) return <p role="status">{text.playbackLoading}</p>;
  if (!currentManifest) {
    return <p role={error ? "alert" : "status"}>{error ? text.playbackLoadFailed : text.playbackUnavailable}</p>;
  }

  const activeError = error ? text.playbackLoadFailed : playbackError;
  const hasPlayableMedia = isMuxed || needsAudio;
  const durationMs = state.durationMs;
  const activePassage = passages.find((passage) => passage.id === state.activePassageId);
  const activePassagePreview = activePassage
    ? `${activePassage.speakerLabel ?? text.unknownSpeaker} · ${formatTime(isPlayablePassage(activePassage) ? activePassage.startMs : state.currentTimeMs)} · ${activePassage.text}`
    : null;

  return (
    <section className="meeting-player" aria-label={text.playback}>
      <h2>{text.playback}</h2>
      {loading && <p role="status">{text.playbackMetadataLoading}</p>}
      {activeError && <p role="alert">{activeError}</p>}
      {!hasPlayableMedia && <p role="status">{text.playbackUnavailable}</p>}
      {isMuxed ? (
        <video
          ref={videoRef}
          data-testid="playback-media"
          aria-label={text.recording}
          playsInline
          onError={handleMediaError}
        />
      ) : (
        <>
          <audio
            ref={audioRef}
            data-testid="playback-audio"
            aria-label={text.audio}
            onError={handleMediaError}
          />
          {isSeparateWithVideo && (
            <video
              ref={videoRef}
              data-testid="playback-video"
              aria-label={text.video}
              muted
              playsInline
              onError={handleMediaError}
            />
          )}
        </>
      )}
      {!isMuxed && isSeparateWithVideo && playableVideoSources.length > 1 && (
        <label>
          {text.quality}
          <select
            aria-label={text.quality}
            value={state.selectedSourceId ?? playableVideoSources[0]?.id ?? ""}
            disabled={controlsDisabled}
            onChange={(event) => controllerRef.current?.selectSource(event.currentTarget.value)}
          >
            {playableVideoSources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}
          </select>
        </label>
      )}
      <div className="meeting-player-controls" aria-label={text.controls}>
        <Button variant="secondary"
          type="button"
          aria-label={text.pause}
          disabled={controlsDisabled}
          onClick={() => {
            controllerRef.current?.pause();
            setState(controllerRef.current?.getState() ?? INITIAL_STATE);
          }}
        >{text.pause}</Button>
        <Button variant="secondary"
          type="button"
          aria-label={text.resume}
          disabled={controlsDisabled}
          onClick={() => {
            void controllerRef.current?.resume();
            setState(controllerRef.current?.getState() ?? INITIAL_STATE);
          }}
        >{text.play}</Button>
        <label>
          {text.seek}
          <input
            type="range"
            aria-label={text.seek}
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
          {text.speed}
          <select
            aria-label={text.speed}
            value={state.playbackRate}
            disabled={controlsDisabled}
            onChange={(event) => controllerRef.current?.setPlaybackRate(Number(event.currentTarget.value))}
          >
            {[0.5, 0.75, 1, 1.25, 1.5, 2].map((rate) => <option key={rate} value={rate}>{rate}×</option>)}
          </select>
        </label>
        <label>
          {text.volume}
          <input
            type="range"
            aria-label={text.volume}
            min="0"
            max="1"
            step="0.05"
            value={state.volume}
            disabled={controlsDisabled}
            onChange={(event) => controllerRef.current?.setVolume(Number(event.currentTarget.value))}
          />
        </label>
        <Button variant="secondary"
          type="button"
          aria-label={state.muted ? text.unmute : text.mute}
          disabled={controlsDisabled}
          onClick={() => controllerRef.current?.setMuted(!state.muted)}
        >{state.muted ? text.unmute : text.mute}</Button>
      </div>
      {passages.length === 0 ? (
        <p>{text.emptyPlaybackTranscript}</p>
      ) : (
        <details>
          <summary>
            {text.passages(passages.length)}
            {activePassage && activePassagePreview && (
              <span
                aria-current="true"
                data-testid="active-playback-passage"
                title={text.currentPassage(activePassagePreview)}
                className="meeting-active-preview meeting-turn--active"
              >
                {activePassagePreview}
              </span>
            )}
          </summary>
          <ol aria-label={text.transcriptPassages}>
            {passages.map((passage) => {
              const playable = isPlayablePassage(passage);
              const isActive = state.activePassageId === passage.id;
              return (
                <li
                  key={passage.id}
                  className={isActive ? "meeting-turn--active" : undefined}
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
                    className="meeting-speaker" style={{ color: passage.speakerColor ?? "var(--speaker-unresolved)" }}
                  >
                    {passage.speakerLabel ?? text.unknownSpeaker}
                  </span>
                  {playable && <span>{formatTime(passage.startMs)} </span>}
                  <span>{passage.text}</span>
                  {playable && (
                    <Button variant="secondary"
                      type="button"
                      aria-label={text.playText(passage.text)}
                      disabled={controlsDisabled}
                      onClick={() => void controllerRef.current?.playPassage(passage)}
                    >{text.playPassage}</Button>
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
