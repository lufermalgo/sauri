# Design — Meeting Review Playback

## Summary

The approved feature adds interactive playback to the meeting review view and connects media time to transcript passages. The user must be able to operate standard playback controls, follow the passage associated with the playing time, and start playback at a passage's linked time. The design is limited to those behaviors; it does not define transcript editing, meeting library behavior, or the rest of the meeting view.

1. Extend the web meeting review component with an accessible media player and ordinary controls.
2. Keep playback state in one player controller and use the media element as the authoritative clock.
3. Model timed transcript passages in milliseconds and derive the active highlight from current playback time.
4. Add a per-passage playback control that seeks to its linked start and starts playback.
5. Obtain media source and transcript data through the web API adapter; expose quality selection only when multiple playable source options are available.

## Key Design Decisions

**Use a browser-native HTML media element, with a small React control layer.** The media element already implements seeking, pause/resume, playback rate, volume, mute, and playback events. React should render controls and transcript state around that single source of playback truth. *Rejected alternative:* a custom playback engine duplicates browser media behavior and creates unnecessary synchronization and accessibility risks.

**Use milliseconds for transcript boundaries and seconds only at the media-element boundary.** The backend transcript response provides `segments` with `start_ms` and `end_ms`; the frontend adapter maps those fields to `TimedPassage.startMs` and `endMs`, with conversion to seconds only when interacting with the media element. *Rejected alternative:* mixing units in the UI/domain contract makes passage matching error-prone. This is a technical representation choice, not a requirement that fixes a user-visible time format.

**Add a backend playback-manifest endpoint and use short-lived object-store read URLs after per-meeting authorization.** The web player cannot attach the API's bearer token to a native `<video>` source request, and sending full recording bytes through the current `ObjectStore.get()` (which returns an in-memory `bytes`) would not be a scalable delivery path. `GET /api/v1/meetings/{meeting_id}/playback` therefore requires `get_current_user`, loads the meeting and its recording, verifies `Meeting.created_by == user.id` (returning 404 for absent or non-owned meetings), and returns only source URLs minted by `ObjectStore.temporary_read_url()` for that recording's stored objects. URLs use a 3600-second TTL (the existing object-store default); on an expired/failed source, the client refetches the manifest and retries at the current playback time once, then reports an error. *Rejected alternative:* a public object-store URL or unbounded in-memory API proxy would either bypass the auth boundary or duplicate large media in API memory.

**Represent quality choices as the actual recording source inventory, not invented encodings.** Add a `recording_media_sources` table keyed to `SessionRecording`, with source id, kind (`video` or `audio`), object reference, MIME type, optional width/height, and a user-visible quality label. Recording persistence registers the existing `video_ref` (and audio when used) as the original source; it registers any additional already-available source renditions when present, but this feature does not add transcoding or promise new renditions. The manifest returns all playable video sources with their labels; show a quality/resolution selector only when there are multiple video sources. Selecting one uses its signed URL while preserving time and play/pause state. *Rejected alternative:* hard-coded quality levels or inferring multiple renditions from one file misrepresents actual assets. This adds the minimum source inventory/API work needed for the conditional selector; the feature does not alter capture/transcoding policy.

**Derive active passage rather than persisting a second playback cursor.** On time updates, find the passage whose interval contains the current media time; update the visible highlight and scroll the active passage into view only when the active passage changes. *Rejected alternative:* maintaining a separately updated transcript cursor risks drift after seeking, rate changes, or source changes.

## Architecture

### Component diagram

```mermaid
graph TD
  USER[Authenticated user] -->|JWT| ROUTE[Backend playback manifest route]
  ROUTE -->|owner check| MEETING[Meeting and recording source inventory]
  ROUTE -->|temporary signed read URLs| STORE[Object store]
  WEBAPI[frontend/src/api.ts] -->|JWT manifest request| ROUTE
  WEBAPI --> DATA[Timed transcript segments and source options]
  DATA --> VIEW[Meeting review playback view]
  VIEW --> PLAYER[Media element and playback controls]
  PLAYER -->|timeupdate, play, pause, ended, error| CTRL[Playback controller state]
  CTRL -->|current time and active passage| VIEW
  VIEW -->|activate passage control| CTRL
  CTRL -->|seek and play| PLAYER
  PLAYER -->|signed URL with byte-range requests| STORE
```

