"""Always-attempt-both, fail-if-either-failed cleanup for the CI aws-verification
job (PHASE4_REMAINING_ISSUES.md §7, post-closeout §5).

Used by .github/workflows/ci.yml's "Clean up ephemeral database and revoke
access" step in place of two independent `... || true` shell commands: that
form silently swallowed either failure, which could leave an ephemeral
database or an open security-group ingress rule behind on AWS `dev` while the
job stayed green. `run_cleanup()` is the reusable unit under test — it always
attempts both operations regardless of the first's outcome, prints a
`::error::` annotation identifying each one that failed, and reports overall
success only if both succeeded. `main()` wires it to the real operations
(dropping the ephemeral database via `ci_ephemeral_database.drop_ephemeral_database`,
revoking the security-group ingress rule via the AWS CLI) and is what CI
actually runs; see tests/unit/test_ci_cleanup.py for `run_cleanup()` exercised
against fake operations that simulate each failure combination without
touching AWS.

Usage: uv run python scripts/ci_cleanup.py

Reads DEV_DB_ADMIN_URL, DND_AI_CI_DB_NAME (both consumed by
ci_ephemeral_database.drop_ephemeral_database), and RUNNER_CIDR /
DEV_DB_SECURITY_GROUP_ID (for the ingress revoke) from the environment, same
as the workflow step it replaces.
"""

import os
import subprocess
import sys
from collections.abc import Callable

from ci_ephemeral_database import drop_ephemeral_database


def run_cleanup(drop_database: Callable[[], None], revoke_ingress: Callable[[], None]) -> bool:
    """Runs both cleanup operations unconditionally — the second always runs
    even if the first raises — and returns True only if neither raised.
    Prints a `::error::` annotation (the GitHub Actions log-annotation
    format) identifying each operation that failed, so a red step in the
    Actions UI still says which resource may have leaked."""
    database_ok = True
    try:
        drop_database()
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any failure here must not skip the ingress revoke below
        database_ok = False
        print(f"::error::Failed to drop the ephemeral database: {exc}", file=sys.stderr)

    ingress_ok = True
    try:
        revoke_ingress()
    except Exception as exc:  # noqa: BLE001 - see above
        ingress_ok = False
        print(f"::error::Failed to revoke security-group ingress: {exc}", file=sys.stderr)

    return database_ok and ingress_ok


def _revoke_real_ingress() -> None:
    runner_cidr = os.environ.get("RUNNER_CIDR")
    if not runner_cidr:
        # Nothing was opened (an earlier step failed before recording it) —
        # matches drop_ephemeral_database's own no-op-when-unset contract.
        return

    subprocess.run(
        [
            "aws",
            "ec2",
            "revoke-security-group-ingress",
            "--group-id",
            os.environ["DEV_DB_SECURITY_GROUP_ID"],
            "--protocol",
            "tcp",
            "--port",
            "5432",
            "--cidr",
            runner_cidr,
        ],
        check=True,
    )


def main() -> None:
    success = run_cleanup(drop_ephemeral_database, _revoke_real_ingress)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
