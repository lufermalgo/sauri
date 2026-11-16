import { describe, expect, it } from "vitest";
import {
  detectProcessingStage, estimateProgress, expectedStageSeconds, formatElapsed, PROGRESS_CAP,
  roundMinutes, secondsSince, stageLabel, type StageSignals,
} from "./processing-estimate";
import { t } from "./i18n";

const AUDIO_54_MIN = 54 * 60;

describe("expectedStageSeconds", () => {
  it("uses the measured speeds", () => {
    expect(expectedStageSeconds(AUDIO_54_MIN)).toEqual({ transcription: 518.4, speakers: 15, summary: 388.8 });
    // Short recordings keep the one-minute summary floor.
    expect(expectedStageSeconds(120).summary).toBe(60);
  });

  it("is an order of magnitude faster for Parakeet than for Whisper, per hour of audio", () => {
    const hour = 3600;
    expect(expectedStageSeconds(hour, "whisper").transcription / 60).toBeGreaterThanOrEqual(9);
    expect(expectedStageSeconds(hour, "whisper").transcription / 60).toBeLessThanOrEqual(10);
    expect(expectedStageSeconds(hour, "parakeet").transcription / 60).toBeGreaterThanOrEqual(1);
    expect(expectedStageSeconds(hour, "parakeet").transcription / 60).toBeLessThanOrEqual(2);
    // Only transcription depends on the engine.
    expect(expectedStageSeconds(AUDIO_54_MIN, "parakeet").summary).toBe(expectedStageSeconds(AUDIO_54_MIN).summary);
  });
});

describe("estimateProgress", () => {
  it("returns nothing without a usable audio duration", () => {
    for (const audioSeconds of [null, undefined, 0, -5, Number.NaN]) {
      expect(estimateProgress({ stage: "transcription", audioSeconds, elapsedSinceUploadSeconds: 30 })).toBeNull();
    }
  });

  it("estimates transcription from the time since upload", () => {
    const estimate = estimateProgress({ stage: "transcription", audioSeconds: AUDIO_54_MIN, elapsedSinceUploadSeconds: 259.2 })!;
    // Total 922.2 s; half of transcription done.
    expect(estimate.percent).toBe(28);
    expect(estimate.overtime).toBe(false);
    expect(estimate.remainingSeconds).toBeCloseTo(259.2 + 15 + 388.8);
  });

  it("follows the engine: the same time since upload is much further along with Parakeet", () => {
    const input = { stage: "transcription" as const, audioSeconds: AUDIO_54_MIN, elapsedSinceUploadSeconds: 60 };
    const parakeet = estimateProgress({ ...input, engine: "parakeet" })!;
    const whisper = estimateProgress({ ...input, engine: "whisper" })!;
    expect(parakeet.stageExpectedSeconds).toBeCloseTo(97.2);
    expect(parakeet.percent).toBeGreaterThan(whisper.percent);
    expect(estimateProgress({ ...input, engine: "parakeet", elapsedSinceUploadSeconds: 120 })!.overtime).toBe(true);
  });

  it("starts speakers after the nominal transcription time and summary after both", () => {
    const speakers = estimateProgress({ stage: "speakers", audioSeconds: AUDIO_54_MIN, elapsedSinceUploadSeconds: 0 })!;
    expect(speakers.fraction).toBeCloseTo(518.4 / 922.2);
    const summary = estimateProgress({ stage: "summary", audioSeconds: AUDIO_54_MIN, elapsedSinceUploadSeconds: 0 })!;
    expect(summary.fraction).toBeCloseTo(533.4 / 922.2);
    expect(summary.remainingSeconds).toBeCloseTo(388.8);
  });

  it("uses the observed stage start when the page saw it begin", () => {
    const estimate = estimateProgress({
      stage: "speakers", audioSeconds: AUDIO_54_MIN, elapsedSinceUploadSeconds: 5000, stageElapsedSeconds: 5,
    })!;
    expect(estimate.overtime).toBe(false);
    expect(estimate.remainingSeconds).toBeCloseTo(10 + 388.8);
  });

  it("never claims more than 95 % before the work really completes", () => {
    const estimate = estimateProgress({
      stage: "summary", audioSeconds: AUDIO_54_MIN, elapsedSinceUploadSeconds: 0, stageElapsedSeconds: 388,
    })!;
    expect(estimate.fraction).toBe(PROGRESS_CAP);
    expect(estimate.percent).toBe(95);
    expect(estimate.overtime).toBe(false);
  });

  it("reports overtime instead of a remaining time when a stage outlasts its estimate", () => {
    const estimate = estimateProgress({
      stage: "transcription", audioSeconds: 21 * 60, elapsedSinceUploadSeconds: 210,
    })!;
    expect(estimate.overtime).toBe(true);
    expect(estimate.remainingSeconds).toBeNull();
    // The bar rests at the end of the current stage, not at the cap.
    expect(estimate.fraction).toBeCloseTo(201.6 / (201.6 + 15 + 151.2));
  });

  it("handles a late open gracefully: overtime, capped, never negative", () => {
    const estimate = estimateProgress({ stage: "summary", audioSeconds: 600, elapsedSinceUploadSeconds: 86_400 })!;
    expect(estimate.overtime).toBe(true);
    expect(estimate.percent).toBe(95);
    const skewed = estimateProgress({ stage: "transcription", audioSeconds: 600, elapsedSinceUploadSeconds: -30 })!;
    expect(skewed.percent).toBe(0);
    expect(skewed.overtime).toBe(false);
  });
});

