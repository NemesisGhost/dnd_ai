"""Foundry pairing scope vocabulary (docs/PLAN.md §23.5, Phase 11R
workstream D).

`FOUNDRY_SCOPES` is the single Python-side definition of the closed,
narrow initial scope set §23.5 describes ("Initial Foundry scopes remain
closed and narrow: encounter/current-state reads, synchronization status
reads, combat synchronization, character-state synchronization, and only
the location/state reads required by the module"). `database/migrations/
versions/100_foundry_pairing.py`'s `ck_foundry_connections_granted_scopes_
closed`/`ck_foundry_pairing_codes_requested_scopes_closed` CHECK
constraints mirror this exact set in SQL — the two must be kept in sync by
hand (the same relationship every other Python-closed-set-mirrored-by-a-
SQL-CHECK in this codebase already has, e.g. `ai.proposed_changes.
proposal_kind`); a scope added to one without the other either can never be
granted (Python rejects it first) or is silently unenforceable at the
database layer (SQL would accept it while Python never offers it) —
`tests/database/test_foundry_pairing_commands.py` proves every code this
module allows an actual `INSERT`/`UPDATE` to succeed for, closing that gap.
"""

FOUNDRY_SCOPES = frozenset(
    {
        "encounter_read",
        "sync_status_read",
        "combat_sync",
        "character_state_sync",
        "location_read",
    }
)


class InvalidFoundryScopeError(ValueError):
    """Raised when a caller-supplied scope list names something outside
    `FOUNDRY_SCOPES` or is empty — checked in Python before any database
    round-trip, rather than left to surface as an opaque CHECK-constraint
    violation (`ck_foundry_connections_granted_scopes_closed`/`ck_foundry_
    pairing_codes_requested_scopes_closed`)."""


def validate_foundry_scopes(scopes: frozenset[str] | set[str] | list[str]) -> tuple[str, ...]:
    """Rejects an empty scope list or one naming anything outside
    `FOUNDRY_SCOPES`, and returns a deterministically ordered tuple
    (sorted) — so two calls requesting the same *set* of scopes in a
    different order still produce identical, comparable rows rather than
    two array values PostgreSQL's `<@`/`=` would treat as unequal only by
    ordering accident."""
    scope_set = frozenset(scopes)
    if not scope_set:
        raise InvalidFoundryScopeError("at least one scope must be requested")
    unknown = scope_set - FOUNDRY_SCOPES
    if unknown:
        raise InvalidFoundryScopeError(
            f"unknown Foundry scope(s): {sorted(unknown)!r} — allowed: {sorted(FOUNDRY_SCOPES)!r}"
        )
    return tuple(sorted(scope_set))
