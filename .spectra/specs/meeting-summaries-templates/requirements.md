# Requirements — Meeting Summaries and Templates

## Introduction

The baseline snapshot assigned to this task defines a structured summary associated with a meeting, distinct from its notes and transcript. Users need to scan a summary for the meeting's main topic and key arguments or points, and take a copy or download it for later use. It also defines user-created, editable summary templates and a selectable default so users can shape summary output.

**Core idea:** Treat each meeting summary as a distinct, clearly organized meeting artifact, and let users shape its structure through their own editable templates.

**Scope:** These requirements cover the observable content and retrieval of meeting summaries, and creating, editing, optionally categorizing, and selecting a default for user-defined summary templates. Each template belongs personally to the user who creates it. A user's designated default applies across that user's categories rather than being selected separately per category.

**Out of scope / unresolved boundaries:** Template ownership is personal to the creating user, and the user's designated default applies across categories. Still unresolved are the summary-generation method and accuracy threshold, template schema and fixed visual layout, broader access-control mechanisms or policy, retention/deletion rules, and meeting portal layout. These matters must not be silently decided here. This spec does not extend to CRM integration.

**Authority and traceability:** This spec is scoped to the owner-approved baseline content assigned to task `t_1mifoa` (`PRODUCT_BASELINE.md`, commit `d738e78d65940f17d209edf9a54af5d34e92e059`, blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`), with the subsequent owner decision recorded as `d_qfyygr` on task `t_i680bu`: templates are personal to each user, and each user's default is user-wide across categories. The requirements trace to baseline §4.C.5 and §5 capability entries, discovery §2.4 and the cited owner decision. The baseline's earlier open boundary is resolved only for template ownership and default scope; other policy questions remain open. No current implementation is used to extend scope.

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

1. THE user SHALL be able to create a personal **Summary_Template**.
2. THE user SHALL be able to edit a personal **Summary_Template** after it has been created.
3. WHEN a **Summary_Template** is used to shape a **Meeting_Summary**, THE resulting summary structure SHALL reflect the selected template.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 (user-defined, editable templates); `PRODUCT_DISCOVERY.md` §2.4 (template intent); owner decision `d_qfyygr` on task `t_i680bu` (templates are personal to each user).

### Requirement 4: Optionally group templates by category

**User Story:** As a Sauri user, I want to group summary templates by category when useful, so I can distinguish templates serving different purposes without requiring every template to belong to a category.

#### Acceptance Criteria

1. WHEN the user chooses to group templates, THE user SHALL be able to assign a **Summary_Template** to a **Template_Category**.
2. THE system SHALL allow multiple **Summary_Template** instances to be assigned to the same **Template_Category**.
3. THE system SHALL allow a **Summary_Template** to exist without assignment to a **Template_Category**.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 (templates may be grouped by category, with multiple templates per category); `PRODUCT_DISCOVERY.md` §2.4 (category grouping) and §5, question 3 (historical open question on template sharing/default scope, superseded only for ownership and default scope by owner decision `d_qfyygr`).

### Requirement 5: Designate a default summary template

**User Story:** As a Sauri user, I want to designate a default summary template, so I can choose my preferred template.

#### Acceptance Criteria

1. THE user SHALL be able to designate a personal **Summary_Template** as that user's single default across all **Template_Category** instances.
2. WHEN the system presents available summary templates, THE system SHALL identify the user's designated default **Summary_Template** across categories.
3. WHEN the user requests a **Meeting_Summary** without selecting a template, THE system SHALL use that user's designated default **Summary_Template** to shape the summary, regardless of the template's **Template_Category**.

**Constraint:** The default is user-wide across categories, not category-specific. This requirement does not specify how a **Meeting_Summary** is produced, broader access-control mechanisms or policy, or retention/deletion behavior.

**Traceability:** Assigned baseline `PRODUCT_BASELINE.md` §5 (selectable default); `PRODUCT_DISCOVERY.md` §2.4; owner decision `d_qfyygr` on task `t_i680bu` (personal ownership and user-wide default across categories). This decision supersedes only the corresponding open boundary noted in the earlier discovery record.

**Scope boundaries:** This spec does not select a summary-generation method, accuracy threshold, or fixed layout. Templates are personal to their creating user; the designated default is that user's default across categories. It does not determine broader access-control mechanisms or policy, retention/deletion rules, or whether templates must be assigned to a category. The proposed example `General > Resumen básico` and visual-reference labels are not approved defaults. CRM integration and CRM AI are excluded as deferred scope. These are scope limits, not additional user-visible acceptance behaviors.
