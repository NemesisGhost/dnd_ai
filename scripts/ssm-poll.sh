#!/usr/bin/env bash
# Portable script to poll an AWS SSM Command until completion
# Usage: ssm-poll.sh <CommandId> [--region <region>] [--profile <profile>] [--timeout <seconds>]

set -euo pipefail

usage() {
  echo "Usage: $0 <CommandId> [--region <region>] [--profile <profile>] [--timeout <seconds>]" >&2
}

if ! command -v aws >/dev/null 2>&1; then
  echo "Error: aws CLI is required on PATH" >&2
  exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required on PATH" >&2
  exit 2
fi

CID=""
REGION_ARG=""
PROFILE_ARG=""
TIMEOUT_SEC=$((30*60))

# Parse args
if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

CID="$1"; shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)
      [[ $# -ge 2 ]] || { echo "--region requires a value" >&2; exit 2; }
      REGION_ARG=(--region "$2"); shift 2;;
    --profile)
      [[ $# -ge 2 ]] || { echo "--profile requires a value" >&2; exit 2; }
      PROFILE_ARG=(--profile "$2"); shift 2;;
    --timeout)
      [[ $# -ge 2 ]] || { echo "--timeout requires a value (seconds)" >&2; exit 2; }
      TIMEOUT_SEC="$2"; shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown argument: $1" >&2; usage; exit 2;;
  esac
done

ts() { date +"%Y-%m-%d %H:%M:%S"; }

echo "[$(ts)] Polling SSM CommandId: $CID (timeout: ${TIMEOUT_SEC}s)" >&2

# Helper: invoke aws with transient error retries
aws_poll_once() {
  local tries=0 max_tries=5 sleep_sec=2
  local out rc
  while :; do
    if out=$(aws ssm list-command-invocations "${REGION_ARG[@]}" "${PROFILE_ARG[@]}" \
              --command-id "$CID" --details --output json 2>&1); then
      printf '%s' "$out"
      return 0
    fi
    rc=$?
    tries=$((tries+1))
    # Retry on throttling/timeouts
    if grep -Eqi '(Throttl|Rate.*exceed|timeout|temporarily unavailable)' <<<"$out"; then
      if (( tries >= max_tries )); then
        echo "[$(ts)] AWS API still failing after $tries tries: $out" >&2
        return $rc
      fi
      sleep "$sleep_sec"; sleep_sec=$(( sleep_sec*2 )); (( sleep_sec>10 )) && sleep_sec=10
      continue
    fi
    # Non-transient error
    echo "[$(ts)] AWS API error: $out" >&2
    return $rc
  done
}

START=$(date +%s)
BACKOFF=10
MAX_BACKOFF=60
LAST_STATUS=""

while :; do
  NOW=$(date +%s)
  ELAPSED=$((NOW-START))
  if (( ELAPSED >= TIMEOUT_SEC )); then
    echo "[$(ts)] Timeout (${TIMEOUT_SEC}s) while waiting for command $CID" >&2
    exit 1
  fi

  STATUS_JSON=$(aws_poll_once) || { sleep "$BACKOFF"; BACKOFF=$(( BACKOFF<MAX_BACKOFF ? BACKOFF*2 : MAX_BACKOFF )); continue; }

  STATUS=$(jq -r '.CommandInvocations[0].Status // empty' <<<"$STATUS_JSON")
  if [[ -z "$STATUS" ]]; then
    STATUS="Pending"
  fi

  if [[ "$STATUS" != "$LAST_STATUS" ]]; then
    echo "[$(ts)] Status: $STATUS" >&2
    LAST_STATUS="$STATUS"
  fi

  case "$STATUS" in
    Success)
      echo "[$(ts)] SSM command $CID completed successfully" >&2
      exit 0
      ;;
    Cancelled|TimedOut|Failed|Cancelling)
      echo "[$(ts)] SSM command $CID ended with status: $STATUS" >&2
      # Print last plugin output if present
      jq -r '.CommandInvocations[0].CommandPlugins[-1].Output // empty' <<<"$STATUS_JSON" || true
      exit 1
      ;;
    *)
      sleep "$BACKOFF"; BACKOFF=$(( BACKOFF<MAX_BACKOFF ? BACKOFF*2 : MAX_BACKOFF ))
      ;;
  esac
done
