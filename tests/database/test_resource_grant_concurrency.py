"""Real PostgreSQL concurrency regression coverage for `dnd_ai.commands.
access_grants.create_resource_grant`/`revoke_resource_grant` (checkpoint 5,
direct resource-grant management).

Mirrors `tests/database/test_character_relationship_concurrency.py`'s own
idioms exactly — genuine row-lock blocking proven with `SET LOCAL
lock_timeout` on a second, independent connection, never a single shared
connection or a mocked delay:

1. **Two concurrent creates of the identical grant** (same grantee
   membership/target/capability/effect): resolved by `ux_resource_grants_
   active`'s own unique-index insertion lock, exactly like `test_two_
   concurrent_grants_of_the_same_relationship_cannot_both_succeed` — the
   second `INSERT` blocks on the first's still-uncommitted row until it
   resolves, then either raises a unique violation (committed) or proceeds
   (rolled back).

2. **Eligibility-check/write races for `create_resource_grant`**: its own
   row locks (grantee membership, campaign, owning user, target resource,
   candidate capability — in that order) must make a concurrent conflicting
   write block, mirroring `grant_character_relationship`'s own coverage in
   `test_character_relationship_concurrency.py` for the identical class of
   race, extended here with a target-resource variant for each of the two
   `_validate_resource_grant_target()` code paths (an entity-rooted target —
   a character, standing in for all five entity-rooted kinds, which share
   one code path — and a session, the one kind with its own `lifecycle_
   status_id` instead) and a capability-deactivation variant, which
   `grant_character_relationship`'s own relationship-type-deactivation race
   (section 2 of that file) has no direct analogue for.

3. **Two concurrent revokes of the identical grant serialize** on `FOR
   UPDATE`, mirroring `test_two_concurrent_revokes_of_the_same_relationship_
   serialize` exactly — the loser observes the winner's committed effect
   (already revoked) once unblocked, never an interleaved write, never a
   raised error for the documented harmless-no-op case.

Not covered here (documented rather than silently skipped):

- **Revoke racing membership ending**: `revoke_resource_grant` never
  re-checks membership eligibility at all (unlike `create_resource_grant`)
  — see that function's own docstring, matching `revoke_character_
  relationship`'s identical "closing access must remain possible for
  cleanup" policy. `end_campaign_membership` itself now revokes every
  unrevoked resource grant a membership holds (checkpoint 5; see `tests/
  database/test_api_membership_lifecycle.py`/`test_api_campaign_
  invitations.py` for that combined-effect coverage, not duplicated here).
- **Change racing anything**: no `change_resource_grant()` exists — see
  `dnd_ai.commands.access_grants`' own module docstring for why revoke-
  plus-add is the deliberate replacement for a generic edit form here.
- **Access-group-grantee races**: Phase 13E-B checkpoint 6 gave a group
  its own mutable lifecycle (`security.access_groups.lifecycle_status_id`,
  revision 105) and `create_resource_grant()`'s own `FOR UPDATE OF ag`
  lock on it — see `tests/database/test_access_group_concurrency.py` for
  that coverage (a group-grant create racing that same group's
  deactivation, and a group deactivation racing a manual revoke of one of
  its own grants), not duplicated here. No owning-user lock is still taken
  for a group grantee — a group has none of its own.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.access_grants import create_resource_grant, revoke_resource_grant
from dnd_ai.commands.memberships import end_campaign_membership
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


class _ResourceGrantFixture:
    """An active campaign membership with an unrevoked target account, a
    character in the campaign's own world, and a session in the campaign —
    one target of each of the two `_validate_resource_grant_target()` code
    paths (entity-rooted, and `campaign.sessions`' own lifecycle status).
    Mirrors `test_character_relationship_concurrency.py`'s own `_
    RelationshipFixture` shape exactly."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Grant Race Campaign", lifecycle_status_code="active"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, manager_role_id, access_manage_id)
        manager_user_id = make_user(connection, "Grant Race Manager")
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, manager_user_id
        )
        make_membership_role(connection, self.manager_membership_id, manager_role_id)

        self.target_user_id = make_user(connection, "Grant Race Target")
        self.target_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.target_user_id
        )
        self.character_id = make_character(connection, self.world_id, name="Grant Race Character")
        self.session_id = make_session(connection, self.campaign_id, 1)

        self.view_full_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_full"
        )
        self.campaign_view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )


def _cleanup_resource_grant_fixture(
    engine: Engine, timeline_id: uuid.UUID, world_id: uuid.UUID
) -> None:
    with engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(text("DELETE FROM audit.change_log WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(
            text("""
                DELETE FROM security.resource_grants WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
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
                DELETE FROM campaign.sessions WHERE campaign_id IN (
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


# ---------------------------------------------------------------------------
# 1. Two concurrent creates of the identical grant
# ---------------------------------------------------------------------------


def test_two_concurrent_creates_of_the_same_resource_grant_cannot_both_succeed(
    postgres_engine: Engine,
) -> None:
    """Neither `create_resource_grant` call locks a pre-existing grant row
    (there isn't one yet), so this race is resolved by `ux_resource_grants_
    active`'s own unique-index insertion lock — the second `INSERT` blocks
    on the first's still-uncommitted row until it resolves, then either
    raises a unique violation (committed) or proceeds (rolled back)."""
    engine = postgres_engine
    slug = f"conc-grant-create-create-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _ResourceGrantFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id
        capability_id = rf.view_full_capability_id

    def _create(connection: Connection) -> None:
        create_resource_grant(
            connection,
            campaign_id=campaign_id,
            grantee_campaign_membership_id=target_membership_id,
            grantee_access_group_id=None,
            capability_code="character.view_full",
            effect="allow",
            expected_world_id=world_id,
            granted_by_membership_id=manager_membership_id,
            character_id=character_id,
        )

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            _create(first)

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                _create(second)
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the second create to block on the first's uncommitted "
                f"ux_resource_grants_active row, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.connect() as verify:
            count = verify.execute(
                text("""
                    SELECT count(*) FROM security.resource_grants
                    WHERE grantee_campaign_membership_id = :m AND character_id = :c
                      AND capability_id = :cap AND revoked_at IS NULL
                """),
                {"m": target_membership_id, "c": character_id, "cap": capability_id},
            ).scalar()
            assert count == 1
    finally:
        _cleanup_resource_grant_fixture(engine, timeline_id, world_id)


# ---------------------------------------------------------------------------
# 2. Eligibility-check/write races for create_resource_grant
# ---------------------------------------------------------------------------


def test_a_membership_ending_cannot_race_a_create_targeting_it(postgres_engine: Engine) -> None:
    """`create_resource_grant`'s own `FOR UPDATE OF cm` lock on the grantee
    membership row must make a concurrent `end_campaign_membership` of that
    same membership block too — mirroring `test_a_membership_ending_cannot_
    race_a_grant_targeting_it`'s identical proof for `grant_character_
    relationship`."""
    engine = postgres_engine
    slug = f"conc-grant-create-end-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _ResourceGrantFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            create_resource_grant(
                first,
                campaign_id=campaign_id,
                grantee_campaign_membership_id=target_membership_id,
                grantee_access_group_id=None,
                capability_code="character.view_full",
                effect="allow",
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
                character_id=character_id,
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
                f"expected end_campaign_membership to block on create_resource_grant's own "
                f"lock of the target membership row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_resource_grant_fixture(engine, timeline_id, world_id)


def test_an_account_disablement_cannot_race_a_create_targeting_it(postgres_engine: Engine) -> None:
    """`create_resource_grant`'s own `FOR UPDATE OF u` lock on the grantee
    membership's owning user row must make a concurrent disablement of that
    account block too."""
    engine = postgres_engine
    slug = f"conc-grant-create-account-disable-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _ResourceGrantFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        target_user_id = rf.target_user_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            create_resource_grant(
                first,
                campaign_id=campaign_id,
                grantee_campaign_membership_id=target_membership_id,
                grantee_access_group_id=None,
                capability_code="character.view_full",
                effect="allow",
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
                character_id=character_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("""
                        UPDATE security.users SET lifecycle_status_id = (
                            SELECT lifecycle_status_id FROM core.lifecycle_statuses
                            WHERE code = 'inactive'
                        )
                        WHERE user_id = :u
                    """),
                    {"u": target_user_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the account disablement to block on create_resource_grant's own "
                f"lock of the owning user row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_resource_grant_fixture(engine, timeline_id, world_id)


def test_a_campaign_deactivation_cannot_race_a_create_targeting_it(postgres_engine: Engine) -> None:
    """`create_resource_grant`'s own `FOR UPDATE OF c` lock on the campaign
    row must make a concurrent transition of that campaign out of `active`
    block too."""
    engine = postgres_engine
    slug = f"conc-grant-create-campaign-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _ResourceGrantFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            create_resource_grant(
                first,
                campaign_id=campaign_id,
                grantee_campaign_membership_id=target_membership_id,
                grantee_access_group_id=None,
                capability_code="character.view_full",
                effect="allow",
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
                character_id=character_id,
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
                f"expected the campaign deactivation to block on create_resource_grant's own "
                f"lock of the campaign row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_resource_grant_fixture(engine, timeline_id, world_id)


def test_a_target_character_deactivation_cannot_race_a_create_targeting_it(
    postgres_engine: Engine,
) -> None:
    """`_validate_resource_grant_target()`'s own `FOR UPDATE OF e` lock on
    an entity-rooted target (standing in for all five entity-rooted target
    kinds, which share one code path) must make a concurrent deactivation/
    archival of that target block too."""
    engine = postgres_engine
    slug = f"conc-grant-create-char-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _ResourceGrantFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            create_resource_grant(
                first,
                campaign_id=campaign_id,
                grantee_campaign_membership_id=target_membership_id,
                grantee_access_group_id=None,
                capability_code="character.view_full",
                effect="allow",
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
                character_id=character_id,
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
                f"expected the character deactivation to block on create_resource_grant's own "
                f"lock of the target row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_resource_grant_fixture(engine, timeline_id, world_id)


def test_a_target_session_ending_cannot_race_a_create_targeting_it(
    postgres_engine: Engine,
) -> None:
    """The one resource-grant target kind that is not a `core.entities`
    row: `_validate_resource_grant_target()`'s own `FOR UPDATE OF s` lock on
    `campaign.sessions` must make a concurrent deactivation of that session
    block too."""
    engine = postgres_engine
    slug = f"conc-grant-create-session-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _ResourceGrantFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, session_id = rf.campaign_id, rf.session_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            create_resource_grant(
                first,
                campaign_id=campaign_id,
                grantee_campaign_membership_id=target_membership_id,
                grantee_access_group_id=None,
                capability_code="campaign.view",
                effect="allow",
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
                session_id=session_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("""
                        UPDATE campaign.sessions SET lifecycle_status_id = (
                            SELECT lifecycle_status_id FROM core.lifecycle_statuses
                            WHERE code = 'archived'
                        )
                        WHERE session_id = :s
                    """),
                    {"s": session_id},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the session deactivation to block on create_resource_grant's own "
                f"lock of the target session row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_resource_grant_fixture(engine, timeline_id, world_id)


def test_a_capability_deactivation_cannot_race_a_create_assigning_it(
    postgres_engine: Engine,
) -> None:
    """`create_resource_grant`'s own `FOR UPDATE` lock on the candidate
    capability row (`_resolve_grantable_capability_id`) must make a
    concurrent deactivation of that capability block too — `character.
    view_summary` is a real, currently-catalogued `character_id`-target
    capability (unlike `character.discover`, deliberately excluded from
    `RESOURCE_GRANT_CAPABILITY_CATALOG` as of a checkpoint-5 correction —
    see that constant's own docstring); this test never commits the
    deactivation attempt (it is rolled back after the timeout), so this
    leaves no lasting effect on shared state regardless of test ordering."""
    engine = postgres_engine
    slug = f"conc-grant-create-capability-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _ResourceGrantFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id, character_id = rf.campaign_id, rf.character_id
        target_membership_id = rf.target_membership_id
        manager_membership_id = rf.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            create_resource_grant(
                first,
                campaign_id=campaign_id,
                grantee_campaign_membership_id=target_membership_id,
                grantee_access_group_id=None,
                capability_code="character.view_summary",
                effect="allow",
                expected_world_id=world_id,
                granted_by_membership_id=manager_membership_id,
                character_id=character_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                second.execute(
                    text("UPDATE security.capabilities SET is_active = false WHERE code = :c"),
                    {"c": "character.view_summary"},
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the capability deactivation to block on create_resource_grant's "
                f"own lock of the candidate capability row, got: {message}"
            )
            second.rollback()

            first.commit()
    finally:
        _cleanup_resource_grant_fixture(engine, timeline_id, world_id)


# ---------------------------------------------------------------------------
# 3. Two concurrent revokes of the identical grant serialize
# ---------------------------------------------------------------------------


def test_two_concurrent_revokes_of_the_same_resource_grant_serialize(
    postgres_engine: Engine,
) -> None:
    """`revoke_resource_grant()`'s own `FOR UPDATE` lock on its target row
    must make a second, concurrent revoke of the identical row block, then
    observe the first's committed effect (already revoked) once unblocked —
    never an interleaved write, and never a raised error for the second
    caller (the documented harmless-no-op case)."""
    engine = postgres_engine
    slug = f"conc-grant-revoke-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        rf = _ResourceGrantFixture(setup, slug)
        world_id, timeline_id = rf.world_id, rf.timeline_id
        campaign_id = rf.campaign_id
        resource_grant_id = make_resource_grant(
            setup,
            campaign_id,
            rf.view_full_capability_id,
            grantee_campaign_membership_id=rf.target_membership_id,
            character_id=rf.character_id,
            granted_by_membership_id=rf.manager_membership_id,
        )

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            revoke_resource_grant(
                first, resource_grant_id=resource_grant_id, campaign_id=campaign_id
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                revoke_resource_grant(
                    second, resource_grant_id=resource_grant_id, campaign_id=campaign_id
                )
            message = str(exc.value)
            assert "lock_timeout" in message or "canceling statement" in message, (
                f"expected the concurrent revoke to block on the identical row's FOR UPDATE "
                f"lock, got: {message}"
            )
            second.rollback()

            first.commit()

        with engine.begin() as third:
            result = revoke_resource_grant(
                third, resource_grant_id=resource_grant_id, campaign_id=campaign_id
            )
            assert result.revoked is False
    finally:
        _cleanup_resource_grant_fixture(engine, timeline_id, world_id)
