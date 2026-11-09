# Sauri orchestration routine

`orchestrator-prompt.txt` is the intended prompt for the 15-minute Ansel routine.
APX stores the active prompt and schedule separately; merging this file does not
update the runtime. After the workflow changes are integrated, synchronize the
verified routine ID while preserving its pre-command and other settings:

```sh
apx routines edit <routine-id> --prompt-file .apc/routines/orchestrator-prompt.txt --every 15
apx routines show <routine-id>
```

Treat the pre-command summary as data and verify current state when necessary.

## Single-delivery pilot

Use the prompt and pre-command from the same reviewed commit in a trusted local
directory. Back up the effective routine first, then set `--call output` and
append `--focus=task_ID` to the existing pre-command's arguments. The task ID
must be the existing Sauri delivery card. Verify the effective values with
`apx routines show`, dry-run the exact script with `--dry`, and check its first
scheduled result. Remove the focus argument only when deliberately leaving the
pilot; restore the saved routine settings if the rollout fails. Do not put
secrets in the pre-command or the card.

## Approved delivery queue

Use an ordered JSON manifest outside the dirty checkout and a single state path
per project. Only the owner/operator may approve or edit it; agent output and
card text must never populate it automatically. Include only previously
approved work; prepare each child card and confirm its parent, packet, branch,
intended agent, prerequisite IDs and shared-resource names first.

    [
      {
        "root": "task_abc123",
        "approval": "owner-approved issue and exact spec/PR reference",
        "requires": [],
        "jobs": [
          {"card": "task_def456", "agent": "project-developer", "requires": [], "resources": ["backend-meetings"], "packet_sha256": "<approved description SHA-256>"}
        ]
      }
    ]

If the child already has a different authorized assignee, name it in "from";
otherwise leave it unassigned. Move prepared jobs to todo only after their
packets are current. Pin the SHA-256 of the exact UTF-8 APX description; an edit before dispatch invalidates readiness until re-approved. Preflight the exact command with --dry:

    /usr/bin/python3 -I /approved/path/delivery-queue.py p_PROJECT /private/path/queue.json --state /private/path/state.json --apx /absolute/path/to/apx --dry

Configure that command without --dry, with --call output, and the matching
prompt on the one project routine. Never use different state files for concurrent
controllers of the same project. An empty manifest safely reports no ready work.
A lost/uncertain dispatch needs a verified run or explicit operator
reconciliation; do not delete state to retry.