### Playback and passage navigation

```mermaid
sequenceDiagram
  participant User
  participant Passage as Transcript passage control
  participant Controller as Playback controller
  participant Media as HTML media element
  participant Transcript as Timed transcript
  User->>Passage: Activate play-from-passage control
  Passage->>Controller: requestPlaybackAt(startMs)
  Controller->>Media: set currentTime = startMs / 1000
  Controller->>Media: play()
  Media-->>Controller: timeupdate(currentTime)
  Controller->>Transcript: find passage containing current time
  Transcript-->>Controller: active passage id or none
  Controller-->>User: render active passage highlight
```

## Components and Interfaces

### `frontend/src/components/MeetingPlaybackView.tsx` (new)

Owns the media element, accessible playback controls, the selected source option when quality selection is available, and the timed transcript presentation. It receives meeting media and transcript data and does not fetch directly. The view must not add library, notes, summary, metadata, or editing behavior.

### `frontend/src/components/PlaybackController.ts` (new, pure helpers plus controller)

The controller binds the media element events to current playback state and exposes:

```typescript
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

export function findPassageAt(
  passages: readonly TimedPassage[],
  currentTimeMs: number,
): TimedPassage | null;
```

Use half-open intervals `[startMs, endMs)` so adjacent passage boundaries resolve to the next passage. For overlap, choose the first matching passage in the transcript's supplied order; passage ordering is not mutated. A passage-control action seeks to `startMs` and calls `play()`. A rejected `play()` promise is handled as a playback error and leaves the media paused; it is not silently reported as playing.

The playback controller uses one native video element with audio enabled for a `muxed_video_source`, one audio element for `absent`/`unknown` audio-only manifests, and an authoritative audio element plus separate muted video element for `separate` manifests. The persisted `video_presence` contract, not MIME or missing inventory rows, chooses the mode. In the separate-track mode, the playback controller owns one audio timeline and, when available, a separate muted video display element. The audio element is the authoritative clock, receives seek/play/pause/rate/volume/mute operations, and drives transcript highlighting. When a video source with a non-null recorded offset is selected, the controller loads it muted and synchronizes playback rate and play/pause to the audio element. On audio `timeupdate` and `seeked`, set video time to `max(0, audio.currentTime - videoOffsetMs / 1000)` and correct residual drift above 250 ms; keep video paused while the audio time is before a positive video offset. A null offset is not a playable synchronized video option. Starting playback waits for both elements' `play()` promises when video is present; if either fails, pause both and report an error rather than showing unsynchronized playback. For an audio-only recording, use the audio element alone. A quality change switches only the video source, preserves the audio source and current time, then re-synchronizes before resuming; show a quality selector only when there are multiple video options. Do not expose a quality selector for an audio-only recording or one video option.

### API/data boundary

Add typed retrieval methods to `frontend/src/api.ts`; all web HTTP calls remain in this adapter. The playback manifest contract is:

```typescript
export interface PlaybackManifest {
  meeting_id: string;
  duration_seconds: number;
  video_presence: 'muxed' | 'separate' | 'absent' | 'unknown';
  audio_source: {
    source_id: string;
    url: string;                 // short-lived presigned read URL
    mime_type: string | null;
  };
  muxed_video_source: {
    source_id: string;           // same underlying object as audio_source
    url: string;                 // signed URL for the single interleaved asset
    mime_type: string | null;
  } | null;
  video_sources: Array<{
    source_id: string;
    url: string;                 // short-lived presigned read URL for separate video
    mime_type: string | null;
    quality_label: string;
    width: number | null;
    height: number | null;
    video_offset_ms: number; // signed start of this video relative to audio time zero
  }>;
}

export interface TranscriptResponse {
  transcript_id: string;
  meeting_id: string;
  language: string;
  provider: string;
  supports_turns: boolean;
  segments: Array<{
    id: string;
    text: string;
    start_ms: number;
    end_ms: number;
    sequence: number;
  }>;
}

export async function getPlaybackManifest(meetingId: string): Promise<PlaybackManifest>;
export async function getTranscript(meetingId: string): Promise<TranscriptResponse>;
```

