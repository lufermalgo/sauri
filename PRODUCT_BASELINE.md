# Sauri Product Baseline

> **Status: DRAFT — Fer approved the portal and Phase 2 scope amendment at commit `f31c1437d002a49849fc577446290ab83d29a584`, as recorded in task `task_a08baf81140a4073`. This current snapshot contains subsequent edits and requires Fer's approval of this exact version before it becomes APPROVED.** This amendment preserves the product content approved on 2026-10-16 at commit `f5ff445fd508983740cd6b5a89c08adafcbb9295` (file blob `c43cad6515b01a52037ad9cd4e09010a40477fb4`). The earlier content published in `main` at commit `d738e78` (file blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`) was approved on 2026-10-09. Proposed, deferred, and open items remain outside the approved scope and are not implementation authorization.

## 1. Product purpose

Sauri is an internal Summan platform for capturing commercial meetings and making their recordings, speaker-attributed transcripts, notes, and summaries useful for later review. The initial user is the functional user of Sauri; the product should be conceived as an internal tool with potential to scale to many Summan users. Speaker name/identity associations are per-user and not shared with other users. Multi-user rollout, authentication, and detailed access policy remain undecided.

The user needs to be able to record a meeting on demand, trust that the resulting audio/video and transcript are available for later use, understand who spoke (and correct uncertain or wrong attributions), and return to a recording in a web portal to review or download it.

## 2. Users and outcomes

### Initial user

- **Functional user:** the person using Sauri to capture and revisit commercial meetings. The first intended user is the functional user.
- **Meeting participants:** customer and Summan attendees whose speech may appear in captured audio/video and transcripts. The functional user states that the platform is authorized and that permission is requested from attendees before recording; this is declared context, not independently verified policy or a specified consent-control design.

### Desired outcomes

1. A user can start a meeting capture from the Chrome extension and later find the resulting recording in Sauri.
2. The recording preserves usable audio and video, and the transcript is attributed to known speakers where possible; uncertain speakers remain visibly unresolved rather than being assigned an unsupported identity.
3. The user can review and correct speaker identities. A user's saved name/identity associations are that user's preferences/data and may help recognize speakers in later recordings for that same user only; they are not shared with other users.
4. The user can revisit a recording in the web portal, navigate between its media and transcript, access notes and summary separately, and download the video or transcript.

## 3. Experience principles

- **On-demand capture:** capture starts only when the user initiates it from the extension and selects the Google Meet tab.
- **Configurable capture presence:** the extension preferences include whether the floating recording indicator is shown. Hiding it is intentional; the user does not need in-recording controls in that mode and can end capture by stopping Chrome tab sharing.
- **Honest attribution:** show a known speaker's name when recognized; use `Speaker N` when the voice is unknown or attribution is uncertain. Do not imply an uncertain match is confirmed.
- **Human correction matters:** incomplete speaker review remains pending and is requested again when the user returns. A user's speaker-name/identity associations are that user's own preferences/data; corrections may inform later recognition for that same user, not other users. Do not infer cross-user sharing of labels, names, or voice data.
- **Keep related content distinct:** notes are associated with a recording but kept in a section separate from the transcript. Summaries are also presented as a distinct meeting artifact.
- **Do not let visual references invent scope:** screenshots are inspiration only. Their values, labels, layout, and controls are not product commitments unless separately confirmed below. The meeting-portal composition and behaviors explicitly stated in §4.C are confirmed product scope, not merely visual inspiration.

## 4. Product journeys

### A. Configure and capture a meeting

1. The user opens the Chrome extension and chooses to record a session.
2. A Chrome tab-selection flow lets the user select the Google Meet tab. The exact selector composition and options are for design; the reference image does not authorize whole-window or full-screen capture.
3. A countdown runs for the duration set in extension preferences, then recording begins. The user expects both audio and video to be captured; this is a product expectation, not a claim that the current implementation guarantees it.
4. The user may choose whether the floating recording indicator is visible. When visible, the expected indicator includes a timer and the previously described recording controls (cancel, pause/resume, stop, microphone selection, movable placement, and access to notes). When hidden, no in-recording controls are required; the user ends capture by stopping sharing of the captured Chrome tab. How notes are reached from the floating control when the indicator is hidden remains a design question.
5. Cancel ends capture without another action. Pause temporarily stops capture and allows resuming. Stop ends the recording; the expected next result is storage in Sauri and transcription. Exact interactions where the indicator is hidden must follow the confirmed tab-sharing behavior, not assume an additional hidden control.
6. The user can add notes from the extension or floating control. Notes remain associated with the recording and separate from its transcript.

