#!/usr/bin/env bash
# Runs the local quality/test verification battery and reports one PASS/FAIL
# line per stage, in the order described in docs/DEVELOPMENT.md §7 ("Code
# quality"), §8 ("Continuous integration"), and §10 ("Definition of done").
# Full command output is captured but only printed for a stage that fails, so
# a clean run stays a handful of lines instead of the combined verbose output
# of running ruff/mypy/pytest/alembic separately.
#
# Usage:
#   scripts/verify.sh quality               # ruff format --check, ruff check, mypy src (no AWS)
#   scripts/verify.sh unit                  # pytest tests/unit (no AWS)
#   scripts/verify.sh database              # pytest tests/database (opens/closes dev ingress)
#   scripts/verify.sh scenario              # pytest tests/scenario (opens/closes dev ingress)
#   scripts/verify.sh full                  # quality + unit + database + scenario + alembic check
#   scripts/verify.sh migration-round-trip --confirm-destructive
#
# `database`/`scenario`/`full`/`migration-round-trip` need DATABASE_URL
# already set per docs/DEVELOPMENT.md §3 (or DND_AI_USE_LOCAL_POSTGRES=1 as
# the documented fallback); they open a short-lived dev security-group
# ingress rule via scripts/aws-db-allow-my-ip.sh and always close it on exit,
# even on failure — the same guaranteed-teardown discipline
# docs/PHASE5_VERIFICATION.md's exit reviews spent ten passes establishing
# for the test-only concurrency helper.
#
# `migration-round-trip` runs `alembic downgrade base` then `upgrade head`
# against whatever DATABASE_URL currently points at. That is safe against a
# disposable ephemeral database (what CI always uses, via
# scripts/ci_ephemeral_database.py) and destructive against anything else.
# It refuses to run without --confirm-destructive.

set -euo pipefail

usage() {
  echo "Usage: $0 <quality|unit|database|scenario|full|migration-round-trip> [--confirm-destructive]" >&2
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

MODE="$1"
shift

CONFIRM_DESTRUCTIVE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --confirm-destructive)
      CONFIRM_DESTRUCTIVE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

case "$MODE" in
  quality|unit|database|scenario|full|migration-round-trip) ;;
  *)
    usage
    exit 2
    ;;
esac

WORKDIR="$(mktemp -d)"
INGRESS_OPENED=0

close_ingress() {
  if [[ "$INGRESS_OPENED" -eq 1 ]]; then
    scripts/aws-db-allow-my-ip.sh close >/dev/null 2>&1 || true
    INGRESS_OPENED=0
  fi
}
cleanup() {
  close_ingress
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

open_ingress() {
  if [[ "$INGRESS_OPENED" -eq 0 ]]; then
    scripts/aws-db-allow-my-ip.sh open >/dev/null
    INGRESS_OPENED=1
  fi
}

run_stage() {
  local label="$1"
  shift
  local slug
  slug="$(echo "$label" | tr -cs 'a-zA-Z0-9' '_')"
  local out="$WORKDIR/${slug}.log"
  local start end elapsed
  start=$(date +%s)
  if "$@" >"$out" 2>&1; then
    end=$(date +%s)
    elapsed=$((end - start))
    echo "PASS: $label (${elapsed}s)"
  else
    end=$(date +%s)
    elapsed=$((end - start))
    echo "FAIL: $label (${elapsed}s)"
    echo "----- output: $label -----"
    cat "$out"
    echo "---------------------------"
    exit 1
  fi
}

run_quality() {
  run_stage "ruff format --check" uv run ruff format --check .
  run_stage "ruff check" uv run ruff check .
  run_stage "mypy src" uv run mypy src
}

run_unit() {
  run_stage "pytest tests/unit" uv run pytest tests/unit -q
}

run_database() {
  open_ingress
  run_stage "pytest tests/database" uv run pytest tests/database -q
}

run_scenario() {
  if [[ -d tests/scenario ]]; then
    open_ingress
    run_stage "pytest tests/scenario" uv run pytest tests/scenario -q
  fi
}

case "$MODE" in
  quality)
    run_quality
    ;;
  unit)
    run_unit
    ;;
  database)
    run_database
    ;;
  scenario)
    run_scenario
    ;;
  full)
    run_quality
    run_unit
    run_database
    run_scenario
    run_stage "alembic check (schema diff)" uv run alembic -c database/alembic.ini check
    ;;
  migration-round-trip)
    if [[ "$CONFIRM_DESTRUCTIVE" -ne 1 ]]; then
      echo "Refusing: this runs 'alembic downgrade base' against whatever DATABASE_URL" >&2
      echo "currently points at, which drops all data reachable from that connection." >&2
      echo "Only run this against a disposable database. Re-run with --confirm-destructive to proceed." >&2
      exit 2
    fi
    open_ingress
    run_stage "alembic downgrade base" uv run alembic -c database/alembic.ini downgrade base
    run_stage "alembic upgrade head" uv run alembic -c database/alembic.ini upgrade head
    ;;
esac

echo "All requested stages passed."
