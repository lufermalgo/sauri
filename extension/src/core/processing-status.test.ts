import { expect, it } from "vitest";
import * as fc from "fast-check";
import { resolveProcessingStatus } from "./processing-status";
import type { RecordingCompletion } from "../recording-db";

const record: RecordingCompletion = {
  sessionId: "session", meetingId: "meeting", recordingId: "recording", provider: "meet",
  capturedTabId: 1, status: "upload_succeeded", updatedAt: 1,
};
const meeting = { meeting_id: "meeting", recording_id: "recording", process_state: "completed" };
const transcript = { meeting_id: "meeting", transcript_id: "transcript" };
const playback = { meeting_id: "meeting", video_presence: "muxed", muxed_video_source: { url: "https://example.invalid/video" } };

it("requires the persisted identity on status even when assets are present (100 generated IDs)", () => {
  fc.assert(fc.property(fc.uuid(), fc.uuid(), (meetingId, recordingId) => {
    const saved = { ...record, meetingId, recordingId };
    expect(resolveProcessingStatus(saved, { ...meeting, meeting_id: meetingId, recording_id: recordingId },
      { ...transcript, meeting_id: meetingId }, { ...playback, meeting_id: meetingId }))
      .toBe("processing_succeeded");
    expect(resolveProcessingStatus(saved, { ...meeting, meeting_id: meetingId, recording_id: "other" },
      { ...transcript, meeting_id: meetingId }, { ...playback, meeting_id: meetingId }))
      .toBeUndefined();
  }), { numRuns: 100 });
});

it("rejects absent, unknown, empty and mismatched video while accepting a usable separate source", () => {
  for (const video of [
    { ...playback, video_presence: "absent" }, { ...playback, video_presence: "unknown" },
    { ...playback, muxed_video_source: { url: "" } }, { ...playback, meeting_id: "other" },
    { ...playback, video_presence: "separate", muxed_video_source: null, video_sources: [] },
  ]) expect(resolveProcessingStatus(record, meeting, transcript, video)).toBe("processing_assets_unavailable");
  expect(resolveProcessingStatus(record, meeting, transcript, {
    ...playback, video_presence: "separate", muxed_video_source: null, video_sources: [{ url: "https://example.invalid/video" }],
  })).toBe("processing_succeeded");
  expect(resolveProcessingStatus(record, meeting, { ...transcript, meeting_id: "other" }, playback))
    .toBe("processing_assets_unavailable");
});
