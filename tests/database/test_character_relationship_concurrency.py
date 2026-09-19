"""Real PostgreSQL concurrency regression coverage for `dnd_ai.commands.
access_grants.grant_character_relationship`/`change_character_relationship`/
`revoke_character_relationship` (character-relationship-management
checkpoint).

Mirrors `tests/database/test_membership_role_concurrency.py`/`.
test_membership_lifecycle_concurrency.py`'s own idioms exactly — genuine
row-lock blocking proven with `SET LOCAL lock_timeout` on a second,
independent connection, never a single shared connection or a mocked
delay:

1. **Two concurrent grants of the identical relationship** (same
   membership/character/type): resolved by `ux_membership_character_
   relationships_active_type`'s own unique-index insertion lock, exactly
   like `test_two_concurrent_adds_of_the_same_account_cannot_both_succeed`
   for `add_campaign_member` — the second `INSERT` blocks on the first's
   still-uncommitted row until it resolves, then either raises a unique
   violation (committed) or proceeds (rolled back).

2. **Eligibility-check/write races for `grant_character_relationship`**:
   its own row locks (target membership, owning user, target character,
   candidate relationship type — in that order) must make a concurrent
   conflicting write block, proven the identical way `test_a_role_
   deactivation_cannot_race_an_add_assigning_it`/`.test_an_account_
   disablement_cannot_race_an_add_targeting_it` prove theirs.

3. **Eligibility-check/write races for `change_character_relationship`**:
   its own row locks (target relationship + owning membership, then the
   candidate new relationship type) must make a concurrent conflicting
   write block, mirroring `change_membership_role`'s own coverage in
   `test_membership_role_concurrency.py`.

4. **Same-row races**: change-vs-revoke, revoke-vs-revoke, and change-vs-
   change of the identical relationship row must serialize on `FOR UPDATE
   OF mcr`, never interleave, and never raise for the loser's own
   documented no-op/already-changed outcome — mirroring `test_two_
   concurrent_revokes_of_the_identical_row_serialize`/`test_a_change_and_a_
   revoke_targeting_the_identical_row_serialize` exactly, all proven with
   the same two-connection `lock_timeout` blocking idiom as sections 1-3
   above (not `_run_with_precommit_barrier`: that helper exists
   specifically to race two *different* rows against a shared, deferred,
   commit-time invariant — see `test_membership_role_concurrency.py`'s own
   docstring, "naming the same... row for both workers would let... `FOR
   UPDATE` on that shared row silently serialize the two workers". A
   same-row test wants exactly that serialization as its own proof, so the
   barrier would only risk a spurious timeout: the second worker's own
   `change_character_relationship` blocks *acquiring* its row lock, before
   it can ever reach the barrier that the first worker is already waiting
   at).

5. **Relationship mutation racing campaign deactivation** (checkpoint-4
   correction): `grant_character_relationship`/`change_character_
   relationship` now lock `campaign.campaigns FOR UPDATE` and require it to
   currently be `active` — the same eligibility bar `add_campaign_member`
   already applies when creating a membership, closing the gap where a
   campaign could be deactivated after `require_campaign_capability` had
   already authorized the request but before either mutation committed.
   Proven the identical blocking way `test_a_campaign_deactivation_cannot_
   race_an_add_targeting_it` (`test_membership_lifecycle_concurrency.py`)
   already proves it for `add_campaign_member`. Locked *after* the
   function's own primary target row (membership, or the `mcr`/`cm` pair)
   rather than before it — see `dnd_ai.commands.access_grants`'s own module
   docstring, "Checkpoint-4 correction," for why: `add_campaign_member` can
   safely lock campaign-then-user because it never locks a pre-existing
   membership row, but `assign_membership_role`/`change_membership_role`/
   `revoke_membership_role`/`end_campaign_membership` all lock their target
   membership/role row synchronously and only ever acquire `campaign.
   campaigns FOR UPDATE` implicitly, at commit, via the `DEFERRABLE
   INITIALLY DEFERRED` constraint trigger `security.assert_campaign_
   retains_access_manager()` — locking campaign-then-membership here
   instead would invert that relative order and create a genuine A-B-A
   deadlock opportunity against any concurrent role mutation targeting the
   same campaign.

Not covered here (documented rather than silently skipped):

- **Revoke racing membership removal**: `revoke_character_relationship`
  never re-checks membership eligibility at all (unlike `grant_character_
  relationship`) — see that function's own docstring, "a character
  relationship never carries `access.manage`... no retention invariant to
  re-check". Revoking a relationship whose owning membership has just
  ended is not a race this function needs to resolve: the relationship row
  itself, not the membership's current state, is revoke's only concern,
  and its own `FOR UPDATE OF mcr` lock is unaffected by a concurrent
  `security.campaign_memberships` write on a different row. `end_campaign_
  membership` itself now revokes every unrevoked relationship a membership
  holds (checkpoint-4 correction; see `tests/database/
  test_membership_lifecycle_concurrency.py`/`test_api_membership_lifecycle.py`
  for that combined-effect coverage, not duplicated here).
- **"Add racing campaign reassignment" of a character**: not applicable to
  this domain model — a character has a `world_id`, never a `campaign_id`
  of its own (docs/architecture/DATABASE_MODEL.md §19.4), so there is no
  "campaign reassignment" operation to race.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.access_grants import (
    CharacterRelationshipNotActiveError,
    change_character_relationship,
    grant_character_relationship,
    revoke_character_relationship,
)
from dnd_ai.commands.memberships import end_campaign_membership
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


class _RelationshipFixture:
    """An active campaign membership with an unrevoked local-login-free
    target account, and a character in the campaign's own world — the
    minimum needed to grant/change/revoke a character relationship. No
    `access.manage` role is involved (`add_by_membership_id`/`granted_by_
    membership_id` accept any membership id; character relationships carry
    no retention invariant of their own — see this module's docstring)."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Race Campaign", lifecycle_status_code="active"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, manager_role_id, access_manage_id)
        manager_user_id = make_user(connection, "Relationship Race Manager")
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, manager_user_id
        )
        make_membership_role(connection, self.manager_membership_id, manager_role_id)

        self.target_user_id = make_user(connection, "Relationship Race Target")
        self.target_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.target_user_id
        )
        self.character_id = make_character(connection, self.world_id, name="Race Character")
        self.viewer_type_id = lookup_id(
            connection,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "viewer",
        )
        self.portrayer_type_id = lookup_id(
            connection,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "portrayer",
        )
        self.former_controller_type_id = lookup_id(
            connection,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "former_controller",
        )
        self.extra_relationship_type_id = make_character_relationship_type(connection)


