import React, { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Button, Skeleton, SkeletonLines } from "./ui";
import "../styles/meeting.css";
import { SpeakerTimeline, type TimelineTurn } from "./SpeakerTimeline";
import type { PlaybackManifest } from "../api";
import {
  PlaybackController,
  type MediaSourceOption,
  type PlaybackState,
} from "./PlaybackController";
import { useT } from "../i18n";

interface MeetingPlaybackViewProps {
  timelineTurns?: TimelineTurn[];
  keyPointTimes?: number[];
  manifest: PlaybackManifest | null;
  loading: boolean;
  error: string | null;
  onRefreshManifest?: (currentTimeMs: number) => Promise<PlaybackManifest>;
  onSeekToReady?: (seekTo: ((timeMs: number, play?: boolean) => void) | undefined) => void;
  onPlayIntervalReady?: (playInterval: ((startMs: number, endMs: number) => Promise<void>) | undefined) => void;
  onPauseReady?: (pause: (() => void) | undefined) => void;
  /** Panel shown beside the video on wide screens and under the timeline otherwise. It never covers the player. */
  sidePanel?: ReactNode;
}

const DEFAULT_VIDEO_RATIO = 16 / 9;

const INITIAL_STATE: PlaybackState = {
  currentTimeMs: 0,
  durationMs: null,
  isPlaying: false,
  playbackRate: 1,
  volume: 1,
  muted: false,
  selectedSourceId: null,
};

