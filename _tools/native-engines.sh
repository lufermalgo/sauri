#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${SAURI_NATIVE_ENGINE_STATE_DIR:-${HOME}/.local/state/sauri/native-engines}"
ASR_PYTHON="${SAURI_ASR_ENGINE_PYTHON:-${SAURI_NATIVE_ENGINE_PYTHON:-${HOME}/.local/share/sauri/native-engines/venv/bin/python}}"
DIAR_PYTHON="${SAURI_DIAR_ENGINE_PYTHON:-${HOME}/.local/share/sauri/native-engines/diar-venv/bin/python}"
ENGINE_TOKEN_FILE="${HOME}/.config/sauri/engine_token"
RECORDING_CAPABILITY_KEY_FILE="${HOME}/.config/sauri/recording_capability_key"

usage() {
  echo "Usage: $0 {start|stop|status} {asr|diar|llm|all}" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
ACTION="$1"
TARGET="$2"
case "$ACTION" in start|stop|status) ;; *) usage ;; esac
case "$TARGET" in asr|diar|llm|all) ;; *) usage ;; esac

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

engine_config() {
  case "$1" in
    asr) ENGINE_PYTHON="$ASR_PYTHON"; ENGINE_LABEL="ASR"; ENGINE_PORT=8001; ENGINE_APP_DIR="$ROOT_DIR/backend/asr-engine" ;;
    diar) ENGINE_PYTHON="$DIAR_PYTHON"; ENGINE_LABEL="diarization"; ENGINE_PORT=8002; ENGINE_APP_DIR="$ROOT_DIR/backend/diar-engine" ;;
    llm)
      ENGINE_LABEL="LLM"; ENGINE_PORT=8003; ENGINE_APP_DIR="$ROOT_DIR/backend/llm-engine"
      ENGINE_PYTHON="${SAURI_NATIVE_LLM_PYTHON:-${SAURI_LLM_INSTALL_DIR:-$HOME/.local/share/sauri/native-engines/llm}/venv/bin/python}"
      ;;
    *) echo "Unknown engine: $1" >&2; exit 2 ;;
  esac
  PID_FILE="$STATE_DIR/$1.pid"
  LOG_FILE="$STATE_DIR/$1.log"
}

process_command() {
  ps -p "$1" -o command= 2>/dev/null || true
}

is_expected_process() {
  local command_line
  command_line="$(process_command "$1")"
  [[ "$command_line" == *uvicorn*"native_main:app"*"--port $ENGINE_PORT"* ]]
}

start_engine() {
  engine_config "$1"
  if [[ -f "$PID_FILE" ]]; then
    local existing_pid
    existing_pid="$(<"$PID_FILE")"
    if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
      if is_expected_process "$existing_pid"; then
        echo "$ENGINE_LABEL already running (PID $existing_pid)"
        return
      fi
      echo "Refusing to start: recorded PID $existing_pid is alive but is not the expected $ENGINE_LABEL server" >&2
      return 1
    fi
    rm -f "$PID_FILE"
  fi

  [[ -s "$ENGINE_TOKEN_FILE" ]] || {
    echo "Native engine token missing: $ENGINE_TOKEN_FILE (run make engines-install)" >&2
    return 1
  }
  [[ -s "$RECORDING_CAPABILITY_KEY_FILE" ]] || {
    echo "Recording capability key missing: $RECORDING_CAPABILITY_KEY_FILE (run make engines-install)" >&2
    return 1
  }
  [[ -x "$ENGINE_PYTHON" ]] || {
    echo "Native engine Python not executable: $ENGINE_PYTHON (run make engines-install)" >&2
    return 1
  }

  PYTHONPATH="$ROOT_DIR/backend/engine-common${PYTHONPATH:+:$PYTHONPATH}" \
    SAURI_RECORDING_CAPABILITY_KEY_FILE="$RECORDING_CAPABILITY_KEY_FILE" \
    nohup "$ENGINE_PYTHON" -m uvicorn native_main:app \
    --app-dir "$ENGINE_APP_DIR" --host 127.0.0.1 --port "$ENGINE_PORT" \
    >>"$LOG_FILE" 2>&1 </dev/null &
  local server_pid=$!
  printf '%s\n' "$server_pid" >"$PID_FILE"
  sleep 1
  if ! kill -0 "$server_pid" 2>/dev/null || ! is_expected_process "$server_pid"; then
    rm -f "$PID_FILE"
    echo "$ENGINE_LABEL server failed to start; inspect $LOG_FILE" >&2
    return 1
  fi
  echo "$ENGINE_LABEL started (PID $server_pid, port $ENGINE_PORT; log $LOG_FILE)"
}

stop_engine() {
  engine_config "$1"
  if [[ ! -f "$PID_FILE" ]]; then
    echo "$ENGINE_LABEL not running (no PID file)"
    return
  fi

  local server_pid
  server_pid="$(<"$PID_FILE")"
  if [[ ! "$server_pid" =~ ^[0-9]+$ ]]; then
    echo "Refusing to stop: invalid PID file $PID_FILE" >&2
    return 1
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "$ENGINE_LABEL not running (stale PID file removed)"
    return
  fi
  if ! is_expected_process "$server_pid"; then
    echo "Refusing to signal PID $server_pid: it is not the expected $ENGINE_LABEL server" >&2
    return 1
  fi

  kill -TERM "$server_pid"
  for _ in {1..10}; do
    if ! kill -0 "$server_pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "$ENGINE_LABEL stopped (PID $server_pid)"
      return
    fi
    if ! is_expected_process "$server_pid"; then
      rm -f "$PID_FILE"
      echo "$ENGINE_LABEL stopped (PID $server_pid)"
      return
    fi
    sleep 1
  done

  if is_expected_process "$server_pid"; then
    kill -KILL "$server_pid"
  fi
  rm -f "$PID_FILE"
  echo "$ENGINE_LABEL stopped (PID $server_pid)"
}

status_engine() {
  engine_config "$1"
  if [[ ! -f "$PID_FILE" ]]; then
    echo "$ENGINE_LABEL stopped"
    return
  fi
  local server_pid
  server_pid="$(<"$PID_FILE")"
  if [[ "$server_pid" =~ ^[0-9]+$ ]] && kill -0 "$server_pid" 2>/dev/null && is_expected_process "$server_pid"; then
    echo "$ENGINE_LABEL running (PID $server_pid, port $ENGINE_PORT)"
    return
  fi
  echo "$ENGINE_LABEL stopped (stale or mismatched PID file: $PID_FILE)"
  return 1
}

engines=(asr diar llm)
if [[ "$TARGET" != all ]]; then engines=("$TARGET"); fi
result=0
for engine in "${engines[@]}"; do
  case "$ACTION" in
    start) start_engine "$engine" || result=1 ;;
    stop) stop_engine "$engine" || result=1 ;;
    status) status_engine "$engine" || result=1 ;;
  esac
done
exit "$result"