def _cleanup_relationship_fixture(
    engine: Engine,
    timeline_id: uuid.UUID,
    world_id: uuid.UUID,
    extra_relationship_type_id: uuid.UUID | None = None,
) -> None:
    """`extra_relationship_type_id` is `_RelationshipFixture.
    extra_relationship_type_id` — every fixture instance creates one,
    unconditionally, since `security.character_relationship_types` is a
    shared lookup table, not scoped by world/campaign like the rows
    deleted below, so every caller of this cleanup must pass it back
    (never left implicit) to avoid leaking a `relationship_type_<hex>`
    row into the shared database on every single test run."""
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(text("DELETE FROM audit.change_log WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(
            text("""
                DELETE FROM security.membership_character_relationships
                WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"), {"t": timeline_id}
        )
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE timeline_id = :t"), {"t": timeline_id}
        )
        cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})
        if extra_relationship_type_id is not None:
            cleanup.execute(
                text(
                    "DELETE FROM security.character_relationship_types "
                    "WHERE character_relationship_type_id = :t"
                ),
                {"t": extra_relationship_type_id},
            )


# ---------------------------------------------------------------------------
# 1. Two concurrent grants of the identical relationship
# ---------------------------------------------------------------------------


def test_two_concurrent_grants_of_the_same_relationship_cannot_both_succeed(
    postgres_engine: Engine,
) -> None:
    """Neither `grant_character_relationship` call locks a pre-existing
    relationship row (there isn't one yet), so this race is resolved by
    `ux_membership_character_relationships_active_type`'s own unique-index
    insertion lock — the second `INSERT` blocks on the first's still-
    uncommitted row until it resolves, then either raises a unique
    violation (committed) or proceeds (rolled back)."""
    engine = postgres_engine
    slug = f"conc-rel-grant-grant-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            grant_character_relationship(
                first,
                campaign_membership_id=target_membership_id,
                character_id=character_id,
                relationship_type_code="viewer",
                campaign_id=campaign_id,
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                grant_character_relationship(
                    second,
                    campaign_membership_id=target_membership_id,
                    character_id=character_id,
                    relationship_type_code="viewer",
                    campaign_id=campaign_id,
                    expected_world_id=world_id,
                    granted_by_membership_id=manager_membership_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the second grant to block on the first's uncommitted "
                f"ux_membership_character_relationships_active_type row, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.connect() as verify:
            count = verify.execute(
                text("""
                    SELECT count(*) FROM security.membership_character_relationships
                    WHERE campaign_membership_id = :m AND character_id = :c AND revoked_at IS NULL
                """),
                {"m": target_membership_id, "c": character_id},
            ).scalar()
            assert count == 1
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)


# ---------------------------------------------------------------------------
# 2. Eligibility-check/write races for grant_character_relationship
# ---------------------------------------------------------------------------


def test_a_membership_ending_cannot_race_a_grant_targeting_it(postgres_engine: Engine) -> None:
    """`grant_character_relationship`'s own `FOR UPDATE OF cm` lock on the
    target membership row must make a concurrent `end_campaign_membership`
    of that same membership block too."""
    engine = postgres_engine
    slug = f"conc-rel-grant-end-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            grant_character_relationship(
                first,
                campaign_membership_id=target_membership_id,
                character_id=character_id,
                relationship_type_code="viewer",
                campaign_id=campaign_id,
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                end_campaign_membership(
                    second,
                    campaign_membership_id=target_membership_id,
                    campaign_id=campaign_id,
                    ended_by_membership_id=manager_membership_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected end_campaign_membership to block on grant_character_relationship's "
                f"own lock of the target membership row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)


def test_a_character_deactivation_cannot_race_a_grant_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`grant_character_relationship`'s own `FOR UPDATE OF e` lock on the
    target character row must make a concurrent deactivation/archival of
    that character block too."""
    engine = postgres_engine
    slug = f"conc-rel-grant-char-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            grant_character_relationship(
                first,
                campaign_membership_id=target_membership_id,
                character_id=character_id,
                relationship_type_code="viewer",
                campaign_id=campaign_id,
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("""
                        UPDATE core.entities SET lifecycle_status_id = (
                            SELECT lifecycle_status_id FROM core.lifecycle_statuses
                            WHERE code = 'archived'
                        )
                        WHERE entity_id = :c
                    """),
                    {"c": character_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the character deactivation to block on grant_character_relationship's "
                f"own lock of the target character row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)


def test_a_relationship_type_deactivation_cannot_race_a_grant_assigning_it(
    postgres_engine: Engine,
) -> None:
    """`grant_character_relationship`'s own `FOR UPDATE` lock on the
    candidate relationship-type row must make a concurrent deactivation of
    that type block too."""
    engine = postgres_engine
    slug = f"conc-rel-grant-type-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id
        extra_relationship_type_id = rf.extra_relationship_type_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            code = first.execute(
                text(
                    "SELECT code FROM security.character_relationship_types WHERE "
                    "character_relationship_type_id = :t"
                ),
                {"t": extra_relationship_type_id},
            ).scalar_one()

            grant_character_relationship(
                first,
                campaign_membership_id=target_membership_id,
                character_id=character_id,
                relationship_type_code=code,
                campaign_id=campaign_id,
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text(
                        "UPDATE security.character_relationship_types SET is_active = false "
                        "WHERE character_relationship_type_id = :t"
                    ),
                    {"t": extra_relationship_type_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the type deactivation to block on grant_character_relationship's own "
                f"lock of the candidate relationship-type row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, extra_relationship_type_id)


# ---------------------------------------------------------------------------
# 3. Eligibility-check/write races for change_character_relationship
# ---------------------------------------------------------------------------


def test_a_relationship_type_deactivation_cannot_race_it_being_assigned_by_a_change(
    postgres_engine: Engine,
) -> None:
    """`change_character_relationship`'s own `FOR UPDATE` lock on the
    candidate new relationship-type row must make a concurrent
    deactivation of that type block too."""
    engine = postgres_engine
    slug = f"conc-rel-change-type-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id
        portrayer_type_id = rf.portrayer_type_id
        relationship_id = make_membership_character_relationship(
            setup,
            target_membership_id,
            character_id,
            rf.viewer_type_id,
            granted_by_membership_id=manager_membership_id,
        )

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            change_character_relationship(
                first,
                membership_character_relationship_id=relationship_id,
                campaign_id=campaign_id,
                new_relationship_type_id=portrayer_type_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text(
                        "UPDATE security.character_relationship_types SET is_active = false "
                        "WHERE character_relationship_type_id = :t"
                    ),
                    {"t": portrayer_type_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the type deactivation to block on change_character_relationship's own "
                f"lock of the candidate new relationship-type row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)
        with engine.begin() as cleanup:
            cleanup.execute(
                text(
                    "UPDATE security.character_relationship_types SET is_active = true "
                    "WHERE character_relationship_type_id = :t"
                ),
                {"t": portrayer_type_id},
            )


# ---------------------------------------------------------------------------
# 5. Relationship mutation racing campaign deactivation (checkpoint-4)
# ---------------------------------------------------------------------------


def test_a_campaign_deactivation_cannot_race_a_grant_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`grant_character_relationship`'s own `FOR UPDATE OF c` lock on the
    campaign row (checkpoint-4 correction) must make a concurrent
    transition of that campaign out of `active` block too — the identical
    proof `test_a_campaign_deactivation_cannot_race_an_add_targeting_it`
    (`test_membership_lifecycle_concurrency.py`) already gives for
    `add_campaign_member`."""
    engine = postgres_engine
    slug = f"conc-rel-grant-campaign-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            grant_character_relationship(
                first,
                campaign_membership_id=target_membership_id,
                character_id=character_id,
                relationship_type_code="viewer",
                campaign_id=campaign_id,
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("""
                        UPDATE campaign.campaigns
                        SET lifecycle_status_id = (
                            SELECT lifecycle_status_id FROM core.lifecycle_statuses
                            WHERE code = 'pending'
                        )
                        WHERE campaign_id = :c
                    """),
                    {"c": campaign_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the campaign deactivation to block on grant_character_relationship's "
                f"own lock of the campaign row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)


def test_a_campaign_deactivation_cannot_race_a_change_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`change_character_relationship`'s own `FOR UPDATE OF c` lock on the
    campaign row (checkpoint-4 correction) must make a concurrent
    transition of that campaign out of `active` block too."""
    engine = postgres_engine
    slug = f"conc-rel-change-campaign-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id = rf.campaign_id
        manager_membership_id = rf.manager_membership_id
        portrayer_type_id = rf.portrayer_type_id
        relationship_id = make_membership_character_relationship(
            setup,
            rf.target_membership_id,
            rf.character_id,
            rf.viewer_type_id,
            granted_by_membership_id=manager_membership_id,
        )

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            change_character_relationship(
                first,
                membership_character_relationship_id=relationship_id,
                campaign_id=campaign_id,
                new_relationship_type_id=portrayer_type_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("""
                        UPDATE campaign.campaigns
                        SET lifecycle_status_id = (
                            SELECT lifecycle_status_id FROM core.lifecycle_statuses
                            WHERE code = 'pending'
                        )
                        WHERE campaign_id = :c
                    """),
                    {"c": campaign_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the campaign deactivation to block on change_character_relationship's "
                f"own lock of the campaign row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)


# ---------------------------------------------------------------------------
# 6. Same-row races: change-vs-revoke, revoke-vs-revoke, change-vs-change
# ---------------------------------------------------------------------------


def test_two_concurrent_revokes_of_the_same_relationship_serialize(
    postgres_engine: Engine,
) -> None:
    """`revoke_character_relationship()`'s own `FOR UPDATE OF mcr` lock on
    its target row must make a second, concurrent revoke of the identical
    row block, then observe the first's committed effect (already revoked)
    once unblocked — never an interleaved write, and never a raised error
    for the second caller (the documented harmless-no-op case)."""
    engine = postgres_engine
    slug = f"conc-rel-revoke-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id = rf.campaign_id
        relationship_id = make_membership_character_relationship(
            setup,
            rf.target_membership_id,
            rf.character_id,
            rf.viewer_type_id,
            granted_by_membership_id=rf.manager_membership_id,
        )

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            revoke_character_relationship(
                first, membership_character_relationship_id=relationship_id, campaign_id=campaign_id
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                revoke_character_relationship(
                    second,
                    membership_character_relationship_id=relationship_id,
                    campaign_id=campaign_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the concurrent revoke to block on the identical row's FOR UPDATE "
                f"lock, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.begin() as third:
            result = revoke_character_relationship(
                third, membership_character_relationship_id=relationship_id, campaign_id=campaign_id
            )
            assert result.revoked is False
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)


def test_a_change_and_a_revoke_of_the_same_relationship_serialize(postgres_engine: Engine) -> None:
    """`change_character_relationship()`'s own `FOR UPDATE OF mcr` lock
    must make a concurrent `revoke_character_relationship()` of the
    identical row block, and vice versa — proven by whichever call is
    issued second blocking on the first's still-open transaction."""
    engine = postgres_engine
    slug = f"conc-rel-change-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id = rf.campaign_id
        manager_membership_id = rf.manager_membership_id
        portrayer_type_id = rf.portrayer_type_id
        relationship_id = make_membership_character_relationship(
            setup,
            rf.target_membership_id,
            rf.character_id,
            rf.viewer_type_id,
            granted_by_membership_id=manager_membership_id,
        )

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            change_character_relationship(
                first,
                membership_character_relationship_id=relationship_id,
                campaign_id=campaign_id,
                new_relationship_type_id=portrayer_type_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                revoke_character_relationship(
                    second,
                    membership_character_relationship_id=relationship_id,
                    campaign_id=campaign_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the concurrent revoke to block on change_character_relationship's own "
                f"lock of the identical row, got: {message}"
            )
            second.rollback()

            first.commit()

        # Unblocked: the row was already revoked (superseded) by the
        # committed change — the documented no-op behavior applies.
        with engine.begin() as third:
            result = revoke_character_relationship(
                third, membership_character_relationship_id=relationship_id, campaign_id=campaign_id
            )
            assert result.revoked is False
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)


def test_two_concurrent_changes_of_the_same_relationship_serialize(
    postgres_engine: Engine,
) -> None:
    """`change_character_relationship()`'s own `FOR UPDATE OF mcr` lock on
    its target row must make a second, concurrent change of the identical
    row block, then observe the first's committed effect (already
    superseded by a new row) once unblocked, raising `CharacterRelationship
    NotActiveError` for the second caller — never an interleaved write, and
    never a silent double-apply."""
    engine = postgres_engine
    slug = f"conc-rel-change-change-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _RelationshipFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id = rf.campaign_id
        manager_membership_id = rf.manager_membership_id
        portrayer_type_id = rf.portrayer_type_id
        former_controller_type_id = rf.former_controller_type_id
        relationship_id = make_membership_character_relationship(
            setup,
            rf.target_membership_id,
            rf.character_id,
            rf.viewer_type_id,
            granted_by_membership_id=manager_membership_id,
        )

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            change_character_relationship(
                first,
                membership_character_relationship_id=relationship_id,
                campaign_id=campaign_id,
                new_relationship_type_id=portrayer_type_id,
                granted_by_membership_id=manager_membership_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                change_character_relationship(
                    second,
                    membership_character_relationship_id=relationship_id,
                    campaign_id=campaign_id,
                    new_relationship_type_id=former_controller_type_id,
                    granted_by_membership_id=manager_membership_id,
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the second change to block on the first's FOR UPDATE OF mcr lock on "
                f"the identical row, got: {message}"
            )
            second.rollback()

            first.commit()

        # Unblocked: the row this second call targeted was already
        # superseded by the committed first change — CharacterRelationship
        # NotActiveError applies, never a silent second apply.
        with engine.begin() as third, pytest.raises(CharacterRelationshipNotActiveError):
            change_character_relationship(
                third,
                membership_character_relationship_id=relationship_id,
                campaign_id=campaign_id,
                new_relationship_type_id=former_controller_type_id,
                granted_by_membership_id=manager_membership_id,
            )

        with engine.connect() as verify:
            active_count = verify.execute(
                text("""
                    SELECT count(*) FROM security.membership_character_relationships
                    WHERE campaign_membership_id = :m AND character_id = :c AND revoked_at IS NULL
                """),
                {"m": rf.target_membership_id, "c": rf.character_id},
            ).scalar()
            assert active_count == 1
    finally:
        _cleanup_relationship_fixture(engine, timeline_id, world_id, rf.extra_relationship_type_id)
