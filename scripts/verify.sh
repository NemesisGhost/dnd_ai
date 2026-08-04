#!/usr/bin/env bash
# Local "definition of done" verification loop — docs/DEVELOPMENT.md §10 and
# the checks in .github/workflows/ci.yml that are safe to run against the
# shared, persistent AWS dev database.
#
# Deliberately does NOT run the CI job's `alembic downgrade base` round trip:
# that step runs against an ephemeral, empty per-run database created via
# scripts/ci_ephemeral_database.py (which itself requires DEV_DB_ADMIN_URL
# and GITHUB_ENV, and is not meant for interactive use — see that script's
# docstring). Downgrading the shared dev database to base would drop every
# schema and every other developer/agent's data on it. Verify a downgrade
# per docs/DEVELOPMENT.md §4 ("downgrade -1") manually, alone on dev, only
# right after writing the migration you're about to roll back.
#
# Usage:
#   scripts/verify.sh [--skip-db] [--environment dev] [--profile <profile>]
#
#   --skip-db   Lint/type-check only — no AWS ingress, no alembic/pytest
#               against the database. Fast loop while iterating on
#               non-schema code.
#
# Exit status is 0 only if every step that ran passed. mypy failing solely
# because this environment's Application Control policy blocks its DLL is
# reported as SKIPPED, not FAILED — it is a sandbox limitation, not a
# verification result — but every other mypy failure still fails the run.

set -uo pipefail
cd "$(dirname "$0")/.."

SKIP_DB=0
ENVIRONMENT="dev"
PROFILE_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-db) SKIP_DB=1; shift;;
    --environment) ENVIRONMENT="$2"; shift 2;;
    --profile) PROFILE_ARGS=(--profile "$2"); shift 2;;
    -h|--help)
      echo "Usage: $0 [--skip-db] [--environment dev] [--profile <profile>]" >&2
      exit 0;;
    *) echo "Unknown argument: $1" >&2; exit 2;;
  esac
done

STEP_NAMES=()
STEP_RESULTS=()
INGRESS_OPEN=0

close_ingress() {
  if [[ "$INGRESS_OPEN" -eq 1 ]]; then
    scripts/aws-db-allow-my-ip.sh close --environment "$ENVIRONMENT" "${PROFILE_ARGS[@]}" >/dev/null 2>&1
    INGRESS_OPEN=0
  fi
}
trap close_ingress EXIT

run_step() {
  local name="$1"; shift
  local logfile start end elapsed rc
  logfile=$(mktemp)
  start=$(date +%s)
  if "$@" >"$logfile" 2>&1; then
    rc=0
  else
    rc=$?
  fi
  end=$(date +%s); elapsed=$((end - start))
  if [[ $rc -eq 0 ]]; then
    echo "[PASS] $name (${elapsed}s)"
    STEP_NAMES+=("$name"); STEP_RESULTS+=("PASS")
  else
    echo "[FAIL] $name (${elapsed}s)"
    echo "  ----- last 40 lines -----"
    tail -n 40 "$logfile" | sed 's/^/  /'
    echo "  --------------------------"
    STEP_NAMES+=("$name"); STEP_RESULTS+=("FAIL")
  fi
  rm -f "$logfile"
}

run_mypy_step() {
  local name="mypy src"
  local logfile start end elapsed rc
  logfile=$(mktemp)
  start=$(date +%s)
  if uv run mypy src >"$logfile" 2>&1; then
    rc=0
  else
    rc=$?
  fi
  end=$(date +%s); elapsed=$((end - start))
  if [[ $rc -eq 0 ]]; then
    echo "[PASS] $name (${elapsed}s)"
    STEP_NAMES+=("$name"); STEP_RESULTS+=("PASS")
  elif grep -qE "DLL load failed|Application Control policy" "$logfile"; then
    echo "[SKIP] $name (${elapsed}s) — blocked by this machine's Application Control policy, not a type-check result"
    STEP_NAMES+=("$name"); STEP_RESULTS+=("SKIP")
  else
    echo "[FAIL] $name (${elapsed}s)"
    echo "  ----- last 40 lines -----"
    tail -n 40 "$logfile" | sed 's/^/  /'
    echo "  --------------------------"
    STEP_NAMES+=("$name"); STEP_RESULTS+=("FAIL")
  fi
  rm -f "$logfile"
}

echo "== Lint and type-check =="
run_step "ruff format --check" uv run ruff format --check .
run_step "ruff check" uv run ruff check .
run_mypy_step

if [[ "$SKIP_DB" -eq 1 ]]; then
  echo
  echo "--skip-db: stopping before AWS/database steps."
else
  echo
  echo "== AWS dev database =="
  if scripts/aws-db-allow-my-ip.sh open --environment "$ENVIRONMENT" "${PROFILE_ARGS[@]}" >/dev/null 2>&1; then
    INGRESS_OPEN=1
  else
    echo "[FAIL] open AWS dev ingress"
    STEP_NAMES+=("open AWS dev ingress"); STEP_RESULTS+=("FAIL")
  fi

  if [[ "$INGRESS_OPEN" -eq 1 ]]; then
    run_step "alembic upgrade head" uv run alembic -c database/alembic.ini upgrade head
    run_step "alembic check (no schema diff)" uv run alembic -c database/alembic.ini check
    run_step "seed idempotency" uv run pytest tests/database/test_seed_idempotency.py -q
    run_step "full pytest suite" uv run pytest -q
  fi
fi

echo
echo "== Summary =="
FAILED=0
for i in "${!STEP_NAMES[@]}"; do
  echo "  [${STEP_RESULTS[$i]}] ${STEP_NAMES[$i]}"
  [[ "${STEP_RESULTS[$i]}" == "FAIL" ]] && FAILED=1
done

if [[ "$FAILED" -eq 1 ]]; then
  echo
  echo "FAILED — see step output above."
  exit 1
fi
echo
echo "All steps passed."