`GET /api/v1/meetings/{meeting_id}/playback` returns the manifest described above. It requires a valid JWT and the authenticated user must own the meeting; for absent/non-owned meetings return the same 404 response. The backend reads the recording source inventory and signs only the recorded objects through `ObjectStore.temporary_read_url(reference, ttl_seconds=3600)`. The web client requests this authenticated manifest, then the browser fetches media bytes from the signed URL; the object-store URL is not persisted or shared. A failed/expired URL causes one manifest refresh and retry at the saved current time, then an accessible error. Object-store CORS and byte-range support must permit the configured frontend origin and browser seeking; verify this contract in integration tests before enabling the feature in a deployment.

The playback manifest is based on persisted, explicit video-presence evidence, not MIME type or missing `video_ref` rows. Each recording carries `video_presence` (`muxed`, `separate`, `absent`, or `unknown`) set by the ingestion path. The extension's known single-container path records the actual video-track presence from its captured `MediaStream` before constructing the interleaved WebM upload and sends `video_presence=muxed` only when at least one video track was present; this assertion and the single uploaded object are persisted with the recording. The backend accepts `muxed` only for that single-object capture mode. A manifest may expose the same signed object as both the audio input and a `muxed_video_source`; the client uses one native video element with its audio enabled so the container's own timestamps remain authoritative. If the state is `absent` or `unknown`, the client is audio-only, regardless of MIME type or lack of separate video rows. New capture explicitly reports `absent` when no video track was captured.

For distinct audio and video assets, ingestion records `video_presence=separate` and every video source must have its measured signed `video_offset_ms` relative to audio time zero. The backend rejects separate-video ingestion without a signed integer offset. The controller uses audio as the clock, mutes the video element, sets video time to `max(0, audio_current_time_ms - video_offset_ms)`, and pauses video until the audio clock reaches a positive offset. Audio remains authoritative for passage highlighting and user controls. Mere association by recording ID does not establish synchronization. No new transcoding or editing is in scope. The existing transcript route's actual JSON has `segments`, each with `id`, `text`, `start_ms`, `end_ms`, `sequence`; the web adapter must correct the current frontend type mismatch (`turns`/camelCase) and map each segment to `TimedPassage` as `{ id: segment.id, text: segment.text, startMs: segment.start_ms, endMs: segment.end_ms }`. Preserve the backend's sequence order and source text. Reject/skip invalid timing for playback actions while retaining the segment text. The current `get_transcript` route authenticates but only checks that the meeting exists; it must additionally apply the same per-meeting ownership check as the playback manifest, returning indistinguishable 404 responses for absent and non-owned meetings before returning transcript text. This is a scoped access boundary for this feature's media/transcript retrieval, not a decision about broader multi-user, sharing, role, or identity policy. The playback backend work is in this feature's implementation scope: source registry migration, manifest route, aligned ownership checks, and API/adapter mapping are needed for the approved web playback behavior. For ingestion of separate tracks, extend `IngestionData` with nullable signed integer `video_offset_ms`: require a finite integer when a distinct `video` upload is present, reject missing/out-of-range values with 422 before persistence, and persist it on that video source; allow null when there is no separate video (including the existing single muxed-file extension upload). The manifest signs and returns only video rows with a known offset; no media transcoder or new encoding-generation behavior is included.

## Data Models

