"""Command-level behavior of dnd_ai.commands.timelines (Phase 14)."""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.timelines import (
    ExistingWorldTime,
    LatestPoint,
    archive_timeline,
    create_timeline,
    create_timeline_branch,
    restore_timeline,
    update_timeline,
)
from dnd_ai.commands.worlds import archive_world
from dnd_ai.domain.authoring import (
    BranchPointInvalidError,
    LifecycleTransitionNotAllowedError,
    PrimaryTimelineNotArchivableError,
    StaleWriteError,
    TimelineArchivedError,
    TimelineHasActiveCampaignsError,
    TimelineNotFoundError,
    WorldArchivedError,
    WorldNotAuthorizedError,
)
from tests.builders import AuthoredWorld, make_authored_world
from tests.factories import make_campaign, make_event, make_timeline, make_user, make_world_time

pytestmark = pytest.mark.database


class Ctx:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.owner = make_user(connection, "Timeline Owner")
        self.world: AuthoredWorld = make_authored_world(connection, owner_user_id=self.owner)

    def branch(
        self,
        parent: uuid.UUID | None = None,
        point: ExistingWorldTime | LatestPoint | None = None,
        name: str = "Branch",
        actor: uuid.UUID | None = None,
    ):  # type: ignore[no-untyped-def]
        return create_timeline_branch(
            self.connection,
            world_id=self.world.world_id,
            parent_timeline_id=parent or self.world.primary_timeline_id,
            actor_user_id=actor or self.owner,
            name=name,
            description=None,
            branch_point=point or LatestPoint(label="Now"),
        )

    def sort_key(self, world_time_id: uuid.UUID) -> int:
        value = self.connection.execute(
            text("SELECT sort_key FROM core.world_times WHERE world_time_id = :w"),
            {"w": world_time_id},
        ).scalar()
        assert isinstance(value, int)
        return value

    def event(self, timeline: uuid.UUID, key: int, status: str = "recorded") -> uuid.UUID:
        time = make_world_time(self.connection, self.world.world_id, key)
        make_event(
            self.connection,
            self.world.world_id,
            timeline,
            time,
            event_status_code=status,
            name=f"e{key}",
        )
        return time


@pytest.fixture
def ctx(db_connection: Connection) -> Ctx:
    return Ctx(db_connection)


# --- create_timeline ---------------------------------------------------------------


def test_create_timeline_adds_a_non_primary_root(ctx: Ctx) -> None:
    result = create_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        actor_user_id=ctx.owner,
        name="  Side Story ",
        description=None,
    )
    row = ctx.connection.execute(
        text(
            "SELECT name, is_primary, parent_timeline_id, branch_world_time_id "
            "FROM campaign.timelines WHERE timeline_id = :t"
        ),
        {"t": result.timeline_id},
    ).one()
    assert (row.name, row.is_primary, row.parent_timeline_id, row.branch_world_time_id) == (
        "Side Story",
        False,
        None,
        None,
    )


def test_create_timeline_requires_authority_and_an_active_world(ctx: Ctx) -> None:
    with pytest.raises(WorldNotAuthorizedError):
        create_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            actor_user_id=make_user(ctx.connection, "Stranger"),
            name="X",
            description=None,
        )
    archive_world(
        ctx.connection,
        world_id=ctx.world.world_id,
        actor_user_id=ctx.owner,
        expected_row_version=ctx.world.row_version,
    )
    with pytest.raises(WorldArchivedError):
        create_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            actor_user_id=ctx.owner,
            name="X",
            description=None,
        )


# --- branching: latest -----------------------------------------------------------


def test_latest_branch_on_an_event_less_timeline_creates_sort_key_zero(ctx: Ctx) -> None:
    result = ctx.branch(point=LatestPoint(label="The Night the Bridge Fell"))
    assert result.created_world_time_id == result.branch_world_time_id
    row = ctx.connection.execute(
        text("""
            SELECT wt.sort_key, wt.label, wt.year, wt.calendar_id, p.code AS precision
            FROM core.world_times wt
            JOIN core.world_time_precisions p
              ON p.world_time_precision_id = wt.world_time_precision_id
            WHERE wt.world_time_id = :w
        """),
        {"w": result.branch_world_time_id},
    ).one()
    assert (row.sort_key, row.label, row.year, row.calendar_id, row.precision) == (
        0,
        "The Night the Bridge Fell",
        None,
        None,
        "narrative",
    )
    timeline = ctx.connection.execute(
        text(
            "SELECT parent_timeline_id, is_primary, branch_event_id FROM campaign.timelines "
            "WHERE timeline_id = :t"
        ),
        {"t": result.timeline_id},
    ).one()
    assert timeline.parent_timeline_id == ctx.world.primary_timeline_id
    assert timeline.is_primary is False
    assert timeline.branch_event_id is None


