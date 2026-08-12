#!/usr/bin/env bash
# Runs the local quality/test verification battery and reports one PASS/FAIL
# line per stage, in the order described in docs/DEVELOPMENT.md §7 ("Code
# quality"), §8 ("Continuous integration"), and §10 ("Definition of done").
# Full command output is captured but only printed for a stage that fails, so
# a clean run stays a handful of lines instead of the combined verbose output
# of running ruff/mypy/pytest/alembic separately.
#
# Usage:
#   scripts/verify.sh --help | -h           # print usage and exit 0
#   scripts/verify.sh quality               # ruff format --check, ruff check, mypy src (no AWS)
#   scripts/verify.sh unit                  # pytest tests/unit (no AWS)
#   scripts/verify.sh database              # pytest tests/database (opens/closes dev ingress)
#   scripts/verify.sh scenario              # pytest tests/scenario (opens/closes dev ingress)
#   scripts/verify.sh full                  # quality + unit + database + scenario + alembic check
#   scripts/verify.sh migration-round-trip --confirm-destructive
#
# `database`/`scenario`/`full`/`migration-round-trip` need DATABASE_URL
# already set per docs/DEVELOPMENT.md §3 — a local or self-hosted (Docker
# Compose) PostgreSQL server by default. AWS RDS is an optional, no longer
# CI-verified target (docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md);
# ingress handling below is a no-op unless DATABASE_URL happens to name an
# AWS RDS endpoint (matched by a *.rds.amazonaws.com host, see
# needs_ingress() below), in which case it opens a short-lived dev
# security-group ingress rule via scripts/aws-db-allow-my-ip.sh and always
# attempts to close it on exit, even on failure. Ingress-revocation failure
# is never swallowed: it fails an otherwise-successful run, and — if a stage
# already failed — is reported alongside that failure without overriding it
# as the primary cause. This is the same guaranteed-teardown discipline
# docs/PHASE5_VERIFICATION.md's exit reviews established for the test-only
# concurrency helper.
#
# `migration-round-trip` runs `alembic downgrade base` then `upgrade head`
# against whatever DATABASE_URL currently points at. That is safe against a
# disposable database (what CI always uses — a fresh containerized
# PostgreSQL service per run) and destructive against anything else. It
# refuses to run without --confirm-destructive.
#
# The ingress open/close script invoked can be overridden via
# VERIFY_SH_INGRESS_SCRIPT (defaults to scripts/aws-db-allow-my-ip.sh) so
# tests/unit/test_verify_sh.py can substitute a stub instead of contacting
# AWS.

set -euo pipefail

usage() {
  echo "Usage: $0 <quality|unit|database|scenario|full|migration-round-trip> [--confirm-destructive]" >&2
  echo "       $0 --help|-h" >&2
}

if [[ $# -ge 1 && ( "$1" == "--help" || "$1" == "-h" ) ]]; then
  usage
  exit 0
fi

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

INGRESS_SCRIPT="${VERIFY_SH_INGRESS_SCRIPT:-scripts/aws-db-allow-my-ip.sh}"

WORKDIR="$(mktemp -d)"
INGRESS_OPENED=0

# Attempts to close an opened ingress rule. Returns 0 if there was nothing to
# close or closing it succeeded; returns 1 if closing a rule we opened
# failed. Never suppresses that failure (no `|| true`): the caller decides
# how to weigh it against any stage failure, per cleanup() below.
close_ingress() {
  if [[ "$INGRESS_OPENED" -eq 1 ]]; then
    local out="$WORKDIR/close_ingress.log"
    if "$INGRESS_SCRIPT" close >"$out" 2>&1; then
      INGRESS_OPENED=0
      return 0
    fi
    echo "FAIL: close dev-database ingress rule" >&2
    cat "$out" >&2
    INGRESS_OPENED=0
    return 1
  fi
  return 0
}

# Runs once, on any exit path (normal completion, a stage's explicit `exit
# 1`, or an unexpected failure under `set -e`). Always attempts ingress
# revocation. A stage failure that triggered the exit remains the primary
# exit code even if revocation also fails; revocation failure alone (after
# an otherwise-successful run) becomes the failure.
cleanup() {
  local trigger_code="$1"
  trap - EXIT

  local ingress_status=0
  close_ingress || ingress_status=1

  rm -rf "$WORKDIR"

  if [[ "$trigger_code" -ne 0 ]]; then
    if [[ "$ingress_status" -ne 0 ]]; then
      echo "Note: ingress revocation also failed above; the stage failure remains primary." >&2
    fi
    exit "$trigger_code"
  fi

  if [[ "$ingress_status" -ne 0 ]]; then
    echo "FAIL: ingress revocation failed after an otherwise-successful run." >&2
    exit 1
  fi

  echo "All requested stages passed."
  exit 0
}
trap 'cleanup "$?"' EXIT

# True only when DATABASE_URL names an AWS RDS endpoint. A local PostgreSQL
# server (the default per docs/DEVELOPMENT.md §3) has no security group to
# open, so open_ingress below must not attempt one.
needs_ingress() {
  [[ "${DATABASE_URL:-}" == *.rds.amazonaws.com* ]]
}

open_ingress() {
  if ! needs_ingress; then
    return 0
  fi
  if [[ "$INGRESS_OPENED" -eq 0 ]]; then
    "$INGRESS_SCRIPT" open >/dev/null
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
