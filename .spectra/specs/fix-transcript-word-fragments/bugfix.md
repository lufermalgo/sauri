# Bugfix — Render transcript speaker turns instead of word fragments

## Descripción del Bug

The meeting transcript is reported to render as thousands of very short word-level fragments, with speaker attribution repeated per word, rather than readable speaker turns. QA traced the confirmed fragmentation-preserving path: the worker persists each ASR segment as a `SpeechTurn`, while the API, frontend adapter, and view preserve and render that one-to-one granularity. It is not yet proven that the private meeting's ASR provider emitted the reported fragments, or how its actual speech-turn boundaries can be derived from current inputs; a mapping-only change may therefore be insufficient.

**Evidence and authority:** Fer reported this on 2026-10-30 in parent task `task_6a271652b2c34130` and the linked bugfix card `task_8ce8907902534201`: a full meeting displayed 2,919 approximately 15-character fragments with speaker attribution per word. These counts describe one observed recording only; the separate offline estimate of roughly 75 turns in 61 minutes is not a threshold or acceptance target. No meeting content is included here. The authorized expected behavior comes from the owner-approved `PRODUCT_BASELINE.md` snapshot at `f31c1437d002a49849fc577446290ab83d29a584` (blob `273e702ac8b4886a91366a1700c3c1946fc6c0c1`), §4.C.4: the portal transcript presents each turn with timestamp, speaker label, and text. The approved `meeting-review-playback` requirements define transcript passages as paragraphs or fragments with linked times; `recording-speaker-review` governs attribution and honest `Speaker N` labels, not general passage grouping. Neither upstream spec defines a silence-gap threshold or permits merging based solely on matching labels.

## Pasos para Reproducir

**Executed synthetic reproduction and code-path evidence:** see `.spectra/specs/fix-transcript-word-fragments/qa-reproduction.md`, authored by Nia for inspected candidate `19a18ea16a3d053b00be3a5b5d7a091bfee9a18e`.

1. Run the exact frontend and backend commands recorded in that evidence file from the assigned worktree.
2. Observe that the existing synthetic frontend API fixture retains each segment separately, and the component fixture renders one row and speaker label for each supplied turn. The backend property test explicitly persists each ASR segment as one `SpeechTurn`.
3. Compare these deterministic observations with Fer's reported full-meeting symptom (2,919 approximately 15-character fragments and speaker attribution per word).

The commands pass because current tests encode one-segment-to-one-row mapping; they confirm the existing fragmentation-preserving behavior, not a corrected candidate. This does **not** independently reproduce the private meeting or establish that its provider emitted one segment per word. Its audio and transcript remain private and are not included in this artifact. The evidence file identifies the inspected modules/functions, commands, test counts, gaps and limitations.

## Comportamiento Actual (Defecto)

WHEN ASR produces multiple transcript segments for a meeting, THEN the transcription worker persists one `SpeechTurn` per ASR segment; the meeting API serializes each row separately, the frontend adapter maps each valid timed segment to a separate turn, and the transcript view renders a separate row and speaker label for each turn. Nia confirmed this path by code inspection and executed tests at candidate `19a18ea16a3d053b00be3a5b5d7a091bfee9a18e`; the exact file/function findings and commands are in `qa-reproduction.md`.

