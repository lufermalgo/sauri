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
