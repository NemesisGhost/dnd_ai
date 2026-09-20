"""Real PostgreSQL concurrency regression coverage for `dnd_ai.commands.
access_groups` (Phase 13E-B checkpoint 6, campaign access-group
management) plus the group-grantee races checkpoint 6 newly introduced to
`dnd_ai.commands.access_grants.create_resource_grant`/`revoke_resource_
grant` (a group now carries its own mutable lifecycle,
`security.access_groups.lifecycle_status_id`, revision 105 — before this
checkpoint, `test_resource_grant_concurrency.py`'s own docstring correctly
noted there was nothing here to race against).

Mirrors `tests/database/test_resource_grant_concurrency.py`'s own idioms
exactly: genuine row-lock blocking proven with `SET LOCAL lock_timeout` on
a second, independent connection, never a single shared connection or a
mocked delay.

1. **Two concurrent creates of the identical group name** / **two
   concurrent renames to the identical name**: resolved by `ux_access_
   groups_campaign_name`'s own unique-index insertion/update lock.
2. **`add_access_group_member` eligibility-check/write races**: its own
   row locks (group, membership, campaign, owning user — in that order)
   must make a concurrent group-deactivation, membership-ending, or
   account-disablement targeting the same row block.
3. **Two concurrent additions of the identical (group, membership) pair**:
   in practice these serialize on the shared group row lock
   `add_access_group_member` itself takes first — before either reaches
   `ux_access_group_memberships_open`'s own uniqueness check — which is a
   stronger, and just as safe, guarantee.
4. **Two concurrent removals of the identical membership row serialize**
   on `FOR UPDATE OF agm`, mirroring `test_two_concurrent_revokes_of_the_
   same_resource_grant_serialize` exactly.
5. **A group-owned grant create cannot race that group's own
   deactivation**: `create_resource_grant()`'s checkpoint-6 `FOR UPDATE OF
   ag` lock on the grantee group must make a concurrent `deactivate_
   access_group()` of that same group block.
6. **A group deactivation cannot race a manual revoke of one of its own
   grants**: `deactivate_access_group()`'s bulk `UPDATE ... WHERE grantee_
   access_group_id = :group` must block on a row `revoke_resource_grant()`
   already holds `FOR UPDATE OF rg`.
7. **Two concurrent deactivations/reactivations of the same group
   serialize** on the group's own row lock, the loser observing the
   winner's committed effect (already archived/already active) once
   unblocked — never an interleaved write, never a raised error for the
   documented harmless-no-op case.

Not covered here (documented rather than silently skipped):

- **Capability/target-deactivation races for a group-grantee create**:
  `create_resource_grant()`'s target/capability validation is grantee-kind
  -independent — `test_resource_grant_concurrency.py`'s own membership-
  grantee coverage of those same code paths already proves the lock
  ordering holds regardless of which grantee kind precedes them.
- **`remove_access_group_member` racing anything but itself**: it locks
  only its own row and checks no external eligibility condition (`closing
  access must remain possible for cleanup`), so it has nothing else to
  race — mirroring `revoke_resource_grant`'s identical, already-covered
  policy.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.access_grants import create_resource_grant, revoke_resource_grant
from dnd_ai.commands.access_groups import (
    add_access_group_member,
    create_access_group,
    deactivate_access_group,
    reactivate_access_group,
    remove_access_group_member,
    update_access_group,
)
from dnd_ai.commands.memberships import end_campaign_membership
from tests.factories import (
    lookup_id,
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


class _AccessGroupFixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Group Race Campaign", lifecycle_status_code="active"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, manager_role_id, access_manage_id)
        manager_user_id = make_user(connection, "Group Race Manager")
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, manager_user_id
        )
        make_membership_role(connection, self.manager_membership_id, manager_role_id)

        self.target_user_id = make_user(connection, "Group Race Target")
        self.target_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.target_user_id
        )
        self.character_id = make_character(connection, self.world_id, name="Group Race Character")

        self.group_id = make_access_group(connection, self.campaign_id, name="Race Group")


def _cleanup_access_group_fixture(
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
                DELETE FROM security.access_group_memberships WHERE access_group_id IN (
                    SELECT access_group_id FROM security.access_groups WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.access_groups WHERE campaign_id IN (
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
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"), {"t": timeline_id}
        )
        cleanup.execute(text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
        cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})


_LOCK_ERROR_SUBSTRINGS = ("lock_timeout", "canceling statement")


def _assert_blocked(exc_value: BaseException, *, context: str) -> None:
    message = str(exc_value)
    assert any(substring in message for substring in _LOCK_ERROR_SUBSTRINGS), (
        f"expected {context} to block on a still-held row lock, got: {message}"
    )


# ---------------------------------------------------------------------------
# 1. Duplicate name races
# ---------------------------------------------------------------------------


def test_two_concurrent_creates_of_the_same_group_name_cannot_both_succeed(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-group-create-create-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            create_access_group(
                first, campaign_id=campaign_id, name="Duplicate Name", description=None
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                create_access_group(
                    second, campaign_id=campaign_id, name="Duplicate Name", description=None
                )
            _assert_blocked(exc.value, context="the second create")
            second.rollback()

            first.commit()

        with engine.connect() as verify:
            count = verify.execute(
                text(
                    "SELECT count(*) FROM security.access_groups "
                    "WHERE campaign_id = :c AND name = 'Duplicate Name'"
                ),
                {"c": campaign_id},
            ).scalar()
            assert count == 1
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


def test_two_concurrent_renames_to_the_same_name_cannot_both_succeed(
    postgres_engine: Engine,
) -> None:
    engine = postgres_engine
    slug = f"conc-group-rename-rename-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        other_group_id = make_access_group(setup, campaign_id, name="Other Group")
        group_id = fx.group_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            update_access_group(
                first,
                access_group_id=group_id,
                campaign_id=campaign_id,
                name="Shared New Name",
                description=None,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                update_access_group(
                    second,
                    access_group_id=other_group_id,
                    campaign_id=campaign_id,
                    name="Shared New Name",
                    description=None,
                )
            _assert_blocked(exc.value, context="the second rename")
            second.rollback()

            first.commit()

        with engine.connect() as verify:
            count = verify.execute(
                text(
                    "SELECT count(*) FROM security.access_groups "
                    "WHERE campaign_id = :c AND name = 'Shared New Name'"
                ),
                {"c": campaign_id},
            ).scalar()
            assert count == 1
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


# ---------------------------------------------------------------------------
# 2. add_access_group_member eligibility-check/write races
# ---------------------------------------------------------------------------


def test_add_member_cannot_race_group_deactivation(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-group-add-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        group_id, membership_id = fx.group_id, fx.target_membership_id
        manager_id = fx.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_access_group_member(
                first,
                access_group_id=group_id,
                campaign_membership_id=membership_id,
                campaign_id=campaign_id,
                added_by_membership_id=manager_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                deactivate_access_group(second, access_group_id=group_id, campaign_id=campaign_id)
            _assert_blocked(exc.value, context="the concurrent group deactivation")
            second.rollback()

            first.commit()
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


def test_add_member_cannot_race_membership_ending(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-group-add-end-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        group_id, membership_id = fx.group_id, fx.target_membership_id
        manager_id = fx.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_access_group_member(
                first,
                access_group_id=group_id,
                campaign_membership_id=membership_id,
                campaign_id=campaign_id,
                added_by_membership_id=manager_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                end_campaign_membership(
                    second,
                    campaign_membership_id=membership_id,
                    campaign_id=campaign_id,
                    ended_by_membership_id=manager_id,
                )
            _assert_blocked(exc.value, context="the concurrent membership ending")
            second.rollback()

            first.commit()
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


def test_add_member_cannot_race_account_disablement(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-group-add-disable-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        group_id, membership_id = fx.group_id, fx.target_membership_id
        manager_id, target_user_id = fx.manager_membership_id, fx.target_user_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_access_group_member(
                first,
                access_group_id=group_id,
                campaign_membership_id=membership_id,
                campaign_id=campaign_id,
                added_by_membership_id=manager_id,
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
            _assert_blocked(exc.value, context="the concurrent account disablement")
            second.rollback()

            first.commit()
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


# ---------------------------------------------------------------------------
# 3 & 4. Two concurrent additions / two concurrent removals
# ---------------------------------------------------------------------------


def test_two_concurrent_additions_of_the_same_pair_cannot_both_succeed(
    postgres_engine: Engine,
) -> None:
    """Both calls target the identical `(group, membership)` pair — they
    serialize on `add_access_group_member()`'s own group-row lock (taken
    before the membership/campaign/user locks) before either ever reaches
    `ux_access_group_memberships_open`'s own uniqueness check, a stronger
    guarantee than relying on the index alone."""
    engine = postgres_engine
    slug = f"conc-group-add-add-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        group_id, membership_id = fx.group_id, fx.target_membership_id
        manager_id = fx.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            add_access_group_member(
                first,
                access_group_id=group_id,
                campaign_membership_id=membership_id,
                campaign_id=campaign_id,
                added_by_membership_id=manager_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                add_access_group_member(
                    second,
                    access_group_id=group_id,
                    campaign_membership_id=membership_id,
                    campaign_id=campaign_id,
                    added_by_membership_id=manager_id,
                )
            _assert_blocked(exc.value, context="the second concurrent addition")
            second.rollback()

            first.commit()

        with engine.connect() as verify:
            count = verify.execute(
                text("""
                    SELECT count(*) FROM security.access_group_memberships
                    WHERE access_group_id = :g AND campaign_membership_id = :m
                      AND removed_at IS NULL
                """),
                {"g": group_id, "m": membership_id},
            ).scalar()
            assert count == 1
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


def test_two_concurrent_removals_of_the_same_row_serialize(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-group-remove-remove-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        access_group_membership_id = make_access_group_membership(
            setup, fx.group_id, fx.target_membership_id
        )

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            remove_access_group_member(
                first,
                access_group_membership_id=access_group_membership_id,
                campaign_id=campaign_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                remove_access_group_member(
                    second,
                    access_group_membership_id=access_group_membership_id,
                    campaign_id=campaign_id,
                )
            _assert_blocked(exc.value, context="the concurrent removal")
            second.rollback()

            first.commit()

        with engine.begin() as third:
            result = remove_access_group_member(
                third,
                access_group_membership_id=access_group_membership_id,
                campaign_id=campaign_id,
            )
            assert result.removed is False
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


# ---------------------------------------------------------------------------
# 5 & 6. Group-owned grant create/revoke racing group deactivation
# ---------------------------------------------------------------------------


def test_a_group_grant_create_cannot_race_group_deactivation(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-group-grant-create-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        group_id, character_id = fx.group_id, fx.character_id
        manager_id = fx.manager_membership_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            create_resource_grant(
                first,
                campaign_id=campaign_id,
                grantee_campaign_membership_id=None,
                grantee_access_group_id=group_id,
                capability_code="character.view_summary",
                effect="allow",
                expected_world_id=world_id,
                granted_by_membership_id=manager_id,
                character_id=character_id,
            )

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                deactivate_access_group(second, access_group_id=group_id, campaign_id=campaign_id)
            _assert_blocked(exc.value, context="the concurrent group deactivation")
            second.rollback()

            first.commit()
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


def test_a_group_deactivation_cannot_race_a_grant_revocation(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-group-deactivate-revoke-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        group_id = fx.group_id
        view_summary_capability_id = lookup_id(
            setup, "security", "capabilities", "capability_id", "character.view_summary"
        )
        resource_grant_id = make_resource_grant(
            setup,
            campaign_id,
            view_summary_capability_id,
            grantee_access_group_id=group_id,
            character_id=fx.character_id,
            granted_by_membership_id=fx.manager_membership_id,
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
                deactivate_access_group(second, access_group_id=group_id, campaign_id=campaign_id)
            _assert_blocked(exc.value, context="the concurrent group deactivation")
            second.rollback()

            first.commit()

        with engine.connect() as verify:
            revoked_at = verify.execute(
                text(
                    "SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :r"
                ),
                {"r": resource_grant_id},
            ).scalar_one()
            assert revoked_at is not None
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


# ---------------------------------------------------------------------------
# 7. Two concurrent deactivations/reactivations of the same group
# ---------------------------------------------------------------------------


def test_two_concurrent_deactivations_of_the_same_group_serialize(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-group-deactivate-deactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        group_id = fx.group_id

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            deactivate_access_group(first, access_group_id=group_id, campaign_id=campaign_id)

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                deactivate_access_group(second, access_group_id=group_id, campaign_id=campaign_id)
            _assert_blocked(exc.value, context="the concurrent deactivation")
            second.rollback()

            first.commit()

        with engine.begin() as third:
            result = deactivate_access_group(
                third, access_group_id=group_id, campaign_id=campaign_id
            )
            assert result.deactivated is False
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)


def test_two_concurrent_reactivations_of_the_same_group_serialize(postgres_engine: Engine) -> None:
    engine = postgres_engine
    slug = f"conc-group-reactivate-reactivate-{uuid.uuid4().hex[:8]}"
    with engine.begin() as setup:
        fx = _AccessGroupFixture(setup, slug)
        world_id, timeline_id, campaign_id = fx.world_id, fx.timeline_id, fx.campaign_id
        group_id = fx.group_id
        deactivate_access_group(setup, access_group_id=group_id, campaign_id=campaign_id)

    try:
        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            reactivate_access_group(first, access_group_id=group_id, campaign_id=campaign_id)

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception) as exc:
                reactivate_access_group(second, access_group_id=group_id, campaign_id=campaign_id)
            _assert_blocked(exc.value, context="the concurrent reactivation")
            second.rollback()

            first.commit()

        with engine.begin() as third:
            result = reactivate_access_group(
                third, access_group_id=group_id, campaign_id=campaign_id
            )
            assert result.reactivated is False
    finally:
        _cleanup_access_group_fixture(engine, timeline_id, world_id)
