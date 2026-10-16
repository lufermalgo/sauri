# Requirements — Meeting Summaries and Templates

## Introduction

The owner-approved baseline defines a structured summary associated with a meeting, distinct from its notes and transcript. Users need to scan a summary for the meeting's main topic and key arguments or points, and copy or download it. The baseline also confirms editable user-defined summary templates and a selectable default. Fer's 2026-10-16 template decision further establishes that templates are personal, users can create multiple templates with specific instructions, the default is configured in Sauri web, and the personal default is applied automatically when summarizing a transcript without requiring an extra confirmation.

**Core idea:** Present each meeting summary as a distinct, clearly organized artifact, and let each user shape summary output with personal templates and a personal default.

**Scope:** These requirements cover summary content, retrieval, creating multiple personal templates with specific instructions, configuring and automatically applying a personal default from Sauri web, optional template categories as allowed by the baseline, and deletion of a persisted structured summary together with its transcript when that transcript expires or is deleted.

**Out of scope / unresolved boundaries:** The internal structure, schema, and format of templates are deferred. No template name, seed template, category defaults, or fallback behavior is specified. The summary-generation method and accuracy threshold, fixed visual layout, broader access-control mechanisms or policy, and meeting portal layout remain unspecified. The transcript-triggered deletion rule is limited to the persisted structured summary associated with that transcript; it does not define a retention period or any broader deletion guarantee. CRM integration is out of scope.

**Authority and traceability:** These requirements derive from the owner-approved `PRODUCT_BASELINE.md` exact content at commit `26d44ca7b212097c82415d0ae038bd9d096873d4` (blob `3afefd5e3da230cc3e26d7b89e74f48dc01d82ae`), principally §§4.C.5, 5, 7.10, and 9, plus Fer's 2026-10-16 template decision. The latter resolves the baseline's previously open questions about personal templates and defaults. Requirement 6 preserves the approved transcript-triggered deletion rule. No current implementation is used to extend scope.

Existing source code, tests, and prior implementation choices are evidence of current state only; they do not constitute product acceptance or authorization to extend behavior. Future implementation must be evaluated against approved requirements and evidence.

## Glossary

- **Meeting_Summary**: A structured summary associated with a meeting and presented as a distinct artifact, not as meeting notes or transcript.
- **Summary_Template**: A personal, user-created template with specific instructions that shape summary output; its internal structure, schema, and format are not defined here.
- **Template_Category**: An optional grouping to which a summary template may be assigned; a category can contain multiple templates.
- **Persisted_Meeting_Summary**: A structured meeting summary stored for a meeting, rather than a transient view of summary content.

## Requirements

### Requirement 1: Distinct, structured meeting summary

**User Story:** As a Sauri user, I want a clear summary of a meeting's main topic and key points, so I can understand its substance without treating notes or transcript as the summary.

#### Acceptance Criteria

1. THE Sauri meeting view SHALL present the **Meeting_Summary** as a distinct meeting artifact, separate from meeting notes and the transcript.
2. THE system SHALL make a **Meeting_Summary** available for the meeting and SHALL organize its content clearly so that its main topic and key arguments or points can each be identified.
3. THE **Meeting_Summary** SHALL be associated with the meeting it summarizes.

**Traceability:** Owner-approved `PRODUCT_BASELINE.md` §4.C.5 and §5 (structured summary capability and content); discovery §2.4 and §2.3 (summary content and distinction from transcript/notes).

### Requirement 2: Copy or download a meeting summary

**User Story:** As a Sauri user, I want to copy or download a meeting summary, so I can reuse or review it outside the meeting view.

#### Acceptance Criteria

1. WHEN a **Meeting_Summary** is available, THE user SHALL be able to copy its content.
2. WHEN a **Meeting_Summary** is available, THE user SHALL be able to download it.

**Traceability:** Owner-approved `PRODUCT_BASELINE.md` §4.C.5 and §5 (copy/download); discovery §2.3–2.4 (copy/download expectation).

### Requirement 3: Create personal templates with specific instructions

**User Story:** As a Sauri user, I want to create multiple personal summary templates with specific instructions, so I can shape summaries for different needs.

