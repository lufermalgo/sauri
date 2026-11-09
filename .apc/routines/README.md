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
