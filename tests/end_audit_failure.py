"""Test support: make the end-membership route fail right where its audit row is written.

Several transaction tests need "a handler that fails after the reservation, the mutation and before the response". Until
S5-E3 they patched `dnd_ai.api.memberships.record_change_log`; the end route is a pre-write plan now and writes its audit
row through the declared step `audit_membership_ended`, so the failure is injected at that step (after `plan.finalize`,
after every closure, before the receipt)."""

from collections.abc import Callable
from typing import Any

import pytest

from dnd_ai.domain.authorization import AuthorizationPlan

END_AUDIT_STEP = "audit_membership_ended"


def fail_end_audit(monkeypatch: pytest.MonkeyPatch, behaviour: Callable[[], Any]) -> None:
    """Calls `behaviour()` instead of writing the end route's audit row. It raises to fail the request, or returns to let
    the genuine write follow."""
    original = AuthorizationPlan.execute

    def execute(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> Any:
        if step.name == END_AUDIT_STEP:
            behaviour()
        return original(self, connection, step, params)

    monkeypatch.setattr(AuthorizationPlan, "execute", execute)
