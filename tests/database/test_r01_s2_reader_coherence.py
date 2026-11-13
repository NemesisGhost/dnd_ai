# ruff: noqa: F811 - the imported fixture is used by parameter name
"""R01 plan 12.3 item 4: the coherence probe detects the old multi-statement reader's mixed observation.

`test_r01_s2_profile_routes.py::test_a_group_deny_and_the_actors_removal_from_the_group_are_seen_together`
shows the production reader is coherent. That alone would pass for any reader, so this file is its control:
a faithful copy of the pre-S1 reader (`tests/access_reference.py`, whose five SQL statements equal the
ones at 825f0ce apart from the documented `now()` rewrite) is made to observe a state no committed
state ever had, deterministically, and the production single-statement reader is shown not to.

**What the old reader reads in separate statements.** The role capabilities (statement 3), the character
relationships (4) and the resource grants (5) are three statements, each with its own READ COMMITTED
snapshot. The group-membership test is a subquery INSIDE statement 5, so a group deny and the actor's
removal from that group are read atomically even by the old reader (`test_..._are_one_statement`).
The mixed observation therefore uses the pair the old reader really splits: roles against grants.

**The interleaving.** The actor, who has no `canon.edit` role, holds `canon.edit` on one character
through a group-keyed `allow` grant (they are a member of the group). The operation asks
`has_capability("canon.edit", entity_id=character)`.

- state A (before): group `allow` live, no role: ALLOWED.
- transaction T (one commit): the group `allow` is revoked AND the actor is given the `gm` role
  (`canon.edit`).
- state B (after): role live, no grant: ALLOWED.
- old reader, gated between its role statement (3) and its grants statement (5): the role statement ran
  in A and the grants statement runs in B. It sees no role and no grant: REFUSED. No committed state
  ever refused the actor.
- production reader, with T committed immediately before its one statement: sees B: ALLOWED.

The gate is a synchronous `before_cursor_execute` hook on the reader's own connection that commits T on a
second connection and then lets the statement run: no thread, no sleep.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, event, text

from dnd_ai.domain.access import AccessContext, resolve_access_context
from tests.access_reference import reference_resolve_access_context
from tests.database.test_campaign_owner_gate import Gate, g  # noqa: F401 - fixture used by name
from tests.factories import (
    lookup_id,
    make_access_group,
    make_access_group_membership,
    make_character,
    make_membership_role,
    make_resource_grant,
)

pytestmark = pytest.mark.database

CANON_EDIT = "canon.edit"
ROLES = "FROM security.membership_roles mr"
GRANTS = "FROM security.resource_grants rg"
PRODUCTION = "WITH clock AS MATERIALIZED"


def _allowed(access: AccessContext | None, character: uuid.UUID) -> bool:
    return access is not None and access.has_capability(CANON_EDIT, entity_id=character)


def _gated(
    engine: Engine,
    read: Callable[[Connection], AccessContext | None],
    *,
    before: str,
    during: Callable[[], None],
) -> tuple[AccessContext | None, list[str]]:
    """Runs `read` on its own connection. Immediately before the first statement containing `before`
    the hook runs `during` (a commit on another connection), then lets that statement execute. Returns
    the result and every statement the reader issued, in order."""
    seen: list[str] = []
    fired: list[bool] = []

    def hook(_conn: Any, _cursor: Any, statement: Any, *_: Any) -> None:
        flat = " ".join(str(statement).split())
        seen.append(flat)
        if not fired and before in flat:
            fired.append(True)
            during()

    with engine.connect() as connection:
        event.listen(connection, "before_cursor_execute", hook)
        try:
            result = read(connection)
        finally:
            event.remove(connection, "before_cursor_execute", hook)
    assert fired == [True], "the gate was never reached"
    return result, seen


class World:
    def __init__(self, engine: Engine, g: Gate) -> None:
        self.engine = engine
        self.g = g
        self.user = g.player_user_id
        self.membership = g.player
        with engine.begin() as connection:
            self.character = make_character(connection, g.world_id, name="Coherence Subject")
            self.group = make_access_group(connection, g.campaign_id, name="Coherence Group")
            self.group_membership = make_access_group_membership(
                connection, self.group, self.membership
            )
            self.capability = lookup_id(
                connection, "security", "capabilities", "capability_id", CANON_EDIT
            )
            self.allow = make_resource_grant(
                connection,
                g.campaign_id,
                self.capability,
                timeline_id=g.timeline_id,
                grantee_access_group_id=self.group,
                entity_id=self.character,
                effect="allow",
            )

    def old(self, connection: Connection) -> AccessContext | None:
        return reference_resolve_access_context(
            connection, user_id=self.user, campaign_id=self.g.campaign_id
        )

    def new(self, connection: Connection) -> AccessContext | None:
        return resolve_access_context(connection, user_id=self.user, campaign_id=self.g.campaign_id)

    def swap_grant_for_role(self) -> None:
        """T: one transaction revokes the group `allow` and assigns the `gm` role."""
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE security.resource_grants SET revoked_at = now() WHERE resource_grant_id = :g"
                ),
                {"g": self.allow},
            )
            make_membership_role(connection, self.membership, self.g.gm_role_id)

    def undo(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE security.resource_grants SET revoked_at = NULL WHERE resource_grant_id = :g"
                ),
                {"g": self.allow},
            )
            connection.execute(
                text(
                    "UPDATE security.membership_roles SET revoked_at = now() "
                    "WHERE campaign_membership_id = :m AND role_id = :r AND revoked_at IS NULL"
                ),
                {"m": self.membership, "r": self.g.gm_role_id},
            )


def test_the_control_old_reader_refuses_a_state_no_commit_ever_had_and_production_allows(
    postgres_engine: Engine, g: Gate
) -> None:
    w = World(postgres_engine, g)

    # The coherent states permit the operation, for both readers: the refusal below is not policy.
    with postgres_engine.connect() as connection:
        before_old, before_new = w.old(connection), w.new(connection)
    assert _allowed(before_old, w.character) and _allowed(before_new, w.character)
    assert CANON_EDIT not in before_old.role_capabilities  # type: ignore[union-attr]  # via the grant
    w.swap_grant_for_role()
    with postgres_engine.connect() as connection:
        after_old, after_new = w.old(connection), w.new(connection)
    assert _allowed(after_old, w.character) and _allowed(after_new, w.character)
    assert CANON_EDIT in after_old.role_capabilities  # type: ignore[union-attr]  # via the role
    w.undo()  # back to state A for the interleaved runs

    # OLD reader: T commits between its role statement and its grants statement.
    mixed, statements = _gated(postgres_engine, w.old, before=GRANTS, during=w.swap_grant_for_role)
    role_statement = next(i for i, s in enumerate(statements) if ROLES in s)
    grants_statement = next(i for i, s in enumerate(statements) if GRANTS in s)
    assert role_statement < grants_statement, statements
    assert mixed is not None
    # It observed the mixed state: the role statement saw A (no role), the grants statement saw B (no
    # grant). That combination was never committed.
    assert CANON_EDIT not in mixed.role_capabilities
    assert mixed.grant_effects.get(("entity_id", w.character), {}).get(CANON_EDIT) is None
    assert _allowed(mixed, w.character) is False, "the old reader should have refused"

    # PRODUCTION reader: T commits immediately before its one statement; it reads state B whole.
    w.undo()
    coherent, issued = _gated(
        postgres_engine, w.new, before=PRODUCTION, during=w.swap_grant_for_role
    )
    assert sum(1 for s in issued if PRODUCTION in s) == 1
    assert coherent is not None
    assert CANON_EDIT in coherent.role_capabilities
    assert _allowed(coherent, w.character) is True


def test_the_group_deny_and_the_actors_removal_are_one_statement_even_in_the_old_reader(
    postgres_engine: Engine, g: Gate
) -> None:
    """Why the control above does not use the group deny and the removal (the pair named in plan 12.3
    item 4): the old reader reads the group memberships in a subquery of its grants statement, so the
    pair is read atomically by BOTH readers. Gated between the old reader's role and grants statements,
    the transaction that adds the group deny and removes the actor from the group is seen whole."""
    w = World(postgres_engine, g)
    with postgres_engine.begin() as connection:  # actor holds the role; the group carries no allow
        make_membership_role(connection, w.membership, g.gm_role_id)
        connection.execute(
            text(
                "UPDATE security.resource_grants SET revoked_at = now() WHERE resource_grant_id = :g"
            ),
            {"g": w.allow},
        )

    def deny_and_remove() -> None:
        with postgres_engine.begin() as connection:
            make_resource_grant(
                connection,
                g.campaign_id,
                w.capability,
                timeline_id=g.timeline_id,
                grantee_access_group_id=w.group,
                entity_id=w.character,
                effect="deny",
            )
            connection.execute(
                text(
                    "UPDATE security.access_group_memberships SET removed_at = now() "
                    "WHERE access_group_membership_id = :m"
                ),
                {"m": w.group_membership},
            )

    with postgres_engine.connect() as connection:
        assert _allowed(
            w.old(connection), w.character
        )  # state A: role, member of a group with no deny
    result, statements = _gated(postgres_engine, w.old, before=GRANTS, during=deny_and_remove)
    # The group membership a deny is judged against is read inside the grants statement itself (the
    # revelations statement also mentions group memberships, for revelation audiences, and carries no
    # grant): exactly one statement reads both the grants and the memberships.
    both = [s for s in statements if GRANTS in s and "security.access_group_memberships" in s]
    assert len(both) == 1
    assert result is not None
    # Both halves were seen together: the deny exists in the grants map, but the actor is not in the
    # group any more, so it does not reach them: allowed, exactly as in the committed state B.
    assert _allowed(result, w.character) is True
