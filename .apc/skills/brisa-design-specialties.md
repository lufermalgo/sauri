---
name: brisa-design-specialties
description: Project-specific activation matrix and design checks for Brisa's software-architecture specializations in Sauri.
---

# Brisa design specializations

This is an APC project rubric, not a claim that a native runtime Skill is installed. Ansel selects specializations from the approved requirements; Brisa applies the relevant checks together. `spectra-design` is mandatory for every design. A specialization is a lens on approved scope, never permission to add product scope.

## Activation matrix

| Specialization | Activate when the approved requirements include | Architecture checks |
| --- | --- | --- |
| `web-application` | Browser-based portal, dashboard, or web UI | Route/component boundaries, state ownership, responsive and accessible behavior where specified, API integration, authentication/session boundaries, loading/error/empty states, browser compatibility, and deploy/runtime boundaries. |
| `mobile-application` | Native or cross-platform mobile clients | Native vs cross-platform choice and rationale, app lifecycle, OS permissions, secure local storage, offline/sync behavior, background execution limits, deep links/notifications where required, network failure/retry, and release/platform constraints. Do not assume a mobile client exists. |
| `chrome-extension` | Chrome APIs, browser UI, extension permissions, content scripts, service worker, or extension packaging | Manifest V3, least-privilege permissions/host access, service-worker lifecycle, content-script isolation, messaging, storage, offscreen documents/media capture if required, web/backend integration, privacy boundaries, and Chrome Web Store constraints. Native Skill: `chrome-extensions` (required when available in the target runtime). |
| `backend-api` | APIs, backend services, persistence, processing, or external integrations | API contracts, domain/service/repository boundaries, authn/authz, validation, idempotency, data ownership, persistence/schema migrations, async jobs/queues, error/retry semantics, observability, retention, and deployment/runtime constraints. |
| `cross-surface-integration` | A capability spans two or more clients/services (for example extension + backend + web portal) | Source of truth, identity/auth handoff, API/schema compatibility, event/data lifecycle, sync and retries, failure ownership, versioning, privacy boundaries, and end-to-end correctness across all surfaces. Activate every applicable surface specialization as well. |

Apply security/privacy and sensitive-data analysis across all selected specialties. Route changes involving authentication, authorization, storage/retention, tenant isolation, integrations, or sensitive data through Ansel's required Security review in addition to the design review.

## Skill selection and availability

- Always list and use `spectra-design`; read its design-format reference before authoring.
- Add `chrome-extensions` when `chrome-extension` is active. The skill must be available to the target Codex runtime or explicitly injected by APX.
- For other selected specializations, Ansel must list any matching native Skills actually available to that runtime. Do not infer availability from a personal-library path or invent a Skill name. The specialization rubric and verified Sauri repository/context are the baseline when no other domain Skill is available.
- If the handoff claims an unavailable Skill is active, stop at preflight and return the exact missing Skill/context to Ansel. Do not ask the owner to resolve a runtime binding unless a genuine owner authorization is required.

## Sauri-specific guardrails

- The repository currently contains a Chrome extension, backend, and web frontend, but the target product baseline is being redefined. Do not activate those domains merely because they exist in the repository; derive active specialties from the approved requirements.
- `.apc/skills/sauri-project-context.md` describes existing stack and patterns. Treat them as verified current-state facts, not automatically approved target architecture. Reuse only when requirements, constraints, and trade-offs support it.
- If the approved scope spans extension, backend, and portal, activate `chrome-extension`, `backend-api`, `web-application`, and `cross-surface-integration` together, plus any relevant security/privacy review.
