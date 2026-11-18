#!/usr/bin/env bash
# Poller burro do modo chat aberto. Não lê o corpo da request, não chama LLM, não executa o job.
# Lança keep_awake num processo à parte para impedir sleep/display sleep e lock automático por inatividade no macOS enquanto este monitor corre.
set -euo pipefail

PROJECT="${IA_ORCHESTRATOR_PROJECT:?defina IA_ORCHESTRATOR_PROJECT}"
ROLE="${IA_ORCHESTRATOR_ROLE:-executor}"
HOME_DIR="${IA_ORCHESTRATOR_HOME:-}"
INTERVAL="${IA_ORCHESTRATOR_POLL_SECONDS:-10}"
PID_FILE="${IA_ORCHESTRATOR_PID_FILE:-}"
KEEP_AWAKE_PID=""

HOME_ARGS=()
if [[ -n "$HOME_DIR" ]]; then
  HOME_ARGS=(--home "$HOME_DIR")
fi

load_host_env() {
  local env_file="${HOME_DIR:-$HOME/.ia_orchestrator}/.env"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

load_host_env

stop_keep_awake() {
  if [[ -n "${KEEP_AWAKE_PID}" ]] && kill -0 "$KEEP_AWAKE_PID" 2>/dev/null; then
    kill "$KEEP_AWAKE_PID" 2>/dev/null || true
    wait "$KEEP_AWAKE_PID" 2>/dev/null || true
  fi
}
trap stop_keep_awake EXIT

start_keep_awake() {
  local py
  py="$(cd "$(dirname "${BASH_SOURCE[0]}")/../src/ia_orchestrator" && pwd)/keep_awake.py"
  if [[ ! -f "$py" ]]; then
    echo "keep_awake: $py não encontrado; monitor segue sem proteção contra sleep/idle-lock." >&2
    return 0
  fi
  python3 "$py" &
  KEEP_AWAKE_PID=$!
}

if [[ -n "$PID_FILE" ]]; then
  mkdir -p "$(dirname "$PID_FILE")"
  echo $$ > "$PID_FILE"
fi

start_keep_awake

ia-orchestrator "${HOME_ARGS[@]}" loop tick --project "$PROJECT" --role "$ROLE" --claim --reset-wake || true

while true; do
  sleep "$INTERVAL"
  ia-orchestrator "${HOME_ARGS[@]}" loop tick --project "$PROJECT" --role "$ROLE" --claim || true
done
