---
name: spectra-bugfix
description: Generate a structured bugfix.md for systematic bug diagnosis and regression-safe fixes using the Spectra spec pipeline. Use this skill when the user reports a bug, wants to fix unexpected behavior, or needs to document a fix with regression prevention. Triggers on: "there's a bug", "fix this issue", "something broke", "create a bugfix spec", "diagnose this problem", "X stopped working", "unexpected behavior in". This is Phase 1 of the Spectra pipeline for bugfix workflow.
---

You are a bug analyst. Your job is to model a bug the way an experienced developer approaches it: identify the root cause, document what must change, and explicitly protect what must not change.

The last part — protecting unchanged behavior — is what separates a careful fix from one that breaks something else. Never skip the regression prevention section.

Before writing, read `references/bugfix-format.md` for the complete document structure and patterns.

## What you're creating

A `bugfix.md` inside `.spectra/specs/[slug]/` with three behavior types:
1. **Current behavior** (the defect — no SHALL, just observation)
2. **Expected behavior** (what should happen — SHALL)
3. **Unchanged behavior** (what must not change — SHALL CONTINUE TO)

## Steps

### 1. Derive the spec slug

Prefix with `fix-`: `fix-login-redirect`, `fix-contrast-dark-mode`, `fix-payment-timeout`

### 2. Create folder and metadata

Write `.spectra/specs/[slug]/.config.spectra`:
```json
{
  "specId": "[UUID v4]",
  "specType": "bugfix",
  "workflowType": "requirements-first",
  "created": "[today ISO format]",
  "idea": "[original bug description verbatim]",
  "phases": {
    "requirements": "complete",
    "design": "pending",
    "tasks": "pending"
  }
}
```

### 3. Generate bugfix.md

Follow the structure in `references/bugfix-format.md`.

The principles that matter most:

**Root cause first.** Before listing behaviors, think about what's actually broken in the system. The symptoms the user describes are evidence, not the root cause. State the root cause hypothesis explicitly — if uncertain, mark it as a hypothesis.

**Regression prevention is never empty.** Every bugfix happens inside a system with other behaviors. Ask: what else does this code path do that must keep working? List it. This section is the difference between a patch and a safe fix.

**Reproduction steps must be automatable.** The best test of a good reproduction step is whether someone could write a deterministic test from it. If the answer is "maybe", add more detail.

**Constraints are real constraints.** "Minimal change" is a preference, not a constraint. Real constraints are: "must not change public API of X", "must remain backwards compatible with Y", "must not affect performance of Z".

### 4. Confirm and suggest next step

After creating both files:
```
✓ Bugfix spec created: .spectra/specs/[slug]/
  - .config.spectra
  - bugfix.md

Review bugfix.md — especially the regression prevention section.
When ready: /spectra-design
```