### B. Process and review speakers

1. After a stopped recording is stored, Sauri transcribes it and attempts to identify speakers. The six-attendee example (three customer, three Summan) is illustrative, not a speaker-count limit.
2. A recognized speaker appears by name. An unknown or uncertain speaker appears as `Speaker N`.
3. When processing finishes, the user is asked to review speaker names. For each speaker, the user can play a clear audio excerpt, replace `Speaker N` with a chosen name/label, or correct an automatically assigned name.
4. If the user leaves before completing review, the review remains pending and is requested again on returning to the recording. It cannot be dismissed as complete without finishing.
5. Previously established identities should be reused despite acoustic variation for the same user. The user's saved name/identity associations are that user's preferences/data and may help recognize speakers in that user's later recordings only; they are not shared with other users. The design chooses the mechanism; no voiceprint, model, or other particular technique is selected here.

### C. Find and revisit a recording in the web portal

1. The user finds a prior recording in a web-based Sauri library. The list is ordered newest first and supports search, filtering, and sorting. Filter fields are derived from available metadata; no arbitrary filter catalogue is prescribed. Full-text search across meetings is not in scope.
2. The user selects a session, can rename or delete it, and can download its video and transcript. When capture stops or the Google Meet session ends, Sauri opens that meeting's portal view automatically.
3. The user can edit company, project, and participant metadata, and use predefined tags (examples given: GenAI, Digital Twin, Automatización) or create tags.
4. The meeting portal places the media player above the transcript. The player has ordinary playback controls, including seek, speed, quality/resolution, pause, volume, and mute. The transcript presents each turn with a timestamp, colored speaker label, and text. During playback, the corresponding transcript passage is highlighted and the transcript follows playback by scrolling to it; selecting a passage starts playback at its linked time. Speaker names can be edited from the transcript, subject to the existing per-user identity boundary. This changes speaker attribution only; manual transcript-text editing is excluded. The precise control, timestamp format, colors, and video-specific behavior are for design.
5. A side panel separates meeting content into tabs, including Chat and Notes/Summary. The Chat tab is part of the initial portal composition; its interactive chat-with-the-recording capability is Phase 2 and is not available as an initial interaction. Notes and summaries remain distinct artifacts and separate from the transcript; the summary can be copied or downloaded and identifies the main topic and key arguments/points in a clear structure. Speaker talk-time insights are also Phase 2. Other tab names or content are not specified by this baseline.

## 5. Capability catalogue and scope state

“Confirmed intent” means the capability is grounded in the user's discovery and included in this approved baseline. It does not settle implementation details or the open boundaries in the Dependencies column. Product acceptance and runtime delivery remain separate later gates.

