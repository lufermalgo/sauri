# Requirements — Meeting Summaries and Templates

## Introduction

The baseline snapshot assigned to this task defines a structured summary associated with a meeting, distinct from its notes and transcript. Users need to scan a summary for the meeting's main topic and key arguments or points, and take a copy or download it for later use. It also defines user-created, editable summary templates and a selectable default so users can shape summary output.

**Core idea:** Treat each meeting summary as a distinct, clearly organized meeting artifact, and let users shape its structure through their own editable templates.

**Scope:** These requirements cover the observable content and retrieval of meeting summaries, and creating, editing, optionally categorizing, and selecting a default for user-defined summary templates.

**Out of scope / unresolved boundaries:** This spec does not select a summary-generation method or accuracy threshold, prescribe a template schema or fixed visual layout, settle whether templates/defaults are personal or shared or how defaults apply across categories, or define the meeting portal layout. These remain open and must not be silently decided here. This spec does not extend to CRM integration.

**Authority and traceability:** This spec is scoped to the owner-approved baseline content assigned to task `t_1mifoa` (`PRODUCT_BASELINE.md`, commit `d738e78d65940f17d209edf9a54af5d34e92e059`, blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`). The approval record in the current `PRODUCT_BASELINE.md` applies to that exact content. The requirements trace to its §4.C.5 and §5 capability entries, and to the recorded product intent in `PRODUCT_DISCOVERY.md` §2.4 and the open template-sharing/default-selection boundary in §5. No other baseline version or current implementation is used to extend scope.

Existing source code, tests, and prior implementation choices are evidence of current state only. They do not constitute product acceptance or authorization to extend existing behavior; any future implementation must be evaluated against approved requirements and evidence.

## Glossary

- **Meeting_Summary**: A structured summary associated with a meeting and presented as a distinct artifact, not as meeting notes or transcript.
- **Summary_Template**: A user-defined, editable structure that shapes summary output.
- **Template_Category**: An optional grouping to which a summary template can be assigned; a category can contain multiple templates.

## Requirements

### Requirement 1: Distinct, structured meeting summary

**User Story:** As a Sauri user, I want a clear summary of a meeting's main topic and key points, so I can understand its substance without treating notes or transcript as the summary.

#### Acceptance Criteria

1. THE Sauri meeting view SHALL present the **Meeting_Summary** as a distinct meeting artifact, separate from meeting notes and the transcript.
2. WHEN a **Meeting_Summary** is available, THE Sauri meeting view SHALL organize its content clearly so that its main topic and key arguments or points can each be identified.
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

1. THE user SHALL be able to create a user-defined **Summary_Template**.
2. THE user SHALL be able to edit a user-defined **Summary_Template** after it has been created.
3. WHEN a **Summary_Template** is used to shape a **Meeting_Summary**, THE resulting summary structure SHALL reflect the selected template.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 (user-defined, editable templates); `PRODUCT_DISCOVERY.md` §2.4 (template intent).

### Requirement 4: Optionally group templates by category

**User Story:** As a Sauri user, I want to group summary templates by category when useful, so I can distinguish templates serving different purposes without requiring every template to belong to a category.

#### Acceptance Criteria

1. WHEN the user chooses to group templates, THE user SHALL be able to assign a **Summary_Template** to a **Template_Category**.
2. THE system SHALL allow multiple **Summary_Template** instances to be assigned to the same **Template_Category**.
3. THE system SHALL allow a **Summary_Template** to exist without assignment to a **Template_Category**.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 (templates may be grouped by category, with multiple templates per category); `PRODUCT_DISCOVERY.md` §2.4 (category grouping) and §5, question 3 (default scope across categories remains open).

### Requirement 5: Designate a default summary template

**User Story:** As a Sauri user, I want to designate a default summary template, so I can choose my preferred template.

#### Acceptance Criteria

1. THE user SHALL be able to designate a user-defined **Summary_Template** as the default template.
2. WHEN the system presents available summary templates, THE system SHALL identify the template designated as default.

**Constraint:** This requirement defines designation and identification only. It does not specify whether designation automatically selects a template when producing a **Meeting_Summary** or how default selection is scoped across categories. Whether templates/defaults are personal or shared also remains open.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 (selectable default); `PRODUCT_DISCOVERY.md` §2.4 and §5, open question 3 (sharing and category scope unresolved).

**Scope boundaries:** This spec does not select a summary-generation method, accuracy threshold, or fixed layout. It does not decide whether templates/defaults are personal or shared, how default selection is scoped across categories, or whether templates must be assigned to a category. The proposed example `General > Resumen básico` and visual-reference labels are not approved defaults. CRM integration and CRM AI are excluded as deferred scope. These are scope limits, not additional user-visible acceptance behaviors.