`SessionRecording.video_presence` is a non-null enum (`muxed`, `separate`, `absent`, `unknown`) with a server-side default of `unknown`; the migration initializes every existing recording to `unknown`. New ingestion must provide explicit video-presence evidence: `muxed` is accepted only for the known single interleaved-file capture mode and a positively observed captured video track; `absent` only when capture observed no video track; `separate` only with a separate video object and a signed integer `video_offset_ms`. The API manifest includes this enum plus nullable `muxed_video_source` and separate `video_sources`. Only `muxed` returns a muxed source (same object as audio); only `separate` with valid offsets returns separate video rows; `absent` and `unknown` return no video sources. MIME is descriptive and never used to infer presence. The migration backfills source inventory but never derives video presence from legacy MIME, missing `video_ref`, or a legacy `video_ref`; downgrade removes the new table and enum/column without altering original recording references.

`TimedPassage` is a view-facing type mapped from API `segments` as specified above. Add a `RecordingMediaSource` persistence model/table with: `id` (string UUID primary key), `recording_id` (FK to `session_recordings.id`, cascade delete), `kind` (`video` or `audio`), `object_ref` (private object-store key), nullable `mime_type`, `quality_label`, nullable integer `width` and `height`, nullable signed integer `video_offset_ms` (required for a video row to be offered as synchronized playback), and a uniqueness constraint on `(recording_id, kind, object_ref)`. Migration backfills one `audio` source from every existing non-null `SessionRecording.audio_ref` (label `Original`, dimensions and timing metadata unknown) plus one `video` source from each non-null `video_ref` (label `Original`, dimensions and `video_offset_ms` unknown). All migrated recordings have `video_presence=unknown` and are audio-only, including rows with null `video_ref`; historical separate refs without an offset are not playable as synchronized video. This prevents inferring a muxed container from missing rows, null MIME, or object references alone. The existing DB has no MIME or offset field: preserve any available object metadata; otherwise leave historical `mime_type` and `video_offset_ms` null. New ingestion metadata MUST include each separate video track's measured signed start offset from audio time zero, computed from the same monotonic capture clock, and persistence stores it with the video source; the current extension's single interleaved WebM path requires no separate offset. The backend rejects a newly ingested separate video source without an offset rather than silently treating it as aligned. No raw object-store references are exposed in API JSON. The manifest maps the required audio source row and any video source rows belonging to the same recording into one audio track plus a list of selectable video renditions, generating fresh signed URLs per response. The audio source is mandatory because `SessionRecording.audio_ref` is non-null; an absent video ref means audio-only or a muxed playable audio/video container as described above. The controller keeps the audio and video elements on the same recording-relative timeline, uses audio as clock and sound output, mutes paired video, and corrects video drift over 250 ms. `startMs` and `endMs` are non-negative finite millisecond offsets relative to the shared media timeline; a passage is eligible for synchronization only when `endMs > startMs`. Do not persist playback position or selected source.

## Correctness Properties

1. **Ordinary controls (Requirements 1.1–1.7):** with playable media, seek changes the media position; pause and resume invoke the corresponding media operations; changing speed applies the chosen rate; volume and mute controls update media state. A quality selector is present and applies a selected source only when multiple options are supplied.
2. **Playback highlight (Requirements 2.1–2.2):** for each playback time update, the highlighted passage is exactly the first valid supplied passage containing that time, or none if no passage contains it; a passage change moves the visible highlight to the newly active passage.
3. **Passage jump (Requirement 3.1):** activating a passage control sets media time to that passage's `startMs` and requests playback.
4. **Scope boundaries (Requirements 4.1–4.4):** the feature introduces no transcript editing, library, notes, summary, metadata, mandated control form, mandated user-visible time format, video-only behavior, fixed speed values, or fixed quality options.
5. **Media alignment:** a paired video option is exposed only with a persisted signed `video_offset_ms`; for any audio time `t`, the target video time is `max(0, t - video_offset_ms / 1000)`, and video remains paused until `t` reaches a positive offset. Drift above 250 ms is corrected. Legacy separate video with unknown offset is not presented as synchronized; single muxed containers remain one media clock.
6. **Playback-state consistency:** displayed playing, rate, volume, mute, current-time, and active-passage state are derived from the authoritative media clock and do not advance independently. Audio-only playback remains fully controllable without a separate video element.
7. **Playback/transcript access boundary:** a valid authenticated owner can receive only their meeting's transcript and signed media-source URLs; unauthenticated, absent, or non-owner requests return no transcript/object references, and absent/non-owned ids are indistinguishable at the API boundary.

