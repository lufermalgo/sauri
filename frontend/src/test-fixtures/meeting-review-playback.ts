import type { PlaybackManifest, TimedPassage } from "../api";

// Synthetic, development-only trial data; no authenticated meeting is represented here.
export const trialManifest: PlaybackManifest = {
  meeting_id: "synthetic-trial",
  duration_seconds: 12,
  video_presence: "absent",
  audio_source: {
    source_id: "synthetic-trial-audio",
    url: "/test-fixtures/meeting-review-playback.wav",
    mime_type: "audio/wav",
  },
  muxed_video_source: null,
  video_sources: [],
};

export const trialPassages: TimedPassage[] = [
  { id: "trial-1", sequence: 0, speakerLabel: "Synthetic voice A", text: "First synthetic passage.", startMs: 0, endMs: 4000 },
  { id: "trial-2", sequence: 1, speakerLabel: "Synthetic voice B", text: "Second synthetic passage.", startMs: 4000, endMs: 8000 },
  { id: "trial-3", sequence: 2, speakerLabel: "Synthetic voice A", text: "Third synthetic passage.", startMs: 8000, endMs: 12000 },
];