#### Acceptance Criteria

1. THE system SHALL associate each personal **Summary_Template** with the user who created it.
2. THE user SHALL be able to create multiple personal **Summary_Template** instances in Sauri web, each with specific instructions.
3. THE owner of a personal **Summary_Template** SHALL be able to edit it after it has been created.
4. WHEN a user attempts to edit a **Summary_Template** owned by another user, THE system SHALL prevent the edit.
5. WHEN a user attempts to select a **Summary_Template** owned by another user for a **Meeting_Summary**, THE system SHALL prevent applying that template.
6. WHEN a **Summary_Template** is applied to a **Meeting_Summary**, THE resulting summary SHALL reflect that template's specific instructions.

**Traceability:** Owner-approved `PRODUCT_BASELINE.md` §5 confirms user-defined, editable templates. Fer's 2026-10-16 decision establishes multiple personal templates, each with specific instructions. Internal template structure, schema, and format remain deferred.

### Requirement 4: Optionally group templates by category

**User Story:** As a Sauri user, I want to group summary templates by category when useful, so I can distinguish templates serving different purposes without requiring every template to belong to a category.

#### Acceptance Criteria

1. WHEN the user chooses to group templates, THE user SHALL be able to assign a **Summary_Template** to a **Template_Category**.
2. THE system SHALL allow multiple **Summary_Template** instances to be assigned to the same **Template_Category**.
3. THE system SHALL allow a **Summary_Template** to exist without assignment to a **Template_Category**.

**Traceability:** Owner-approved `PRODUCT_BASELINE.md` §5 confirms optional category grouping and multiple templates per category. Fer's 2026-10-16 decision establishes that a user's personal default is not scoped by category. Category defaults are not defined.

### Requirement 5: Configure and automatically apply a personal default

**User Story:** As a Sauri user, I want to configure my personal default summary template in Sauri web, so it is applied automatically when I summarize a transcript without requiring an extra confirmation.

#### Acceptance Criteria

1. THE user SHALL be able to configure one **Summary_Template** that they own as their personal default in Sauri web.
2. WHEN a user attempts to configure a **Summary_Template** owned by another user as their default, THE system SHALL prevent that configuration.
3. WHEN the system presents available summary templates to the user, THE system SHALL identify that user's configured default **Summary_Template**.
4. WHEN the user explicitly chooses a personal **Summary_Template** for a transcript summary, THE system SHALL apply that chosen template to that summary.
5. WHEN the user summarizes a transcript without making an explicit template choice for that summary, THE system SHALL automatically apply that user's configured default **Summary_Template** without requiring an additional confirmation.
6. WHEN the user changes their configured default **Summary_Template**, THE system SHALL apply the newly configured default to subsequent transcript summaries for which the user makes no explicit template choice.
7. THE personal default SHALL apply across template categories.

**Constraint:** This requirement does not define behavior when no personal default is configured, category-specific defaults, template fallback behavior, or any additional template-choice flow beyond the stated automatic application. It does not specify how a **Meeting_Summary** is generated.

**Traceability:** Owner-approved `PRODUCT_BASELINE.md` §5 supports user-defined editable templates, a selectable default, and optional category grouping. Fer's 2026-10-16 decision establishes configuration from Sauri web, automatic application without an extra confirmation when no explicit choice is made, and the cross-category personal default. It does not define fallback behavior when no default exists.

### Requirement 6: Delete persisted summary with transcript

**User Story:** As a Sauri user, I want a persisted structured summary deleted with its transcript when that transcript expires or is deleted, so the summary does not remain after its transcript is removed.

#### Acceptance Criteria

1. WHEN a transcript expires or is deleted, THE system SHALL delete the associated **Persisted_Meeting_Summary** together with that transcript.

**Traceability:** Owner-approved `PRODUCT_BASELINE.md` §7.10 and §9, commit `26d44ca7b212097c82415d0ae038bd9d096873d4`, blob `3afefd5e3da230cc3e26d7b89e74f48dc01d82ae` (Fer's 2026-10-16 decision). This rule does not specify a retention period or any broader deletion guarantee.