WHEN the reported full meeting was reviewed, THEN it displayed 2,919 approximately 15-character fragments with speaker attribution per word (Fer's report, not independently reproduced). It remains unproven whether the real provider emitted those fragments or what the actual spoken-turn boundaries were. The confirmed implementation seam is one-ASR-segment-to-one-`SpeechTurn` and one-turn-to-one-row. This is a causal explanation for how segment granularity reaches the UI, but it does not establish that changing this mapping alone can recover correct speaker-turn boundaries.

## Comportamiento Esperado (Correcto)

WHEN the portal presents a transcript for a new recording, or a historical recording whose audio is available and authorized under existing retention, THEN the system SHALL present the transcript as complete speaker turns, each with a timestamp, speaker label, and associated text, as required by the owner-approved product baseline §4.C.4. Raw ASR segment boundaries SHALL NOT, by themselves, be treated as proof that each segment is a separate user-facing speaker turn.

WHEN a historical recording's audio is confirmed expired or irrecoverable under existing retention, THEN the system SHALL preserve its existing source fragments ungrouped and mark them `not_reconstructible`; it SHALL NOT recreate, infer, or fabricate turn groupings without authorized available audio.

WHEN consecutive speech belongs to different speakers or to distinct nonconsecutive turns, THEN the system SHALL preserve the correct turn distinction and attribution; repeated speaker labels alone SHALL NOT cause separate turns to be merged. The approved product behavior is turn-level presentation; the technical signal and processing layer needed to determine those boundaries are not yet established and belong in design, not this bugfix specification.

WHEN a transcript passage is linked to media time, THEN the system SHALL preserve the passage's correct start and end boundaries so that playback highlighting and passage-initiated playback continue to target the corresponding time under `meeting-review-playback` requirements 2 and 3. The fix SHALL NOT invent turn timing or a silence-gap threshold absent from approved sources.

## Comportamiento Sin Cambios (Prevención de Regresiones)

WHEN consecutive transcript turns have different speakers, THEN the system SHALL CONTINUE TO retain the speaker change and the correct attribution for each turn; unknown or uncertain attributions SHALL CONTINUE TO use `Speaker N` rather than an unsupported identity, under `recording-speaker-review` requirement 2.

WHEN two turns with the same speaker label are separated by an intervening speaker turn, THEN the system SHALL CONTINUE TO keep them as separate turns and in their original order.

WHEN transcript timing contains a gap or overlapping intervals, THEN the system SHALL CONTINUE TO preserve those original timing relationships and SHALL NOT bridge a gap or remove an overlap by widening, shifting, or fabricating turn boundaries.

WHEN playback time advances across a transcript passage boundary, THEN the system SHALL CONTINUE TO highlight the passage associated with that time; activating a passage playback control SHALL CONTINUE TO start playback at that passage's linked time, under `meeting-review-playback` requirements 2 and 3.

WHEN text or timing is absent or invalid for an entry, THEN the system SHALL CONTINUE TO avoid fabricating text or a time-linked playback association, consistent with the approved playback design's invalid/missing timing behavior.

## Restricciones del Fix

- Do not include actual meeting content, transcript text, names, or other owner data in this spec, tests, fixtures, or commits; use synthetic data only.
- Do not treat the observed counts or the offline turn estimate as thresholds, targets, or pass/fail criteria.
- Do not introduce an arbitrary silence-gap duration or other numerical threshold. The approved sources do not specify one.
- Do not merge nonconsecutive turns solely because speaker labels match; preserve turn order, speaker changes, unknown labels, and original timing gaps/overlaps.
- Do not change retention policy or recover audio outside existing retention and authorization; when historical audio is confirmed expired or irrecoverable, preserve source fragments ungrouped and mark them `not_reconstructible`.
- Preserve playback passage start/end fidelity and current seek/highlight behavior. Do not redesign the UI or add transcript editing.
- Establish the failing layer with reproducible synthetic test evidence before choosing backend, API, or frontend implementation placement. If a proposed fix requires new product behavior beyond presenting each turn as specified in the approved baseline, stop and identify that scope delta to Ansel for an authorized decision; do not silently broaden this bugfix.

## Criterios de Aceptación

1. Given a new recording, or a historical recording whose audio is available and authorized under existing retention, and a processing output representing multiple low-level text fragments within a spoken turn, the portal SHALL present the complete turn text as a turn-level passage with its timestamp and correct speaker label, rather than exposing each low-level ASR fragment as a user-facing turn. The approved baseline specifies this observable turn-level behavior; the source of reliable turn boundaries is an unresolved technical design investigation.
2. Given a historical recording whose audio is confirmed expired or irrecoverable under existing retention, the portal SHALL preserve the existing source fragments ungrouped and mark them `not_reconstructible`; this state SHALL be observable in the transcript representation, and no turn grouping SHALL be inferred or fabricated.
3. Given a speaker change or a distinct later nonconsecutive turn with a previously used speaker label, the output SHALL preserve separate turns, their original order, and their correct labels; matching labels alone SHALL NOT merge them.
4. Given unknown or uncertain speaker attribution, the output SHALL preserve the `Speaker N` label rather than assert an unsupported identity, consistent with `recording-speaker-review` requirement 2.
5. Given transcript timing with gaps or overlapping intervals, the fix SHALL preserve the original timing relationships and SHALL NOT fabricate continuous timing or bridge the intervals. No numeric silence-gap threshold is prescribed.
6. Given playback at a passage boundary or activation of a passage control, highlighting and playback start SHALL continue to use the correct passage timing; the fix SHALL NOT regress approved playback requirements 2 and 3.
7. Tests SHALL use synthetic transcript content only. Neither the reported 2,919 fragments nor the offline estimate of roughly 75 turns in 61 minutes is a numeric acceptance threshold.
