"""Command-level behavior of dnd_ai.commands.worlds (Phase 14)."""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands import worlds as world_commands
from dnd_ai.commands.worlds import (
    archive_world,
    claim_unowned_world,
    create_world,
    restore_world,
    update_world,
)
from dnd_ai.domain.authoring import (
    AuthoringValidationError,
    LifecycleTransitionNotAllowedError,
    RulesetNotAvailableError,
    StaleWriteError,
    WorldAlreadyClaimedError,
    WorldArchivedError,
    WorldHasActiveCampaignsError,
    WorldNotAuthorizedError,
)
from tests.builders import dnd5e_ids, make_authored_world, make_world_creator
from tests.factories import (
    make_campaign,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


def _create(connection: Connection, owner: uuid.UUID, name: str = "My World") -> uuid.UUID:
    return make_authored_world(connection, owner_user_id=owner, name=name).world_id


# --- create_world ---------------------------------------------------------------


def test_create_world_builds_world_allowlist_owner_and_primary_timeline(
    db_connection: Connection,
) -> None:
    owner = make_world_creator(db_connection, make_user(db_connection))
    ruleset_id, _ = dnd5e_ids(db_connection)
    result = create_world(
        db_connection,
        creator_user_id=owner,
        name="  Eberron  ",
        description="  A world  ",
        ruleset_ids=[ruleset_id],
        default_ruleset_id=ruleset_id,
        primary_timeline_name="Main",
    )

    world = db_connection.execute(
        text(
            "SELECT name, description, default_ruleset_id, row_version FROM core.worlds "
            "WHERE world_id = :w"
        ),
        {"w": result.world_id},
    ).one()
    assert (world.name, world.description, world.default_ruleset_id) == (
        "Eberron",
        "A world",
        ruleset_id,
    )
    assert world.row_version == result.row_version
    allowed = (
        db_connection.execute(
            text("SELECT ruleset_id FROM rules.world_rulesets WHERE world_id = :w"),
            {"w": result.world_id},
        )
        .scalars()
        .all()
    )
    assert allowed == [ruleset_id]
    timeline = db_connection.execute(
        text(
            "SELECT is_primary, parent_timeline_id FROM campaign.timelines WHERE timeline_id = :t"
        ),
        {"t": result.primary_timeline_id},
    ).one()
    assert timeline.is_primary is True and timeline.parent_timeline_id is None
    membership = db_connection.execute(
        text("""
            SELECT wr.code, wm.user_id FROM security.world_memberships wm
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            WHERE wm.world_id = :w
        """),
        {"w": result.world_id},
    ).one()
    assert (membership.code, membership.user_id) == ("world_owner", owner)


def test_two_worlds_with_the_same_name_both_succeed_with_distinct_slugs(
    db_connection: Connection,
) -> None:
    first = _create(db_connection, make_user(db_connection, "A"), "Same Name")
    second = _create(db_connection, make_user(db_connection, "B"), "Same Name")
    slugs = (
        db_connection.execute(
            text("SELECT slug FROM core.worlds WHERE world_id = ANY(:ids)"),
            {"ids": [first, second]},
        )
        .scalars()
        .all()
    )
    assert len(set(slugs)) == 2
    assert all(s.startswith("same-name") for s in slugs)


def test_a_slug_colliding_with_a_legacy_world_is_resolved_silently(
    db_connection: Connection,
) -> None:
    make_world(db_connection, slug="eberron", name="Legacy")
    world_id = _create(db_connection, make_user(db_connection), "Eberron")
    slug = db_connection.execute(
        text("SELECT slug FROM core.worlds WHERE world_id = :w"), {"w": world_id}
    ).scalar()
    assert slug != "eberron" and slug.startswith("eberron-")


@pytest.mark.parametrize(
    "case",
    ["empty_list", "default_outside", "duplicates", "unknown", "non_canon", "no_version"],
)
def test_ruleset_selection_is_validated(db_connection: Connection, case: str) -> None:
    owner = make_world_creator(db_connection, make_user(db_connection))
    ruleset_id, _ = dnd5e_ids(db_connection)
    ids = [ruleset_id]
    default = ruleset_id
    if case == "empty_list":
        ids = []
    elif case == "default_outside":
        default = uuid.uuid4()
    elif case == "duplicates":
        ids = [ruleset_id, ruleset_id]
    elif case == "unknown":
        ids = [ruleset_id, uuid.uuid4()]
    elif case == "non_canon":
        draft = db_connection.execute(
            text("""
                INSERT INTO rules.rulesets (code, display_name, canon_status_id)
                VALUES ('homebrew_draft', 'Homebrew', (SELECT canon_status_id
                        FROM core.canon_statuses WHERE code = 'draft'))
                RETURNING ruleset_id
            """)
        ).scalar()
        db_connection.execute(
            text(
                "INSERT INTO rules.ruleset_versions (ruleset_id, version_label, is_current) "
                "VALUES (:r, '1', true)"
            ),
            {"r": draft},
        )
        ids = [draft]
        default = draft
    elif case == "no_version":
        bare = db_connection.execute(
            text(
                "INSERT INTO rules.rulesets (code, display_name) VALUES ('bare', 'Bare') "
                "RETURNING ruleset_id"
            )
        ).scalar()
        ids = [bare]
        default = bare
    with pytest.raises(RulesetNotAvailableError):
        create_world(
            db_connection,
            creator_user_id=owner,
            name="W",
            description=None,
            ruleset_ids=ids,
            default_ruleset_id=default,
            primary_timeline_name="T",
        )


def test_a_failure_inside_create_world_leaves_no_partial_world(
    db_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = make_world_creator(db_connection, make_user(db_connection))
    ruleset_id, _ = dnd5e_ids(db_connection)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("timeline insert failed")

    monkeypatch.setattr(world_commands, "insert_root_timeline", boom)
    savepoint = db_connection.begin_nested()
    with pytest.raises(RuntimeError):
        create_world(
            db_connection,
            creator_user_id=owner,
            name="Ghost World",
            description=None,
            ruleset_ids=[ruleset_id],
            default_ruleset_id=ruleset_id,
            primary_timeline_name="T",
        )
    savepoint.rollback()
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM core.worlds WHERE name = 'Ghost World'")
        ).scalar()
        == 0
    )
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM security.world_memberships WHERE user_id = :u"),
            {"u": owner},
        ).scalar()
        == 0
    )


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_world_name_is_bounded(db_connection: Connection, name: str) -> None:
    ruleset_id, _ = dnd5e_ids(db_connection)
    with pytest.raises(AuthoringValidationError):
        create_world(
            db_connection,
            creator_user_id=make_world_creator(db_connection, make_user(db_connection)),
            name=name,
            description=None,
            ruleset_ids=[ruleset_id],
            default_ruleset_id=ruleset_id,
            primary_timeline_name="T",
        )


