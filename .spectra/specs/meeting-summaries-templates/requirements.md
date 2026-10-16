# Requirements — Meeting Summaries and Templates

## Introduction

The baseline snapshot assigned to this task defines a structured summary associated with a meeting, distinct from its notes and transcript. Users need to scan a summary for the meeting's main topic and key arguments or points, and take a copy or download it for later use. It also defines user-created, editable summary templates and a selectable default so users can shape summary output.

**Core idea:** Treat each meeting summary as a distinct, clearly organized meeting artifact, and let users shape its structure through editable, user-defined templates.

**Scope:** These requirements cover the observable content and retrieval of meeting summaries, creating, editing, optionally categorizing, and selecting a default for user-defined summary templates, and the deletion of a persisted structured summary together with its transcript when that transcript expires or is deleted. Each user's templates are personal to that user. The user selects one personal default in platform settings; that default applies across all categories and is automatically applied to every transcription summary for that user until the user changes it. The requirements do not specify behavior when no default is configured. The initial release has one defined template.

**Out of scope / unresolved boundaries:** The owner-approved decision establishes personal templates and one personal default across categories. The transcript-triggered deletion rule is limited to the persisted structured summary associated with that transcript; it does not define a retention period or any broader deletion guarantee. Still unresolved are the summary-generation method and accuracy threshold, template schema and fixed visual layout, broader access-control mechanisms or policy, and meeting portal layout. These matters must not be silently decided here. This spec does not extend to CRM integration.

**Authority and traceability:** This spec is scoped to the exact owner-approved `PRODUCT_BASELINE.md` content at commit `26d44ca7b212097c82415d0ae038bd9d096873d4` (blob `3afefd5e3da230cc3e26d7b89e74f48dc01d82ae`). The requirements trace to baseline §4.C.5 and §5 capability entries and discovery §2.4. These sources support meeting summaries, user-defined editable templates, optional categories, and a selectable default. The personal ownership, cross-category default, automatic application, and initial-template rules trace to Fer's 2026-10-15 owner decision. Requirement 6 traces to the baseline's §7.10 and §9 statement of Fer's 2026-10-16 decision: a persisted structured summary is deleted with its transcript when the transcript expires or is deleted. The baseline does not specify a retention period or any broader deletion guarantee. Behavior when no default is configured and other policy questions remain unspecified. No current implementation is used to extend scope.

Existing source code, tests, and prior implementation choices are evidence of current state only. They do not constitute product acceptance or authorization to extend existing behavior; any future implementation must be evaluated against approved requirements and evidence.

## Glossary

- **Meeting_Summary**: A structured summary associated with a meeting and presented as a distinct artifact, not as meeting notes or transcript.
- **Summary_Template**: A user-defined, editable structure that shapes summary output.
- **Template_Category**: An optional grouping to which a summary template can be assigned; a category can contain multiple templates.
- **Persisted_Meeting_Summary**: A structured meeting summary stored for a meeting, rather than a transient view of summary content.

## Requirements

### Requirement 1: Distinct, structured meeting summary

**User Story:** As a Sauri user, I want a clear summary of a meeting's main topic and key points, so I can understand its substance without treating notes or transcript as the summary.

#### Acceptance Criteria

1. THE Sauri meeting view SHALL present the **Meeting_Summary** as a distinct meeting artifact, separate from meeting notes and the transcript.
2. THE system SHALL make a **Meeting_Summary** available for the meeting and SHALL organize its content clearly so that its main topic and key arguments or points can each be identified.
3. THE **Meeting_Summary** SHALL be associated with the meeting it summarizes.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §4.C.5 and §5 (structured summary capability); `PRODUCT_DISCOVERY.md` §2.4 and §2.3 (summary content and distinction from transcript/notes).

### Requirement 2: Copy or download a meeting summary

**User Story:** As a Sauri user, I want to copy or download a meeting summary, so I can reuse or review it outside the meeting view.

#### Acceptance Criteria

1. WHEN a **Meeting_Summary** is available, THE user SHALL be able to copy its content.
2. WHEN a **Meeting_Summary** is available, THE user SHALL be able to download it.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §4.C.5 and §5 (copy/download); `PRODUCT_DISCOVERY.md` §2.3–2.4 (copy/download expectation).

