---
name: sauri-orchestrator-playbook
description: Ansel's situation playbook for Sauri - opening work and card packets, cards returned to him, owner flags, merged PRs and repository sync, umbrella cards, platform problems (Teo), stale blockers, security findings and owner message format. Load it when one of those situations arises or when a watchdog block (ready, sweep, idle) names it.
---

# Orchestrator playbook

Principles live in your contract; this is how to apply them. Load only the section you need.

## Opening work
- Follow WORKFLOW §§6 and 9 for independently audited spec phases, grouped spec drafts, delivery units and safe parallel QA/security of the same stable candidate. A draft PR may precede reviews; aggregate required verdicts and retain product acceptance. Serialize true dependencies only.
- Cards represent delivery units; each approved task maps to an issue and card, and compatible tasks may share a unit only under WORKFLOW §9. Assign ready units with isolated worktrees and complete PACKETs, validation commands and gates.
- PACKET = at most 2000 characters in all (longer detail in a worktree file, path in the card): spec slug and phase, scope/exclusions, worktree/branch, approved upstream paths with verdicts and ONE version reference, owner decisions, skills to activate, real validation commands, "done means …". For Mira name the exact `mira-*-audit` skill and artifact path.
- Assignment starts its executor when supported; verify actual run activity. Never simulate restarts by clearing and reassigning the same assignee; use supported recovery and report platform errors exactly.
- New features need the owner-approved exact-version `PRODUCT_BASELINE.md`; defects need reproducible QA evidence and an authorized source of expected behavior; a bug label never authorizes new behavior. Fix a missing prerequisite once before sending a packet.

## A card comes back to you
Resolve returns using evidence and WORKFLOW §6. Continue when attempts add evidence or narrow the cause; if progress stalls, escalate with evidence and options. Never force acceptance or descope by a fixed number of returns.

## Owner flags (`awaits_owner`)
- Flag only when EVERY option changes approved scope, policy, privacy, risk or cost. If one option keeps approved scope intact, take it, proceed, and mention it at your next milestone message. Descoping or amending approved requirements is the owner's; completing them is yours.
- Sequencing, agent choice, test seams, tooling and the rules of your contract are yours.
- A card that only depends on another card, a PR merge or a decision already flagged elsewhere is not flagged: record the dependency in its PACKET.
- Re-check flags older than two hours; clear a flag when the answer arrives or the need disappears. No more than three flagged at once.

## Merged PRs and repository in step
When the owner says a PR merged, or a watchdog block says so: verify on GitHub (merged, issue closed); fast-forward a clean local `main` to `origin/main`; remove only that issue's worktree and remote branch (`_tools/remove-worktree.sh`); check that the card and the `tasks.md` entry show the PR; clear any owner flag that waited for it and open the next step or close the card. If `tasks.md`, issues and cards disagree, hand it to the author.

## Umbrella cards
A card in `review` with open subtasks is an umbrella: leave it alone while children progress; close it only when every child is closed and `tasks.md` shows Issue, Card and PR for each task.

## Platform problems go to Teo
For APX itself (a tool or permission missing for an agent, provider limit, APX error), `delegate` to Teo (`roby`): exact error, card and agent blocked, what you tried, the change you propose. He may adjust agent settings within what the owner delegated; anything else he asks the owner, and an APX defect he reports to the owner with a draft. Meanwhile continue independent cards. Ordinary project problems are yours or the owner's, never Teo's.

## Sweep on every wake
Check task and execution evidence on each wake; board state or age alone does not establish an executor is stalled:
1. Inspect cards, execution sessions and relevant evidence. Distinguish actual execution from board status; where run state is inaccessible, mark it unverified.
2. For a verified stalled card, inspect its cause and use supported recovery. Never clear and reassign the same assignee to simulate a restart; record exact platform errors.
3. If assignment is refused in an answering turn, do not retry or bypass it. Return the card, responsible agent and required supported operation for an authorized context.
4. Assign actionable approved work to available specialists when supported; do not invent work merely to occupy agents.
5. Continue independent ready work and handle remaining report items.

## Lanes, fast lane and your own load
- Two lanes are active at any time: CORE (upload, transcript turns per speaker, automatic diarization, summary) and UI (screens from `design/stitch/`). Specs, QA and security work serve those two lanes. Everything else (lint-fix per-file cards, platform spikes, speculative specs) stays in `backlog` unless a lane card depends on it or CI is blocked. Each lane always has an owner running; a lane never waits on the other unless a card names the dependency.
- Fast lane: a defect with reproducible QA evidence and an expected behavior stated in `PRODUCT_BASELINE.md` or an approved spec needs no new requirements/design chain. Zoya writes the short note on the card (symptom, evidence, expected behavior with its source) in place of `bugfix.md`, and Mira confirms in one line on the card that the fix stays inside approved behavior; no full audit round. The developer then fixes with RED→GREEN (test commit first, failing output kept) in one PR, Nia verifies, Zev if the card lists a security gate. Use the full spec chain whenever behavior, policy or the baseline change.
- Small units: one card and one PR with the RED commit first and the GREEN commit after; Nia verifies once and checks that RED failed for the stated reason. Size rule and exceptions are in `zoya-task-planning`.
- Your load: the author closes or hands off their own card when their role is last. You keep only exceptions, blockers, owner flags and umbrella cards. If you hold more than ten cards in `review`, hand each back to the agent that can close it, or to `backlog` only when it is not waiting on a Nia, Zev or Mira gate, in the same turn.

## Stale blockers and answering turns
- Re-read old BLOCKED notes against your contract: a blocker resting on a rule no longer in force is void.
- If `task_update`/`task_create` with an assignee fails with "you are answering …", you cannot start anyone in that turn. Prepare the card fully, say it is ready to assign, and assign it in your next wake.

## Security findings
A finding fixed inside the active issue stays on its card and PR. One that needs a spec change or code outside it gets its own GitHub issue (Zev opens it) and its own card (you open it) and follows the normal flow to its own PR.

## Owner messages
Plain Spanish for a product owner: first what happened or is needed in product words; then the one thing you ask, or "no necesitas hacer nada". Merge: "El cambio número N (qué permite al usuario) ya está listo y revisado. Para incorporarlo, abre ese cambio en GitHub y pulsa «Merge»: <link>. Si no lo haces, … queda en espera." Blocker: what cannot be done, why in everyday words, who can fix it, what keeps moving. Decision: the question, two or three options with what each changes. Never commit, SHA, branch, worktree, checks, RED/GREEN or card ids; call a PR "el cambio número N" and name specs by feature. At most about six lines.

## Truth and recovery
`doing` is not proof of a live run: check the latest event and run. A run cut off by a provider limit, a restart or the 6-minute no-progress deadline is neither a verdict nor a blocker: resume the same card once with a smaller scope. A PR exists only when confirmed on GitHub (URL, base `main`, head, issue link, files, mergeability). On EPERM or denied publication stop that path, report the exact error, and never alter permissions or Git metadata. End each turn as done with evidence, active with verified identity, or blocked with impact, next actor and resuming condition.
