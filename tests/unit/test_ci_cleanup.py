"""ci_cleanup.run_cleanup() — the always-attempt-both, fail-if-either-failed
combinator behind CI's cleanup step (PHASE4_REMAINING_ISSUES.md §7,
post-closeout §5).

Exercises every failure combination against fake operations rather than the
real database drop / AWS ingress revoke, so this is safe to run anywhere
(including outside CI) without ever leaking a real ephemeral database or
security-group rule just to prove the failure path works.
"""

import pytest
from ci_cleanup import run_cleanup

pytestmark = pytest.mark.unit


class _Boom(Exception):
    pass


def _ok() -> None:
    return None


def _fail() -> None:
    raise _Boom("simulated failure")


def test_both_succeeding_reports_success() -> None:
    assert run_cleanup(_ok, _ok) is True


def test_database_drop_failure_still_attempts_ingress_revoke_and_reports_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    revoked = []

    def revoke() -> None:
        revoked.append(True)

    assert run_cleanup(_fail, revoke) is False
    assert revoked == [True], "ingress revoke must still run after a database-drop failure"
    assert "::error::Failed to drop the ephemeral database" in capsys.readouterr().err


def test_ingress_revoke_failure_still_attempted_after_successful_drop_and_reports_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    dropped = []

    def drop() -> None:
        dropped.append(True)

    assert run_cleanup(drop, _fail) is False
    assert dropped == [True]
    assert "::error::Failed to revoke security-group ingress" in capsys.readouterr().err


def test_both_failing_attempts_both_and_reports_failure_identifying_both(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cleanup(_fail, _fail) is False
    err = capsys.readouterr().err
    assert "::error::Failed to drop the ephemeral database" in err
    assert "::error::Failed to revoke security-group ingress" in err