## Error Handling

| Condition | Behavior |
|---|---|
| Missing/invalid JWT for manifest or transcript | Return 401; never sign a media URL or return transcript content. |
| Meeting is absent or not owned by the authenticated user | Return the same 404 response for both cases; do not reveal the distinction or sign any object URL. |
| Media manifest, signed-URL generation, or transcript request fails | Show an inline, accessible error for the failed content; do not present stale transcript as synchronized to a different meeting. |
| Signed URL expires or storage denies/does not support range/CORS access | Refresh the manifest once at the saved media time; if retry fails, stop playback and show an accessible error. Do not fall back to a public URL or unauthenticated API path. |
| Source-inventory migration/backfill fails | Let the migration transaction fail and roll back; do not remove or rewrite the existing `SessionRecording` references. Deployment stays on the prior schema until the migration succeeds. |
| Ingestion video-presence metadata is missing or inconsistent with capture mode | Reject the request with 422 before persisting playable sources; never infer muxed video from MIME, missing `video_ref`, or association by recording id. Legacy `unknown` stays audio-only. |
| Separate video upload has no valid signed start offset | Reject the ingestion request with 422 before persisting the recording; do not infer synchronization from a shared recording id. Legacy video rows with null offsets remain excluded from synchronized video playback. |
| Media metadata is loading or duration is unavailable | Keep applicable controls disabled until the media element reports the needed capability; show loading state. |
| Browser rejects playback (including passage-triggered playback) | Keep paused state, surface an accessible playback error, and allow another user action. |
| Selected quality/source fails | Surface an accessible error and retain the last usable player state where the browser permits; do not claim the failed source is active. |
| Transcript passage has invalid/missing timing | Render its text without a time-linked active state or passage-play action. |
| Current time has no corresponding passage | Clear the active highlight; do not fabricate a transcript association. |
| No media or empty transcript | Render an explicit unavailable/empty state; do not imply synchronization is active. |

## Testing Strategy

Use unit/component tests with synthetic media and transcript fixtures plus backend migration, route, and object-store integration tests. Mock browser media events for control logic; exercise database and storage contracts against disposable test infrastructure where required. Do not use real meeting recordings or transcripts.

- `frontend/src/**/__tests__/PlaybackController.test.ts`: test interval starts, end-exclusive boundaries, gaps, overlaps, invalid timing, empty input; test control state transitions and active-passage changes.
- `frontend/src/**/__tests__/MeetingPlaybackView.test.tsx`: test seek, pause/resume, rate, volume, mute, source selection only for multiple video options, passage seek/play, URL refresh retry once at the saved time, and accessible errors; assert audio-only playback uses the audio element with working volume/mute, paired audio+video playback uses audio as the audible clock and muted video, positive and negative `video_offset_ms` align start/seek with the offset formula, video waits when its positive start offset is ahead of audio, drift over 250 ms is corrected, changing quality preserves the audio source and position, `unknown` legacy video presence is audio-only; null MIME and missing `video_ref` never expose muxed video; only explicit `muxed` capture evidence enables the single-container path, and failure to start either paired element pauses both. Assert no editing or out-of-scope meeting controls.
- `backend/tests/test_migration.py`: start from revision `008_speaker_review_aggregate`, seed audio-only and audio-plus-video recordings, upgrade to the new source-inventory revision, and assert exactly one backfilled original audio source for every `audio_ref`, plus exactly one original video source for each non-null `video_ref` and none for null refs. Assert every migrated recording has `video_presence=unknown`, remains audio-only even with null MIME or missing `video_ref`, and legacy MIME/`video_offset_ms` stay null when unavailable. Test new ingestion persists `muxed` only for the explicit single-container capture mode with a positively observed video track, persists `absent` only for observed no-video capture, accepts `separate` only with an explicit separate video and signed integer offset, and rejects missing/inconsistent metadata (422). Downgrade to `008` and assert original `session_recordings.audio_ref`/`video_ref` data remains intact while the derived source table is removed; re-upgrade must recreate both source kinds. Verify duplicate `(recording_id, kind, object_ref)` is rejected.
- `backend/tests/meetings/test_playback_manifest.py`: test authenticated owner success, missing/invalid JWT (401), absent and non-owned meetings (same 404 response), no recording/no playable source, one vs multiple video source options, audio-only behavior for all `unknown` legacy rows including null MIME and absent `video_ref`, `muxed_video_source` only for explicit persisted muxed evidence, omission of separate video without an offset, signed positive/negative offsets for aligned video, and that only owner-authorized object refs are passed to `temporary_read_url` with TTL 3600 and never serialized in the response. Test transcript route applies the identical ownership boundary and does not return another user's text.
- `backend/tests/meetings/test_playback_storage_integration.py`: with disposable S3-compatible storage, fetch a signed source URL using HTTP `Range` and verify 206/`Content-Range`/correct bytes; run browser-origin CORS preflight and GET from the configured frontend origin. A deployment must pass this integration contract before playback is enabled; configuration failure blocks playback delivery rather than bypassing authorization.