function formatTime(milliseconds: number): string {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function MeetingPlaybackView({
  manifest,
  timelineTurns = [],
  keyPointTimes,
  loading,
  error,
  onRefreshManifest,
  onSeekToReady,
  onPlayIntervalReady,
  onPauseReady,
  sidePanel,
}: MeetingPlaybackViewProps) {
  const { t } = useT();
  const [state, setState] = useState<PlaybackState>(INITIAL_STATE);
  const [mediaReady, setMediaReady] = useState(false);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  // Width over height of the picture, so the player is exactly as wide as the video (no empty side bands).
  const [videoRatio, setVideoRatio] = useState(DEFAULT_VIDEO_RATIO);
  const [currentManifest, setCurrentManifest] = useState(manifest);
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const controllerRef = useRef<PlaybackController | null>(null);
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
      mediaSources: playableVideoSources,
      onError: () => {
        setPlaybackError(t("meeting:playbackFailed"));
      },
    });
    controllerRef.current = controller;
    onSeekToReady?.((timeMs, play = false) => {
      controller.seekTo(timeMs);
      if (play) void controller.resume();
    });
    onPlayIntervalReady?.((startMs, endMs) => controller.playInterval(startMs, endMs));
    onPauseReady?.(() => controller.pause());
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
        onPauseReady?.(undefined);
      }
    };
  }, [currentManifest, isMuxed, isSeparateWithVideo, needsAudio, onSeekToReady, onPlayIntervalReady, onPauseReady, playableVideoSources]);

  async function refreshSource() {
    if (refreshAttempted.current) {
      controllerRef.current?.pause();
      setPlaybackError(t("meeting:playbackReloadFailed"));
      return;
    }
    refreshAttempted.current = true;
    if (!onRefreshManifest) {
      controllerRef.current?.pause();
      setPlaybackError(t("meeting:playbackLoadFailed"));
      return;
    }
    const currentTimeMs = controllerRef.current?.getState().currentTimeMs ?? savedTimeMs.current;
    savedTimeMs.current = currentTimeMs;
    try {
      const refreshedManifest = await onRefreshManifest(currentTimeMs);
      setCurrentManifest(refreshedManifest);
    } catch {
      controllerRef.current?.pause();
      setPlaybackError(t("meeting:playbackReloadFailed"));
    }
  }

  function handleMediaError() {
    void refreshSource();
  }

  function handleVideoMetadata(event: React.SyntheticEvent<HTMLVideoElement>) {
    const { videoWidth, videoHeight } = event.currentTarget;
    if (videoWidth > 0 && videoHeight > 0) setVideoRatio(videoWidth / videoHeight);
  }

  const controlsDisabled = loading || !mediaReady || !currentManifest || Boolean(error);
  if (loading && !currentManifest) return <div className="meeting-playback-loading">
    <p role="status">{t("meeting:playbackLoading")}</p>
    <div aria-hidden="true"><Skeleton className="meeting-video-skeleton" radius="md" /><SkeletonLines lines={1} /></div>
    {sidePanel}
  </div>;
  if (!currentManifest) {
    return <>
      <p role={error ? "alert" : "status"}>{error ? t("meeting:playbackLoadFailed") : t("meeting:playbackUnavailable")}</p>
      {sidePanel}
    </>;
  }

  const activeError = error ? t("meeting:playbackLoadFailed") : playbackError;
  const hasPlayableMedia = isMuxed || needsAudio;
  const durationMs = state.durationMs;

  return (
    <div className={`meeting-player${sidePanel && (isMuxed || isSeparateWithVideo) ? " meeting-player--docked" : ""}`}
      style={{ "--meeting-video-ratio": videoRatio } as CSSProperties}>
      {loading && <p role="status">{t("meeting:playbackMetadataLoading")}</p>}
      {activeError && <p role="alert">{activeError}</p>}
      {!hasPlayableMedia && <p role="status">{t("meeting:playbackUnavailable")}</p>}
      {isMuxed ? (
        <video
          ref={videoRef}
          data-testid="playback-media"
          aria-label={t("meeting:recording")}
          playsInline
          onLoadedMetadata={handleVideoMetadata}
          onError={handleMediaError}
        />
      ) : (
        <>
          <audio
            ref={audioRef}
            data-testid="playback-audio"
            aria-label={t("meeting:audio")}
            onError={handleMediaError}
          />
          {isSeparateWithVideo && (
            <video
              ref={videoRef}
              data-testid="playback-video"
              aria-label={t("meeting:video")}
              muted
              playsInline
              onLoadedMetadata={handleVideoMetadata}
              onError={handleMediaError}
            />
          )}
        </>
      )}
      <div className="meeting-player-controls" aria-label={t("meeting:controls")}>
        <Button variant="ghost" className="meeting-control-button"
          type="button"
          aria-label={t("meeting:pause")}
          disabled={controlsDisabled}
          onClick={() => {
            controllerRef.current?.pause();
            setState(controllerRef.current?.getState() ?? INITIAL_STATE);
          }}
        ><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16">
          <path d="M4 3h3v10H4zM9 3h3v10H9z" fill="currentColor" />
        </svg></Button>
        <Button variant="ghost" className="meeting-control-button"
          type="button"
          aria-label={t("meeting:resume")}
          disabled={controlsDisabled}
          onClick={() => {
            void controllerRef.current?.resume();
            setState(controllerRef.current?.getState() ?? INITIAL_STATE);
          }}
        ><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16">
          <path d="M5 3 13 8 5 13Z" fill="currentColor" />
        </svg></Button>
        <label className="meeting-control-seek">
          <span className="meeting-sr-only">{t("meeting:seek")}</span>
          <input
            type="range"
            aria-label={t("meeting:seek")}
            min="0"
            max={durationMs ?? 0}
            step="100"
            value={state.currentTimeMs}
            disabled={controlsDisabled || durationMs === null}
            onChange={(event) => controllerRef.current?.seekTo(Number(event.currentTarget.value))}
          />
        </label>
        <span className="meeting-control-time" aria-live="off">{formatTime(state.currentTimeMs)} / {durationMs === null ? "--:--" : formatTime(durationMs)}</span>
        <label className="meeting-control-speed">
          <span className="meeting-sr-only">{t("meeting:speed")}</span>
          <select
            aria-label={t("meeting:speed")}
            value={state.playbackRate}
            disabled={controlsDisabled}
            onChange={(event) => controllerRef.current?.setPlaybackRate(Number(event.currentTarget.value))}
          >
            {[0.5, 0.75, 1, 1.25, 1.5, 2].map((rate) => <option key={rate} value={rate}>{rate}×</option>)}
          </select>
        </label>
        <label className="meeting-control-volume">
          <span className="meeting-sr-only">{t("meeting:volume")}</span>
          <input
            type="range"
            aria-label={t("meeting:volume")}
            min="0"
            max="1"
            step="0.05"
            value={state.volume}
            disabled={controlsDisabled}
            onChange={(event) => controllerRef.current?.setVolume(Number(event.currentTarget.value))}
          />
        </label>
        <Button variant="ghost" className="meeting-control-button"
          type="button"
          aria-label={state.muted ? t("meeting:unmute") : t("meeting:mute")}
          disabled={controlsDisabled}
          onClick={() => controllerRef.current?.setMuted(!state.muted)}
        ><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16">
          <path d="M2 6h3l4-3v10l-4-3H2Z" fill="currentColor" />
          <path d={state.muted ? "m11 6 4 4m0-4-4 4" : "M11 5q5 3 0 6"}
            fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg></Button>
        {!isMuxed && isSeparateWithVideo && playableVideoSources.length > 1 && (
          <label className="meeting-control-quality">
            <span className="meeting-sr-only">{t("meeting:quality")}</span>
            <select
              aria-label={t("meeting:quality")}
              value={state.selectedSourceId ?? playableVideoSources[0]?.id ?? ""}
              disabled={controlsDisabled}
              onChange={(event) => controllerRef.current?.selectSource(event.currentTarget.value)}
            >
              {playableVideoSources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}
            </select>
          </label>
        )}
      </div>
      <SpeakerTimeline turns={timelineTurns} durationMs={currentManifest.duration_seconds * 1000}
        currentTimeMs={state.currentTimeMs} keyPointTimes={keyPointTimes} disabled={controlsDisabled}
        onSeek={timeMs => controllerRef.current?.seekTo(timeMs)} />
      {sidePanel}
    </div>
  );
}
