#!/usr/bin/env bash
# Opens or closes a short-lived security-group ingress rule on the dev database
# for the caller's current public IP, per docs/PLAN.md §29.9. This is the
# reachability mechanism for day-to-day migrations and tests/database /
# tests/scenario against the deployed dev RDS instance — not a permanent
# allowlist entry in Terraform.
#
# Usage:
#   scripts/aws-db-allow-my-ip.sh open  [--environment dev] [--profile <profile>]
#   scripts/aws-db-allow-my-ip.sh close [--environment dev] [--profile <profile>]
#
# `open` is idempotent (re-running when already open is a no-op, not an
# error); so is `close`.

set -euo pipefail

usage() {
  echo "Usage: $0 <open|close> [--environment dev] [--profile <profile>]" >&2
}

for tool in aws terraform curl; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Error: $tool is required on PATH" >&2
    exit 2
  fi
done

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

ACTION="$1"
shift
if [[ "$ACTION" != "open" && "$ACTION" != "close" ]]; then
  usage
  exit 2
fi

ENVIRONMENT="dev"
PROFILE_ARG=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --environment)
      [[ $# -ge 2 ]] || { echo "--environment requires a value" >&2; exit 2; }
      ENVIRONMENT="$2"; shift 2;;
    --profile)
      [[ $# -ge 2 ]] || { echo "--profile requires a value" >&2; exit 2; }
      PROFILE_ARG=(--profile "$2"); shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown argument: $1" >&2; usage; exit 2;;
  esac
done

TF_DIR="terraform/environments/$ENVIRONMENT"
SG_ID=$(terraform -chdir="$TF_DIR" output -raw database_security_group_id)
MY_IP=$(curl -s https://checkip.amazonaws.com)
CIDR="${MY_IP}/32"

case "$ACTION" in
  open)
    echo "Authorizing $CIDR on security group $SG_ID (tcp/5432)..." >&2
    if OUTPUT=$(aws ec2 authorize-security-group-ingress "${PROFILE_ARG[@]}" \
        --group-id "$SG_ID" --protocol tcp --port 5432 --cidr "$CIDR" 2>&1); then
      echo "Opened." >&2
    elif grep -q "InvalidPermission.Duplicate" <<<"$OUTPUT"; then
      echo "Already open for $CIDR." >&2
    else
      echo "$OUTPUT" >&2
      exit 1
    fi
    echo "Run '$0 close --environment $ENVIRONMENT' when you're done for this session." >&2
    ;;
  close)
    echo "Revoking $CIDR on security group $SG_ID (tcp/5432)..." >&2
    if OUTPUT=$(aws ec2 revoke-security-group-ingress "${PROFILE_ARG[@]}" \
        --group-id "$SG_ID" --protocol tcp --port 5432 --cidr "$CIDR" 2>&1); then
      echo "Closed." >&2
    elif grep -q "InvalidPermission.NotFound" <<<"$OUTPUT"; then
      echo "Already closed for $CIDR." >&2
    else
      echo "$OUTPUT" >&2
      exit 1
    fi
    ;;
esac