| Capability | User / outcome | State in this baseline | Dependencies or boundary |
| --- | --- | --- | --- |
| Extension preferences: countdown duration and show/hide floating recording indicator | Recorder configures capture and indicator presence | Confirmed intent | Specific countdown values (including image's “3s”) and other image-only settings are not selected |
| On-demand capture of a selected Google Meet Chrome tab, with expected audio and video | Recorder creates a meeting recording | Confirmed intent | Reliability expectation is not a verified implementation claim; exact selector behavior is for design |
| Floating indicator when enabled: timer, cancel, pause/resume, stop, microphone selection, movable placement, notes access | Recorder can see/use capture controls when the indicator is shown | Confirmed intent | Hidden-indicator mode needs no in-recording controls; end by stopping tab sharing. Notes access in hidden mode is unresolved |
| Cancel / pause-resume / stop outcomes | Recorder can abandon, temporarily pause, or finish capture | Confirmed intent | Cancel creates no further action; stop stores the recording and starts transcription |
| Recording-associated notes, separate from transcript | Recorder adds context for later review | Confirmed intent | Note format/editing and access when indicator is hidden remain open/design work |
| Recording storage, transcription, and automatic speaker identification | Recorder can review the captured meeting and who spoke | Confirmed intent | Transcription/diarization technology and quality thresholds are not chosen here |
| Speaker review, `Speaker N` for unknown/uncertain voices, and same-user future effect of corrections | Recorder resolves attribution and improves future recognition for that same user | Confirmed intent | Cross-user sharing of speaker labels, names, and voice data is not implied; future multi-user implementation must preserve per-user isolation. Permissions and technical recognition mechanism remain unresolved |
| Web recording library with search, newest-first ordering, metadata-derived filters, session selection | User finds recordings later | Confirmed intent | Search semantics and filter catalogue are for design; full-text search across meetings is excluded |
| Rename/delete/download recording video and transcript | User manages and takes away a session's artifacts | Confirmed intent | Retention, deletion guarantees, and export formats are not specified |
| Editable company, project, participant metadata; predefined and user-created tags | User organizes recordings | Confirmed intent | Tag governance and extra fields are not specified |
| Meeting portal with player above a timestamped, speaker-colored transcript; passage seeking, playback-following scroll, and editable speaker names | User reviews media and transcript together and corrects speaker attribution | Confirmed intent | Speaker identity remains per-user. Editing speaker names does not authorize editing transcript text; control, timestamp representation, colors, and video-specific behavior are for design |
| Structured meeting summary with copy/download | User retrieves key content quickly | Confirmed intent | No accuracy threshold, generation method, or fixed layout selected |
| User-defined, editable summary templates and a selectable default; templates may be grouped by category with multiple templates per category | User shapes summary output | Confirmed intent | Sharing/default-selection rules remain open. “General > Resumen básico” is only a proposal, not an approved default/template |
| Manual transcript-text correction with saved changes | User repairs errors caused by audio/noise issues | Explicitly excluded from current scope | Editing speaker names is in scope; editing transcript wording is not |
| Automatic opening of the meeting portal when recording stops or the Google Meet session ends | User arrives at the recording for review without manually navigating to it | Confirmed intent | Exact trigger handling when both events occur and browser behavior remain for design |
| Chat tab in the meeting portal | User can navigate the initial portal composition, which includes a Chat tab | Confirmed intent | Tab presence does not imply interactive chat functionality; interaction remains Phase 2 |
| Chat with the recording | User interacts with chat in the context of a meeting recording | Phase 2 | Not available as an initial interaction; interaction boundaries remain to be specified |
| Speaker talk-time insights | User reviews how speaking time is distributed among speakers | Phase 2 | Presentation and calculation details remain to be specified |
| Other side-panel tab names/content and processing-progress states | User understands and navigates the product | Open for design | The portal composition and Chat / Notes-Summary tabs are confirmed; unspecified additional tabs and progress states are not commitments |
| CRM integration / CRM AI | Future commercial intelligence flow | Explicitly deferred; out of current scope | Revisit only after capture, transcription, and diarization stabilize. CRM AI is not part of Sauri; no fields, integration, or mechanism are agreed |

## 6. Product constraints and non-goals

### Confirmed product constraints

- Sauri is an internal Summan platform, initially for the functional user, with future multi-user scale under consideration.
- A recording is initiated on demand from the extension; the current described journey selects a Google Meet browser tab.
- The user expects usable audio and video, transcription, and speaker attribution. Expectations do not represent technical verification or a guaranteed outcome.
- Unknown or uncertain speaker attribution must be represented as `Speaker N` until human review.
- A user's saved speaker name/identity associations are that user's preferences/data and may influence later recognition for that same user only. They are not shared with other users; future per-user isolation is required. This does not authorize global voice modeling.
- Meeting notes, transcript, and summary are distinct content types associated with the meeting as described above.
- The functional user reports that Sauri is authorized and attendees are asked before recording. This baseline does not independently validate that assertion or decide a consent workflow.

### Explicit non-goals for current scope

- CRM integration, taking meeting intelligence into the CRM, and any CRM AI agent. These are future topics, not current functionality.
- Assuming that a UI screenshot selects a framework, technology, exact layout, default value, capture mode, or additional preference.
- Treating the six-person example as a maximum or assuming all automatic speaker matches will be correct.
- Treating existing source code, old roadmaps, or tests as product approval or evidence of deployment.
- Sharing speaker labels, names, or voice data between users, or using them for global voice modeling, is not authorized by this baseline clarification.
- Full-text search across meetings, manual transcript-text editing, and sentiment analysis are outside the approved scope.
- Interactive chat with a recording and speaker talk-time insights are Phase 2; the Chat tab itself is included in the initial portal composition, without initial chat interaction.

## 7. Open and deferred decisions

These are not questions already answered by the user; they are the remaining boundaries for discovery or design.

1. **Future multi-user platform and access policy:** multi-user rollout and authentication (including Google authentication) are separate future work. The speaker identity boundary is decided: associations are per-user and must not be shared across users. Detailed permissions/access policy remains open.
2. **Technical design:** transcription and diarization/identity-reuse mechanisms. The user expects strong identification and considers current ML/deep-learning methods if useful, but has not selected a model or implementation.
3. **Templates:** whether templates/defaults are personal or shared and how a default is chosen across categories. Do not treat “General > Resumen básico” as settled.
4. **Capture design:** exact selector composition and options, and the result of clicking record/note again after closing the selector without a selection.
5. **Notes interaction:** how to access notes from the floating control when that indicator is hidden; note format and editing are also unspecified.
6. **Processing experience:** user-visible states, feedback, timing, and results before the recording/transcript are ready.
7. **Transcript editing:** manual transcript-text editing is explicitly outside the approved scope. Any reconsideration requires a new product decision; speaker-name corrections remain distinct and are in scope.
8. **Playback details:** exact transcript-to-time control and representation, including video-specific behavior.
9. **Portal details:** the approved composition is a player above the transcript, with side-panel tabs including Chat and Notes/Summary. Exact control details, timestamp format, colors, and the names/content of any additional tabs remain for design; no unlisted tabs or capabilities are implied.
10. **Privacy and data governance:** consent workflow, retention, deletion guarantees, and access policy require explicit definition before their behavior is specified. Meeting media, transcripts, speaker identity data, and participant details are sensitive.
11. **CRM:** whether and how a future transfer/integration should work remains deferred until the product is stable; there are no agreed fields or mechanisms.

## 8. Success signals

These are outcome signals for later measurement, not committed targets or acceptance thresholds:

- Users can locate a saved meeting and reopen its video and transcript.
- Users can identify and correct speaker labels, and later recordings for that same user can reuse those corrections.
- Users can navigate between transcript passages and corresponding media time, and follow the active passage during playback.
- Users reach the meeting portal automatically when recording stops or the Google Meet session ends.
- Users can add and later distinguish meeting notes, transcript, and summary.
- Users can retrieve a meeting summary and download the relevant recording artifacts.

Numerical targets, measurement windows, and representative-user acceptance evidence remain to be set. Technical QA alone does not constitute product acceptance.

## 9. Source and authority

This baseline was prepared from `PRODUCT_DISCOVERY.md`, especially §§1–6 and the chronological clarifications in §7. The 2026-10-16 owner clarification, relayed by Teo in `th_24d098a54e5c4187`, narrows the earlier speaker-correction wording: Speaker N can be reviewed/named per recording; saved name/identity associations are that user's data/preferences and may assist recognition in later recordings for that same user only; there is no implied sharing of labels, names, or voice data with other users. Future per-user isolation is intended; multi-user rollout and Google authentication are separate work. This does not authorize global voice modeling. Other clarifications remain: `Speaker N` for unknown/uncertain voices; hiding the indicator means no in-recording controls are required and capture ends by stopping Chrome tab sharing; notes are separate from the transcript and attached to the recording; CRM and its AI agent remain outside current scope.

Fer approved the product content of the prior snapshot on 2026-10-16: commit `f5ff445fd508983740cd6b5a89c08adafcbb9295` (file blob `c43cad6515b01a52037ad9cd4e09010a40477fb4`). On 2026-10-22, Fer approved the portal and Phase 2 scope amendment in this baseline at commit `f31c1437d002a49849fc577446290ab83d29a584`, as recorded in task `task_a08baf81140a4073`. The earlier product content published in `main` at commit `d738e78` (file blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`) was approved on 2026-10-09. The discovery record preserves examples, references, and distinctions in greater detail. Other open and deferred decisions remain unresolved and outside approved scope. Product acceptance and runtime delivery are separate gates.
