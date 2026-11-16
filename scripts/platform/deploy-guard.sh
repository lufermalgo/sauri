#!/usr/bin/env bash
# Refuse to restart the stack while a recording is still being processed.
#
#   scripts/platform/deploy-guard.sh <what is about to happen>
#
# Looks (read-only) at everything in flight: meetings not in a terminal state, speaker identification
# still open, summaries still being written, claims whose lease is live, and messages waiting or being
# handled in the processing queues. Exits 1 with the list when there is work in flight.
# FORCE=1 skips the check: work in flight is then given back to the queue and resumes after the restart
# (see "Restarting safely" in docs/operations/local-deployment.md), at the cost of redoing the step.
set -Eeuo pipefail

ACTION="${1:-restart the stack}"

if [[ "${FORCE:-}" == "1" ]]; then
  echo "FORCE=1: not checking for processing in flight before: ${ACTION}"
  exit 0
fi

if [[ -z "${QUEUE_MESSAGE_SIGNING_KEY:-}" && -r "${HOME}/.config/sauri/queue_signing_key" ]]; then
  QUEUE_MESSAGE_SIGNING_KEY="$(<"${HOME}/.config/sauri/queue_signing_key")"
  export QUEUE_MESSAGE_SIGNING_KEY
fi

running() { [[ -n "$(docker compose ps --status running --quiet "$1" 2>/dev/null)" ]]; }

found=""
fail_check() {
  echo "Could not check for processing in flight, so not continuing to: ${ACTION}" >&2
  echo "$1" >&2
  echo "Run again with FORCE=1 if you are sure nothing is being processed." >&2
  exit 1
}

# No database container running means nothing can be processing.
if running postgres; then
  read -r -d '' QUERY <<'SQL' || true
SELECT 'meeting', substr(m.id, 1, 8), m.process_state,
       coalesce(to_char(max(h.occurred_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI'), '?')
  FROM meetings m LEFT JOIN state_history h ON h.meeting_id = m.id
 WHERE m.process_state NOT IN ('completed', 'failed') GROUP BY m.id
UNION ALL
SELECT 'speakers', substr(meeting_id, 1, 8), diarization_state,
       to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI')
  FROM diarizations WHERE diarization_state IN ('pending', 'in_progress')
UNION ALL
SELECT 'summary', substr(meeting_id, 1, 8), status,
       coalesce(to_char(coalesce(started_at, requested_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI'), '?')
  FROM summary_request_outbox WHERE status IN ('pending', 'running')
UNION ALL
SELECT 'live-claim', substr(meeting_id, 1, 8), claim_kind,
       to_char(claim_expires_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI')
  FROM meeting_processing_claims
 WHERE claim_kind IN ('transcription', 'diarization') AND claim_expires_at > now()
ORDER BY 1, 4;
SQL
  if ! rows="$(docker compose exec -T postgres psql -U sauri -d sauri -v ON_ERROR_STOP=1 -tA -F ' ' -c "${QUERY}" 2>&1)"; then
    fail_check "${rows}"
  fi
  found+="${rows}"$'\n'
fi

# Messages waiting or being handled (unacknowledged), including the ones parked for a retry or a deferral.
if running rabbitmq; then
  if ! queues="$(docker compose exec -T rabbitmq rabbitmqctl -q list_queues name messages 2>&1)"; then
    fail_check "${queues}"
  fi
  found+="$(awk '$1 ~ /^(transcribe|diarize|summarize)(\.|$)/ && $2 + 0 > 0 { print "queue", $1, $2 " message(s)" }' <<<"${queues}")"$'\n'
fi

if [[ -n "${found//[[:space:]]/}" ]]; then
  {
    echo "Not continuing to: ${ACTION}"
    echo "Work is still in flight (kind, meeting or queue, state, since UTC):"
    sed '/^[[:space:]]*$/d; s/^/  /' <<<"${found}"
    echo "Wait for it to finish, or run again with FORCE=1: the work is given back to the queue and"
    echo "resumes after the restart, but the step in progress starts over."
  } >&2
  exit 1
fi