### Requirement 3: Create and edit user-defined summary templates

**User Story:** As a Sauri user, I want to create and edit my own summary templates, so I can shape how meeting summaries are organized.

#### Acceptance Criteria

1. THE user SHALL be able to create a personal **Summary_Template** associated with that user.
2. THE user SHALL be able to edit a personal **Summary_Template** associated with that user after it has been created.
3. WHEN a **Summary_Template** is used to shape a **Meeting_Summary**, THE resulting summary structure SHALL reflect the selected template.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 supports user-defined, editable templates. Fer's 2026-10-15 owner decision establishes that each user's templates are personal to that user and that a user can have multiple templates.

### Requirement 4: Optionally group templates by category

**User Story:** As a Sauri user, I want to group summary templates by category when useful, so I can distinguish templates serving different purposes without requiring every template to belong to a category.

#### Acceptance Criteria

1. WHEN the user chooses to group templates, THE user SHALL be able to assign a **Summary_Template** to a **Template_Category**.
2. THE system SHALL allow multiple **Summary_Template** instances to be assigned to the same **Template_Category**.
3. THE system SHALL allow a **Summary_Template** to exist without assignment to a **Template_Category**.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 confirms that templates may be grouped by category and that multiple templates may share a category. Fer's 2026-10-15 owner decision establishes that each user's personal default is independent of category; category grouping does not create a separate default per category.

### Requirement 5: Select and automatically apply the default summary template

**User Story:** As a Sauri user, I want to select my default summary template in platform settings, so my chosen template is used for transcription summaries.

#### Acceptance Criteria

1. THE initial release SHALL include one defined **Summary_Template**.
2. THE user SHALL be able to have multiple **Summary_Template** instances.
3. THE user SHALL be able to select one personal **Summary_Template** as that user's default in platform settings, and that default SHALL apply across all categories.
4. WHEN the system presents available summary templates, THE system SHALL identify the user's selected default **Summary_Template**.
5. WHEN the system generates a transcription summary for a user who has configured a default in platform settings, THE system SHALL automatically apply that configured **Summary_Template** to shape the summary, regardless of the template's category.
6. WHEN the user changes the configured default **Summary_Template** in platform settings, THE system SHALL apply the newly selected default to subsequent transcription summaries.

**Constraint:** Each **Summary_Template** is personal to an individual user, and each user has one personal default that applies across all categories. This requirement does not define broader access-control mechanisms or policy. Behavior when a user has no personal default configured remains unspecified. This requirement does not specify how a **Meeting_Summary** is produced. Transcript-triggered deletion of a persisted structured summary is specified only in Requirement 6.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 supports user-defined, editable templates, a selectable default, and optional category grouping. Fer's 2026-10-15 owner decision establishes personal templates, multiple templates per user, selection of one personal default in platform settings, application of that default across categories to each transcription summary until the user changes it, and one defined template in the initial release. The baseline does not define personal ownership, cross-category default scope, or automatic application; those rules trace to the owner decision. Behavior when no default is configured is not defined by either source.

**Scope boundaries:** This spec does not select a summary-generation method, accuracy threshold, or fixed layout. It does not define broader access-control mechanisms or policy, a retention period, deletion guarantees beyond Requirement 6, or whether templates must be assigned to a category. The proposed example `General > Resumen básico` and visual-reference labels are not approved defaults. CRM integration and CRM AI are excluded as deferred scope. These are scope limits, not additional user-visible acceptance behaviors.

### Requirement 6: Delete persisted summary with transcript

**User Story:** As a Sauri user, I want a persisted structured summary deleted with its transcript when that transcript expires or is deleted, so the summary does not remain after its transcript is removed.

#### Acceptance Criteria

1. WHEN a transcript expires or is deleted, THE system SHALL delete the associated **Persisted_Meeting_Summary** together with that transcript.

**Traceability:** Owner-approved `PRODUCT_BASELINE.md` §7.10 and §9, commit `26d44ca7b212097c82415d0ae038bd9d096873d4`, blob `3afefd5e3da230cc3e26d7b89e74f48dc01d82ae` (Fer's 2026-10-16 decision). This rule does not specify a retention period or any broader deletion guarantee.
