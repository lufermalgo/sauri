export type VideoPresence = "muxed" | "separate" | "absent" | "unknown";

export interface TimedPassage {
  id: string;
  startMs: number;
  endMs: number;
  text: string;
}

export interface MediaSourceOption {
  id: string;
  label: string;
  videoSrc: string | null;
  audioSrc: string;
  mimeType: string | null;
  videoOffsetMs: number;
}

export interface PlaybackState {
  currentTimeMs: number;
  durationMs: number | null;
  isPlaying: boolean;
  playbackRate: number;
  volume: number;
  muted: boolean;
  activePassageId: string | null;
  selectedSourceId: string | null;
}

export interface PlaybackControllerOptions {
  videoPresence: VideoPresence;
  audioElement: HTMLMediaElement;
  videoElement?: HTMLMediaElement;
  passages: readonly TimedPassage[];
  videoOffsetMs?: number | null;
  mediaSources?: readonly MediaSourceOption[];
  onError?: (error: unknown) => void;
}

const DRIFT_THRESHOLD_SECONDS = 0.25;

export function findPassageAt(
  passages: readonly TimedPassage[],
  currentTimeMs: number,
): TimedPassage | null {
  if (!Number.isFinite(currentTimeMs)) return null;
  return passages.find(
    ({ startMs, endMs }) =>
      Number.isFinite(startMs) && Number.isFinite(endMs) && startMs < endMs &&
      currentTimeMs >= startMs && currentTimeMs < endMs,
  ) ?? null;
}

export class PlaybackController {
  private readonly audio: HTMLMediaElement;
  private readonly video: HTMLMediaElement | undefined;
  private readonly passages: readonly TimedPassage[];
  private readonly onError: ((error: unknown) => void) | undefined;
  private readonly sources: readonly MediaSourceOption[];
  private readonly listeners: Array<[string, EventListener]> = [];
  private offsetMs: number | null;
  private intervalEndMs: number | null = null;
  private state: PlaybackState;

  constructor(options: PlaybackControllerOptions) {
    this.audio = options.audioElement;
    this.passages = options.passages;
    this.onError = options.onError;
    this.video = options.videoPresence === "separate" ? options.videoElement : undefined;
    this.sources = options.videoPresence === "separate"
      ? (options.mediaSources ?? []).filter(
        (source) => source.videoSrc !== null && Number.isFinite(source.videoOffsetMs),
      )
      : [];

    const initialSource = this.sources[0];
    this.offsetMs = initialSource?.videoOffsetMs ?? options.videoOffsetMs ?? null;
    if (this.video) {
      this.video.muted = true;
      if (initialSource?.videoSrc) this.video.src = initialSource.videoSrc;
    }

    this.state = {
      currentTimeMs: this.toMilliseconds(this.audio.currentTime),
      durationMs: Number.isFinite(this.audio.duration) ? this.toMilliseconds(this.audio.duration) : null,
      isPlaying: !this.audio.paused,
      playbackRate: this.audio.playbackRate,
      volume: this.audio.volume,
      muted: this.audio.muted,
      activePassageId: findPassageAt(this.passages, this.toMilliseconds(this.audio.currentTime))?.id ?? null,
      selectedSourceId: this.isVideoPlayable() ? initialSource?.id ?? null : null,
    };

    for (const event of ["timeupdate", "seeked", "loadedmetadata", "durationchange", "play", "pause", "ended", "ratechange", "volumechange"]) {
      this.listen(this.audio, event, () => {
        if (event === "timeupdate" || event === "seeked") {
          this.synchronizeVideo();
          this.stopAtIntervalEnd();
        }
        if (event === "ended") this.video?.pause();
        this.refreshState();
      });
    }
    if (this.video) {
      this.listen(this.video, "error", () => this.reportError(this.video?.error ?? new Error("Video playback failed")));
    }
  }

  getState(): PlaybackState {
    return { ...this.state };
  }

  /** A manual seek cancels any interval being played. */
  seekTo(timeMs: number): void {
    if (!Number.isFinite(timeMs)) return;
    this.intervalEndMs = null;
    this.audio.currentTime = Math.max(0, timeMs) / 1000;
    this.synchronizeVideo();
    this.refreshState();
  }

  async playPassage(passage: TimedPassage): Promise<void> {
    this.seekTo(passage.startMs);
    await this.resume();
  }