def test_latest_branch_sits_one_step_after_everything_the_parent_can_see(ctx: Ctx) -> None:
    ctx.event(ctx.world.primary_timeline_id, 100)
    ctx.event(ctx.world.primary_timeline_id, 250)
    result = ctx.branch()
    assert ctx.sort_key(result.branch_world_time_id) == 251


def test_a_nested_latest_branch_never_precedes_its_parents_own_branch_point(ctx: Ctx) -> None:
    ctx.event(ctx.world.primary_timeline_id, 100)
    first = ctx.branch(name="First")  # branch point 101
    second = ctx.branch(parent=first.timeline_id, name="Second")
    assert ctx.sort_key(second.branch_world_time_id) >= ctx.sort_key(first.branch_world_time_id)


def test_a_latest_branch_is_atomic_with_its_world_time(ctx: Ctx) -> None:
    before = ctx.connection.execute(text("SELECT count(*) FROM core.world_times")).scalar()
    savepoint = ctx.connection.begin_nested()
    with pytest.raises(WorldNotAuthorizedError):
        ctx.branch(actor=make_user(ctx.connection, "Stranger"))
    savepoint.rollback()
    assert ctx.connection.execute(text("SELECT count(*) FROM core.world_times")).scalar() == before


# --- branching: existing world time ------------------------------------------------


def test_existing_world_time_accepts_the_parents_recorded_event_time(ctx: Ctx) -> None:
    time = ctx.event(ctx.world.primary_timeline_id, 100)
    result = ctx.branch(point=ExistingWorldTime(world_time_id=time))
    assert result.branch_world_time_id == time
    assert result.created_world_time_id is None


def test_inherited_history_is_branchable_only_at_or_after_the_parents_branch_point(
    ctx: Ctx,
) -> None:
    early = ctx.event(ctx.world.primary_timeline_id, 100)
    at_branch = ctx.event(ctx.world.primary_timeline_id, 300)
    child = ctx.branch(point=ExistingWorldTime(world_time_id=at_branch), name="Child")

    # The child inherits both parent events, but a grandchild may not branch
    # before the child's own branch point (the existing effective_events cap
    # would otherwise let it see ancestor events newer than its branch point).
    with pytest.raises(BranchPointInvalidError):
        ctx.branch(parent=child.timeline_id, point=ExistingWorldTime(world_time_id=early))
    grandchild = ctx.branch(
        parent=child.timeline_id, point=ExistingWorldTime(world_time_id=at_branch)
    )
    assert grandchild.branch_world_time_id == at_branch


@pytest.mark.parametrize(
    "case", ["no_event", "draft_event", "other_world", "nonexistent", "other_timeline"]
)
def test_invalid_branch_points_all_raise_the_same_error(ctx: Ctx, case: str) -> None:
    point: uuid.UUID
    if case == "no_event":
        point = make_world_time(ctx.connection, ctx.world.world_id, 50)
    elif case == "draft_event":
        point = ctx.event(ctx.world.primary_timeline_id, 60, status="draft")
    elif case == "other_world":
        other = make_authored_world(ctx.connection, owner_user_id=ctx.owner, name="Other")
        point = make_world_time(ctx.connection, other.world_id, 1)
        make_event(
            ctx.connection,
            other.world_id,
            other.primary_timeline_id,
            point,
            name="foreign",
        )
    elif case == "other_timeline":
        side = create_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            actor_user_id=ctx.owner,
            name="Side",
            description=None,
        )
        point = ctx.event(side.timeline_id, 70)
    else:
        point = uuid.uuid4()
    with pytest.raises(BranchPointInvalidError) as exc:
        ctx.branch(point=ExistingWorldTime(world_time_id=point))
    assert exc.value.safe_message == "The branch point is not valid for this timeline."


def test_a_branch_cannot_attach_to_an_archived_parent_or_in_an_archived_world(ctx: Ctx) -> None:
    side = create_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        actor_user_id=ctx.owner,
        name="Side",
        description=None,
    )
    archived = archive_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        timeline_id=side.timeline_id,
        actor_user_id=ctx.owner,
        expected_row_version=side.row_version,
    )
    assert archived.lifecycle_status == "archived"
    with pytest.raises(TimelineArchivedError):
        ctx.branch(parent=side.timeline_id)
    archive_world(
        ctx.connection,
        world_id=ctx.world.world_id,
        actor_user_id=ctx.owner,
        expected_row_version=ctx.world.row_version,
    )
    with pytest.raises(WorldArchivedError):
        ctx.branch()


def test_a_timeline_of_another_world_is_not_found_not_forbidden(ctx: Ctx) -> None:
    other = make_authored_world(ctx.connection, owner_user_id=ctx.owner, name="Other")
    with pytest.raises(TimelineNotFoundError):
        ctx.branch(parent=other.primary_timeline_id)
    with pytest.raises(TimelineNotFoundError):
        ctx.branch(parent=uuid.uuid4())