### Reproducible participant-trial fixture and route integration

Add a deterministic synthetic playable fixture at `frontend/public/test-fixtures/meeting-review-playback.wav` (12 seconds, mono, 16 kHz, 16-bit PCM) and a paired timed transcript fixture at `frontend/src/test-fixtures/meeting-review-playback.ts` with three ordered passages whose intervals cover the media timeline. The audio and transcript contain synthetic content only; no real meeting material or identifying data. The fixture is for trial-readiness and browser integration, not a replacement for API-backed media in the normal meeting view. A real static WAV is preferred over a fake media element because only an actual browser-decoded asset demonstrates playable media and timing; a local fixture route is preferred over a backend-seeded meeting because it is deterministic and requires no real account or storage setup. The route is development-only so this convenience cannot create a production authorization bypass.

Wire the existing `frontend/src/App.tsx` to mount `MeetingPlaybackView` at `/_trial/meeting-review-playback` only in Vite development mode, loading the checked-in fixture directly. Include a development-only link from the app's root view so a participant or tester can reach the route from the application rather than rendering the component in isolation. Do not expose this route/link in production builds, add it to meeting navigation, or use it to bypass authentication for real meeting media; normal meeting playback continues to load its authenticated manifest and transcript through `frontend/src/api.ts`.

Add `frontend/tests/e2e/meeting-review-playback-trial.spec.ts` with a real-browser test that starts at the app root, follows the development-only trial link, and verifies the playback view is mounted, the actual WAV reports finite non-zero duration/metadata, and all three fixture passages are visible. Use the rendered audio element (`data-testid="playback-media"`) and the visible playback/passage controls; do not call `HTMLMediaElement.play()` or change `currentTime` from the test. Assert the media element's source is the fixture WAV, clicking the view's Play control causes `paused` to become false and `currentTime` to advance by at least 500 ms within 5 seconds, and clicking the second passage's control (fixture `startMs=4000`) dispatches the real seek/play path: observe its `seeked` and `playing` events, assert the `currentTime` sampled at `seeked` is within 250 ms of 4.000 seconds, and assert it is not paused when `playing` fires. Use event listeners registered before each click to avoid missing events. This proves browser playback and passage-control integration against the asset, not merely route or component rendering. This is technical readiness evidence only: it does not count participant observations, establish user acceptance, change any frozen scenario/pass threshold, or assert that participants can complete scenarios. Run and report this E2E test against the exact candidate before resuming the frozen evaluation; record its candidate SHA and result separately from participant observations.

Run backend tests from `backend/` (`pytest`) and frontend tests/typecheck from `frontend/`; these are required implementation validations, not claims that this design run executed them.