# --- update_world ---------------------------------------------------------------


def test_update_world_changes_fields_and_bumps_the_version(db_connection: Connection) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    result = update_world(
        db_connection,
        world_id=world.world_id,
        actor_user_id=owner,
        expected_row_version=world.row_version,
        name="Renamed",
        description="New",
    )
    assert result.changed is True
    assert result.row_version == world.row_version + 1
    assert set(result.changed_fields) == {"name", "description"}


def test_a_no_op_update_writes_nothing_and_does_not_bump(db_connection: Connection) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner, name="Same")
    result = update_world(
        db_connection,
        world_id=world.world_id,
        actor_user_id=owner,
        expected_row_version=world.row_version,
        name="Same",
        description=None,
    )
    assert result.changed is False
    assert result.row_version == world.row_version


def test_a_stale_update_is_rejected_even_when_it_would_be_a_no_op(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner, name="Same")
    with pytest.raises(StaleWriteError):
        update_world(
            db_connection,
            world_id=world.world_id,
            actor_user_id=owner,
            expected_row_version=world.row_version - 1,
            name="Same",
            description=None,
        )


def test_an_archived_world_cannot_be_edited(db_connection: Connection) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    archived = archive_world(
        db_connection,
        world_id=world.world_id,
        actor_user_id=owner,
        expected_row_version=world.row_version,
    )
    with pytest.raises(WorldArchivedError):
        update_world(
            db_connection,
            world_id=world.world_id,
            actor_user_id=owner,
            expected_row_version=archived.row_version,
            name="Nope",
            description=None,
        )


def test_commands_reject_a_non_owner_a_missing_world_and_an_unclaimed_world_identically(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection, "Owner")
    stranger = make_user(db_connection, "Stranger")
    world = make_authored_world(db_connection, owner_user_id=owner)
    legacy = make_world(db_connection, "legacy-unclaimed")
    for target, actor in (
        (world.world_id, stranger),
        (uuid.uuid4(), owner),
        (legacy, owner),
    ):
        with pytest.raises(WorldNotAuthorizedError):
            update_world(
                db_connection,
                world_id=target,
                actor_user_id=actor,
                expected_row_version=1,
                name="X",
                description=None,
            )


# --- archive / restore ----------------------------------------------------------


