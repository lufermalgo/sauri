# Requirements — Web Recording Library and Metadata

## Introduction

The approved product baseline includes a web recording library where the functional user can find a prior meeting, manage its recording artifacts, and organize it with business metadata and tags. This spec defines only those library and metadata capabilities. The owner clarified the searchable fields and matching behavior on 2026-10-14: search uses only existing recording name, date, company, project, and tags; text matches partially without case sensitivity, and date uses a range filter. Other filter fields and sort keys beyond the required newest-first ordering remain unspecified. Retention and deletion guarantees, export formats, and access policy remain open and are not decided here.

**Thesis:** A newest-first recording library with search, metadata-derived filtering, and editable metadata and tags helps the user find and organize prior meetings without assuming unresolved policies or implementation details.

**Scope:** Browse, search, filter, sort, and select recordings; rename or delete a selected recording; download its video and transcript; edit company, project, and participant metadata; assign predefined tags and create tags.

**Out of scope:** CRM integration and CRM AI; playback, summaries, transcript search or editing, notes, analytics, and any other meeting-view capability. Transcript and participant search, and search over fields not stored by the product, are outside this spec. This spec does not decide other filter fields, sort keys beyond newest-first ordering, tag governance, retention, deletion guarantees, export formats, or access policy.

Current implementation, source code, and tests are current-state evidence only. They are not product acceptance or authorization to extend functionality without evaluating the candidate against these approved requirements and the relevant acceptance evidence.

## Glossary

- **Recording_Library**: The web-portal collection of recordings that the functional user can browse, search, filter, sort, and select.
- **Recording_Metadata**: Company, project, and participant information associated with a recording, together with tags used to organize recordings.
- **Predefined_Tag**: A tag supplied for assignment to recordings; baseline examples are `GenAI`, `Digital Twin`, and `Automatización`.
- **User_Created_Tag**: A tag created by the user for use with recordings.

## Requirements

### Requirement 1: Find and select recordings

**User Story:** As the functional user, I want to find and select a prior recording in a web library, so that I can manage its recording artifacts and metadata.

#### Acceptance Criteria

1. THE Recording_Library SHALL present recordings in newest-first order.
2. WHEN the user searches recordings with text, THE Recording_Library SHALL present recordings whose existing recording name, company, project, or tags partially match that text without regard to letter case, and exclude recordings without such a match. Transcript content, participant metadata, and fields not stored by the product SHALL NOT be searched.
3. WHEN the user applies a date-range filter to recordings, THE Recording_Library SHALL present recordings whose existing recording date matches the selected range and exclude recordings whose recording date does not match that range.
4. WHEN the user filters by available recording metadata, THE Recording_Library SHALL present recordings matching the selected metadata filter and exclude recordings that do not match it. Filter fields beyond the specified date range remain open and SHALL NOT be inferred as an arbitrary catalog.
5. WHEN the user sorts recordings newest first, THE Recording_Library SHALL present the resulting recordings in newest-first order, including after search or filtering. No other sort key is specified by this requirement.
6. WHEN the user selects a recording, THE Recording_Library SHALL identify that recording as the selected session for library actions.

### Requirement 2: Manage and download recording artifacts

**User Story:** As the functional user, I want to rename or delete a selected recording and download its video or transcript, so that I can manage and retrieve the meeting artifacts.

#### Acceptance Criteria

1. WHEN the user renames a selected recording and the action completes, THE Recording_Library SHALL display the new name for that recording, including when the user revisits or refreshes the library.
2. WHEN the user deletes a selected recording and the action completes, THE Recording_Library SHALL no longer display it as an available entry, including when the user revisits or refreshes the library. This outcome does not specify retention or any deletion guarantee.
3. WHEN the user requests a selected recording's video download, THE system SHALL make that video's artifact available through a download action.
4. WHEN the user requests a selected recording's transcript download, THE system SHALL make that transcript artifact available through a distinct download action. Export formats are not specified here.

### Requirement 3: Edit recording metadata

**User Story:** As the functional user, I want to edit a recording's company, project, and participant metadata, so that I can organize it using its business context.

#### Acceptance Criteria

1. WHEN the user edits company metadata for a selected recording and the action completes, THE Recording_Library SHALL display the updated company metadata for that recording, including when the user revisits or refreshes the library.
2. WHEN the user edits project metadata for a selected recording and the action completes, THE Recording_Library SHALL display the updated project metadata for that recording, including when the user revisits or refreshes the library.
3. WHEN the user edits participant metadata for a selected recording and the action completes, THE Recording_Library SHALL display the updated participant metadata for that recording, including when the user revisits or refreshes the library.

### Requirement 4: Use predefined and user-created tags

**User Story:** As the functional user, I want to use predefined tags or create tags for recordings, so that I can organize meetings with relevant categories.

#### Acceptance Criteria

1. WHEN the user assigns a predefined tag to a selected recording, THE Recording_Library SHALL display that tag as associated with the recording, including when the user revisits or refreshes the library; available examples include `GenAI`, `Digital Twin`, and `Automatización`.
2. WHEN the user creates a tag, THE Recording_Library SHALL make that tag available for assignment to recordings, including when the user revisits or refreshes the library.
3. WHEN the user assigns a user-created tag to a selected recording, THE Recording_Library SHALL display that tag as associated with the recording, including when the user revisits or refreshes the library.
4. Tag governance remains open and is not specified by this requirement.

### Requirement 5: Preserve scope boundaries

**User Story:** As a product stakeholder, I want this spec to remain within the approved library and metadata scope, so that open decisions and separate capabilities are not mistaken for requirements.

#### Acceptance Criteria

1. THE Recording_Library SHALL NOT require full-text transcript search or transcript editing.
2. THE Recording_Library SHALL NOT specify retention behavior, deletion guarantees, export formats, access policy, or tag governance.
3. THE Recording_Library SHALL NOT include CRM integration or CRM AI.
4. THIS spec SHALL NOT specify playback, summaries, notes, analytics, or other meeting-view capabilities; their exclusion here is not an exclusion from the approved product baseline.

## Traceability

The approved scope authority is `PRODUCT_BASELINE.md` at commit `d738e78`, blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`. This spec traces to §4.C steps 1–3; §5 capability catalogue rows 74–76; §7 open/deferred decision 10; §8 success signals; and §9 source and authority. The owner decision recorded on 2026-10-14 for this task (`task_ff6b983f1f994f15`, input `inp_a00ebfb01a1046b2`) narrows Requirement 1 search to existing recording name, date, company, project, and tags, specifies case-insensitive partial text matching and date-range filtering, and excludes transcript and participant search and unstored fields. This clarification is not literal text of baseline `d738e78`. Decision 10 leaves retention, deletion guarantees, and access policy open. The §8 success signals are later outcome signals, not acceptance thresholds or authorization to add playback/review capabilities to this spec.

Discovery references are `PRODUCT_DISCOVERY.md` §2.2 lines 32–37 for the library, operations, sorting/filtering, metadata, and tags; §2.6 steps 6–7 for post-review web use and the boundary around other meeting-view behavior; and §7 clarifications dated 2026-10-09 concerning later use of the web library and CRM. Discovery is traceability context only; the approved baseline remains the sole scope authority. CRM and CRM AI are explicitly out of scope, and any future CRM transfer/integration remains deferred with no fields or mechanisms specified.

Requirements 1–4 map to baseline §4.C steps 1–3 and capability rows 74–76. Requirement 5 preserves the open/deferred boundaries and scope exclusions in baseline §§7 and 9. No source-code or legacy-document behavior is promoted into product scope by this spec.