describe("detectProcessingStage", () => {
  const signals = (overrides: Partial<StageSignals>): StageSignals => ({
    processState: "transcribing", hasTranscript: false, diarizationNotFound: true, hasDiarization: false,
    summary: "none", ...overrides,
  });

  it.each([
    [signals({ processState: "queued" }), "transcription"],
    [signals({}), "transcription"],
    [signals({ hasTranscript: true }), "speakers"],
    [signals({ processState: "completed", hasTranscript: true }), "speakers"],
    [signals({ processState: "completed", hasTranscript: true, diarizationNotFound: false, hasDiarization: true,
      summary: "waiting" }), "summary"],
    [signals({ processState: "completed", hasTranscript: true, diarizationNotFound: false, hasDiarization: true,
      summary: "expected" }), "summary"],
    [signals({ processState: "completed", hasTranscript: true, diarizationNotFound: false, hasDiarization: true,
      summary: "settled" }), "done"],
    [signals({ processState: "completed", hasTranscript: true, diarizationNotFound: false, hasDiarization: true }), "done"],
    // A diarization service error is not pending identification.
    [signals({ processState: "completed", hasTranscript: true, diarizationNotFound: false }), "done"],
    [signals({ processState: "transcribing", hasTranscript: true, diarizationNotFound: false }), "transcription"],
    [signals({ processState: "failed" }), "failed"],
    [signals({ processState: "joining" }), "live"],
    [signals({ processState: "recording" }), "live"],
    [signals({ processState: "something-new" }), "unknown"],
  ] as const)("detects %o as %s", (input, expected) => {
    expect(detectProcessingStage(input)).toBe(expected);
  });
});

describe("stageLabel", () => {
  it.each([
    ["transcription", "queued", t("processing:queued")],
    ["transcription", "transcribing", t("processing:transcribing")],
    ["speakers", "completed", t("processing:identifying")],
    ["summary", "completed", t("processing:summarizing")],
    ["done", "completed", t("meeting:ready")],
    ["failed", "failed", t("processing:failed")],
    ["live", "joining", t("processing:joining")],
    ["live", "recording", t("processing:recording")],
    ["unknown", "something-new", t("processing:unknown")],
  ] as const)("labels %s (%s)", (stage, processState, label) => {
    expect(stageLabel(stage, processState)).toBe(label);
  });

  it("only says ready when no stage is left, even though ASR already completed", () => {
    for (const stage of ["transcription", "speakers", "summary", "failed"] as const) {
      expect(stageLabel(stage, "completed")).not.toBe(t("meeting:ready"));
    }
  });
});

describe("formatting helpers", () => {
  it("formats elapsed time", () => {
    expect(formatElapsed(130)).toBe("2:10");
    expect(formatElapsed(3 * 3600 + 5)).toBe("3:00:05");
    expect(formatElapsed(-4)).toBe("0:00");
  });

  it("rounds minutes to at least one", () => {
    expect(roundMinutes(10)).toBe(1);
    expect(roundMinutes(313)).toBe(5);
  });

  it("measures time since an ISO date", () => {
    const now = Date.parse("2026-11-15T10:00:00Z");
    expect(secondsSince("2026-11-15T09:59:00Z", now)).toBe(60);
    expect(secondsSince(null, now)).toBeNull();
    expect(secondsSince("not a date", now)).toBeNull();
    expect(secondsSince("2026-11-15T10:01:00Z", now)).toBe(0);
  });
});
