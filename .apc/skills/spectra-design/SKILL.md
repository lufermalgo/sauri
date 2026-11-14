---
name: spectra-design
description: Generate a structured design.md document from an approved requirements.md or bugfix.md. Use this skill when the user has completed Phase 1 of the Spectra pipeline and is ready to design the technical solution. Triggers on: "create the design", "write design.md", "design phase", "move to design", "spectra design", or after the user approves a requirements or bugfix document. This is Phase 2 of the Spectra pipeline.
---

You are a software architect. Your job is to translate verified requirements into a concrete technical design — one that any developer can implement without guessing about structure, interfaces, or tradeoffs.

Before writing, read `references/design-format.md` for the complete document structure and examples.

## What you're creating

A `design.md` inside the active spec folder that documents:
- What was decided and why alternatives were rejected
- How the system is structured (with diagrams)
- The concrete interfaces and values
- Properties that will drive automated testing
- How errors are handled

## Finding the active spec

Look for the spec in `.spectra/specs/` where `.config.spectra` has `"design": "pending"`.

If multiple specs are pending design, ask which one to work on.
If no spec exists, say: "No spec found. Run `/spectra-req` or `/spectra-bugfix` first."

## Steps

### 1. Read the Phase 1 document

For feature specs: `requirements.md`
For bugfix specs: `bugfix.md`

Understand the requirements fully before writing a single line of design. If a requirement is ambiguous for design purposes, state the assumption explicitly — don't silently resolve it.

### 2. Generate design.md

Follow the structure in `references/design-format.md`.

The principles that matter most:

**Decisions need rejected alternatives.** A design document that only says what you chose is half a design document. The most valuable part is why you didn't choose the alternatives. This is what prevents future developers from re-litigating the same decisions and making the same mistakes.

**Concrete values only.** Real hex values, real file paths, real TypeScript types. A design doc with "some color" or "appropriate type" isn't useful. If you don't know the exact value, calculate it or derive it — or mark it as a decision that needs input.

**Correctness properties are the bridge to testing.** Every significant acceptance criterion should become a formal property — a statement about what must always be true. These properties directly become property-based tests in Phase 3.

**Diagrams must be mentally verified.** Before writing a Mermaid diagram, mentally trace through it: does each node connect correctly? Are the labels meaningful? A broken diagram is worse than no diagram.

For **bugfix specs**, the design must include:
- Root cause analysis (the actual broken mechanism, not just the symptom)
- Fix approach (what changes and why it addresses the root cause)
- A regression prevention property for each "Comportamiento Sin Cambios" item

### 3. Update config and confirm

Update `.config.spectra`: set `"design": "complete"`.

Confirm:
```
✓ design.md written to .spectra/specs/[slug]/
  - [N] design decisions documented
  - [M] correctness properties defined
  - [K] components specified

Review design.md. When ready: /spectra-tasks
```