def test_archive_then_restore_round_trips(db_connection: Connection) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    archived = archive_world(
        db_connection,
        world_id=world.world_id,
        actor_user_id=owner,
        expected_row_version=world.row_version,
        reason="done",
    )
    assert archived.lifecycle_status == "archived"
    restored = restore_world(
        db_connection,
        world_id=world.world_id,
        actor_user_id=owner,
        expected_row_version=archived.row_version,
    )
    assert restored.lifecycle_status == "active"
    assert restored.row_version == archived.row_version + 1


def test_archive_is_refused_while_a_campaign_is_active_and_discloses_nothing_about_it(
    db_connection: Connection,
) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    make_campaign(db_connection, world.primary_timeline_id, lifecycle_status_code="pending")
    with pytest.raises(WorldHasActiveCampaignsError) as exc:
        archive_world(
            db_connection,
            world_id=world.world_id,
            actor_user_id=owner,
            expected_row_version=world.row_version,
        )
    assert exc.value.safe_message == "The world still has active campaigns."


def test_archive_ignores_archived_campaigns(db_connection: Connection) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    make_campaign(db_connection, world.primary_timeline_id, lifecycle_status_code="archived")
    archive_world(
        db_connection,
        world_id=world.world_id,
        actor_user_id=owner,
        expected_row_version=world.row_version,
    )


def test_archive_and_restore_enforce_legal_transitions(db_connection: Connection) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    with pytest.raises(LifecycleTransitionNotAllowedError):
        restore_world(
            db_connection,
            world_id=world.world_id,
            actor_user_id=owner,
            expected_row_version=world.row_version,
        )
    archived = archive_world(
        db_connection,
        world_id=world.world_id,
        actor_user_id=owner,
        expected_row_version=world.row_version,
    )
    with pytest.raises(LifecycleTransitionNotAllowedError):
        archive_world(
            db_connection,
            world_id=world.world_id,
            actor_user_id=owner,
            expected_row_version=archived.row_version,
        )


def test_archive_does_not_touch_timelines(db_connection: Connection) -> None:
    owner = make_user(db_connection)
    world = make_authored_world(db_connection, owner_user_id=owner)
    other = make_timeline(db_connection, world.world_id, "Extra")
    archive_world(
        db_connection,
        world_id=world.world_id,
        actor_user_id=owner,
        expected_row_version=world.row_version,
    )
    statuses = (
        db_connection.execute(
            text("""
            SELECT ls.code FROM campaign.timelines t
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = t.lifecycle_status_id
            WHERE t.world_id = :w
        """),
            {"w": world.world_id},
        )
        .scalars()
        .all()
    )
    assert set(statuses) == {"active"} and other is not None


# --- claim_unowned_world --------------------------------------------------------


def test_claim_gives_a_legacy_world_its_first_owner(db_connection: Connection) -> None:
    user = make_user(db_connection)
    legacy = make_world(db_connection, "claim-legacy")
    result = claim_unowned_world(db_connection, world_id=legacy, user_id=user)
    assert result.user_id == user
    db_connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_claim_refuses_an_owned_world(db_connection: Connection) -> None:
    owner = make_user(db_connection, "Owner")
    world = make_authored_world(db_connection, owner_user_id=owner)
    with pytest.raises(WorldAlreadyClaimedError):
        claim_unowned_world(
            db_connection, world_id=world.world_id, user_id=make_user(db_connection, "Other")
        )


def test_claim_refuses_a_previously_owned_world_even_with_only_closed_rows(
    db_connection: Connection,
) -> None:
    legacy = make_world(db_connection, "claim-formerly-owned")
    former = make_user(db_connection, "Former")
    db_connection.execute(
        text("""
            INSERT INTO security.world_memberships
                (world_id, user_id, world_role_id, membership_status_id, joined_at, ended_at)
            VALUES (:w, :u,
                (SELECT world_role_id FROM security.world_roles WHERE code = 'world_owner'),
                (SELECT membership_status_id FROM security.membership_statuses
                 WHERE code = 'departed'),
                now(), now())
        """),
        {"w": legacy, "u": former},
    )
    with pytest.raises(WorldAlreadyClaimedError):
        claim_unowned_world(db_connection, world_id=legacy, user_id=make_user(db_connection, "New"))


def test_claim_refuses_an_inactive_user_and_a_missing_world(db_connection: Connection) -> None:
    legacy = make_world(db_connection, "claim-inactive-user")
    with pytest.raises(WorldAlreadyClaimedError):
        claim_unowned_world(
            db_connection,
            world_id=legacy,
            user_id=make_user(db_connection, "Off", status_code="inactive"),
        )
    with pytest.raises(WorldAlreadyClaimedError):
        claim_unowned_world(
            db_connection, world_id=uuid.uuid4(), user_id=make_user(db_connection, "On")
        )