  /** Seeks to `startMs`, plays and pauses at `endMs`; replaces any previous interval. */
  async playInterval(startMs: number, endMs: number): Promise<void> {
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || startMs < 0 || endMs <= startMs) return;
    this.seekTo(startMs);
    this.intervalEndMs = endMs;
    await this.resume();
  }

  pause(): void {
    this.intervalEndMs = null;
    this.audio.pause();
    this.video?.pause();
    this.refreshState();
  }

  async resume(): Promise<void> {
    const videoShouldPlay = this.shouldPlayVideoAt(this.audio.currentTime);
    try {
      const requests: Promise<void>[] = [Promise.resolve(this.audio.play())];
      if (videoShouldPlay && this.video) requests.push(Promise.resolve(this.video.play()));
      await Promise.all(requests);
      if (this.video && this.isVideoPlayable() && !videoShouldPlay) this.video.pause();
      this.refreshState();
    } catch (error) {
      this.audio.pause();
      this.video?.pause();
      this.state.isPlaying = false;
      this.reportError(error);
    }
  }

  setPlaybackRate(rate: number): void {
    if (!Number.isFinite(rate) || rate <= 0) return;
    this.audio.playbackRate = rate;
    if (this.isVideoPlayable() && this.video) this.video.playbackRate = rate;
    this.state.playbackRate = this.audio.playbackRate;
  }

  setVolume(volume: number): void {
    if (!Number.isFinite(volume)) return;
    this.audio.volume = Math.min(1, Math.max(0, volume));
    this.state.volume = this.audio.volume;
  }

  setMuted(muted: boolean): void {
    this.audio.muted = muted;
    if (this.video) this.video.muted = true;
    this.state.muted = this.audio.muted;
  }

  selectSource(sourceId: string): void {
    const source = this.sources.find(({ id }) => id === sourceId);
    if (!source || !this.video || !source.videoSrc) return;

    const wasPlaying = !this.audio.paused;
    const currentTime = this.audio.currentTime;
    this.video.pause();
    this.video.src = source.videoSrc;
    this.video.muted = true;
    this.video.playbackRate = this.audio.playbackRate;
    this.offsetMs = source.videoOffsetMs;
    this.state.selectedSourceId = source.id;
    this.audio.currentTime = currentTime;
    this.synchronizeVideo();
    if (wasPlaying) void this.resume();
  }

  destroy(): void {
    for (const [event, listener] of this.listeners) this.audio.removeEventListener(event, listener);
    this.listeners.length = 0;
  }

  private listen(element: HTMLMediaElement, event: string, handler: () => void): void {
    const listener: EventListener = () => handler();
    element.addEventListener(event, listener);
    if (element === this.audio) this.listeners.push([event, listener]);
  }

  private stopAtIntervalEnd(): void {
    if (this.intervalEndMs !== null && this.toMilliseconds(this.audio.currentTime) >= this.intervalEndMs) {
      this.pause();
    }
  }

  private refreshState(): void {
    const currentTimeMs = this.toMilliseconds(this.audio.currentTime);
    this.state = {
      ...this.state,
      currentTimeMs,
      durationMs: Number.isFinite(this.audio.duration) ? this.toMilliseconds(this.audio.duration) : null,
      isPlaying: !this.audio.paused,
      playbackRate: this.audio.playbackRate,
      volume: this.audio.volume,
      muted: this.audio.muted,
      activePassageId: findPassageAt(this.passages, currentTimeMs)?.id ?? null,
      selectedSourceId: this.isVideoPlayable() ? this.state.selectedSourceId : null,
    };
  }

  private synchronizeVideo(): void {
    if (!this.video || !this.isVideoPlayable() || this.offsetMs === null) return;
    const audioTime = this.audio.currentTime;
    const targetTime = Math.max(0, audioTime - this.offsetMs / 1000);
    if (Math.abs(this.video.currentTime - targetTime) > DRIFT_THRESHOLD_SECONDS) {
      this.video.currentTime = targetTime;
    }
    this.video.playbackRate = this.audio.playbackRate;
    this.video.muted = true;
    if (this.offsetMs > 0 && audioTime < this.offsetMs / 1000) {
      this.video.pause();
    } else if (!this.audio.paused && this.video.paused) {
      void this.video.play().catch((error: unknown) => {
        this.audio.pause();
        this.video?.pause();
        this.state.isPlaying = false;
        this.reportError(error);
      });
    } else if (this.audio.paused && !this.video.paused) {
      this.video.pause();
    }
  }

  private shouldPlayVideoAt(audioTime: number): boolean {
    return this.isVideoPlayable() && (this.offsetMs ?? 0) <= 0 ||
      this.isVideoPlayable() && audioTime >= (this.offsetMs ?? 0) / 1000;
  }

  private isVideoPlayable(): boolean {
    return this.video !== undefined && this.offsetMs !== null && Number.isFinite(this.offsetMs);
  }

  private toMilliseconds(seconds: number): number {
    return Number.isFinite(seconds) ? Math.round(seconds * 1000) : 0;
  }

  private reportError(error: unknown): void {
    this.onError?.(error);
  }
}
