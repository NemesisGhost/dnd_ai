"""dnd_ai.domain.foundry_pairing — the closed Foundry scope vocabulary
(docs/PLAN.md §23.5, Phase 11R workstream D)."""

import pytest

from dnd_ai.domain.foundry_pairing import (
    FOUNDRY_SCOPES,
    InvalidFoundryScopeError,
    validate_foundry_scopes,
)

pytestmark = pytest.mark.unit


def test_validate_foundry_scopes_accepts_every_defined_scope() -> None:
    assert set(validate_foundry_scopes(FOUNDRY_SCOPES)) == FOUNDRY_SCOPES


def test_validate_foundry_scopes_rejects_empty() -> None:
    with pytest.raises(InvalidFoundryScopeError):
        validate_foundry_scopes([])


def test_validate_foundry_scopes_rejects_unknown_code() -> None:
    with pytest.raises(InvalidFoundryScopeError):
        validate_foundry_scopes(["encounter_read", "delete_everything"])


def test_validate_foundry_scopes_returns_a_deterministic_sorted_tuple() -> None:
    a = validate_foundry_scopes(["combat_sync", "encounter_read"])
    b = validate_foundry_scopes(["encounter_read", "combat_sync"])
    assert a == b
    assert a == tuple(sorted(a))


def test_validate_foundry_scopes_deduplicates() -> None:
    result = validate_foundry_scopes(["encounter_read", "encounter_read"])
    assert result == ("encounter_read",)