# --- update / archive / restore -----------------------------------------------------


def test_update_stale_noop_and_scope(ctx: Ctx) -> None:
    side = create_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        actor_user_id=ctx.owner,
        name="Side",
        description=None,
    )
    noop = update_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        timeline_id=side.timeline_id,
        actor_user_id=ctx.owner,
        expected_row_version=side.row_version,
        name="Side",
        description=None,
    )
    assert noop.changed is False and noop.row_version == side.row_version
    with pytest.raises(StaleWriteError):
        update_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            timeline_id=side.timeline_id,
            actor_user_id=ctx.owner,
            expected_row_version=side.row_version + 3,
            name="Late",
            description=None,
        )
    changed = update_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        timeline_id=side.timeline_id,
        actor_user_id=ctx.owner,
        expected_row_version=side.row_version,
        name="Renamed",
        description="d",
    )
    assert changed.changed and changed.row_version == side.row_version + 1
    other = make_authored_world(ctx.connection, owner_user_id=ctx.owner, name="Other")
    with pytest.raises(TimelineNotFoundError):
        update_timeline(
            ctx.connection,
            world_id=other.world_id,
            timeline_id=side.timeline_id,
            actor_user_id=ctx.owner,
            expected_row_version=1,
            name="x",
            description=None,
        )


def test_archive_refusals_and_round_trip(ctx: Ctx) -> None:
    with pytest.raises(PrimaryTimelineNotArchivableError):
        archive_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            timeline_id=ctx.world.primary_timeline_id,
            actor_user_id=ctx.owner,
            expected_row_version=1,
        )
    side = create_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        actor_user_id=ctx.owner,
        name="Side",
        description=None,
    )
    campaign = make_campaign(ctx.connection, side.timeline_id, lifecycle_status_code="pending")
    with pytest.raises(TimelineHasActiveCampaignsError):
        archive_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            timeline_id=side.timeline_id,
            actor_user_id=ctx.owner,
            expected_row_version=side.row_version,
        )
    ctx.connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = (SELECT lifecycle_status_id "
            "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE campaign_id = :c"
        ),
        {"c": campaign},
    )
    archived = archive_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        timeline_id=side.timeline_id,
        actor_user_id=ctx.owner,
        expected_row_version=side.row_version,
    )
    with pytest.raises(LifecycleTransitionNotAllowedError):
        archive_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            timeline_id=side.timeline_id,
            actor_user_id=ctx.owner,
            expected_row_version=archived.row_version,
        )
    restored = restore_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        timeline_id=side.timeline_id,
        actor_user_id=ctx.owner,
        expected_row_version=archived.row_version,
    )
    assert restored.lifecycle_status == "active"
    with pytest.raises(LifecycleTransitionNotAllowedError):
        restore_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            timeline_id=side.timeline_id,
            actor_user_id=ctx.owner,
            expected_row_version=restored.row_version,
        )


def test_restore_is_refused_while_the_world_is_archived_and_children_keep_inheriting(
    ctx: Ctx,
) -> None:
    side = create_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        actor_user_id=ctx.owner,
        name="Side",
        description=None,
    )
    child = ctx.branch(parent=side.timeline_id, name="Child")
    archived = archive_timeline(
        ctx.connection,
        world_id=ctx.world.world_id,
        timeline_id=side.timeline_id,
        actor_user_id=ctx.owner,
        expected_row_version=side.row_version,
    )
    status = ctx.connection.execute(
        text("""
            SELECT ls.code FROM campaign.timelines t
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = t.lifecycle_status_id
            WHERE t.timeline_id = :t
        """),
        {"t": child.timeline_id},
    ).scalar()
    assert status == "active"
    archive_world(
        ctx.connection,
        world_id=ctx.world.world_id,
        actor_user_id=ctx.owner,
        expected_row_version=ctx.world.row_version,
    )
    with pytest.raises(WorldArchivedError):
        restore_timeline(
            ctx.connection,
            world_id=ctx.world.world_id,
            timeline_id=side.timeline_id,
            actor_user_id=ctx.owner,
            expected_row_version=archived.row_version,
        )


def test_lineage_cannot_be_changed_after_creation(ctx: Ctx) -> None:
    from sqlalchemy.exc import DBAPIError

    branch = ctx.branch()
    other = make_timeline(ctx.connection, ctx.world.world_id, "Loose")
    with pytest.raises(DBAPIError):
        ctx.connection.execute(
            text("UPDATE campaign.timelines SET parent_timeline_id = :p WHERE timeline_id = :t"),
            {"p": other, "t": branch.timeline_id},
        )
