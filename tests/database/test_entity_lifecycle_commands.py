"""Command-level behavior of dnd_ai.commands.entity_lifecycle (Phase 14)."""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands import entity_lifecycle as cmd
from dnd_ai.domain.authoring import (
    CampaignNotAuthorizedError,
    EntityReferencedError,
    LifecycleNotSupportedError,
    LifecycleTransitionNotAllowedError,
    StaleWriteError,
    SubtypeIncompleteError,
    SupersessionTargetInvalidError,
)
from tests.builders import AuthoredWorld, make_authored_campaign, make_authored_world
from tests.factories import (
    make_character,
    make_entity,
    make_location,
    make_organization,
    make_user,
    make_world,
    status_id,
)

pytestmark = pytest.mark.database


class Ctx:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.owner = make_user(connection, "Lifecycle GM")
        self.world: AuthoredWorld = make_authored_world(connection, owner_user_id=self.owner)
        self.campaign = make_authored_campaign(connection, self.world)

    def location(self, name: str = "Place", canon: str = "draft") -> uuid.UUID:
        location_id = make_location(self.connection, self.world.world_id, name=name)
        self.set_canon(location_id, canon)
        return location_id

    def set_canon(self, entity_id: uuid.UUID, canon: str) -> None:
        self.connection.execute(
            text("UPDATE core.entities SET canon_status_id = :s WHERE entity_id = :e"),
            {"s": status_id(self.connection, "canon_statuses", canon), "e": entity_id},
        )

    def version(self, entity_id: uuid.UUID) -> int:
        value = self.connection.execute(
            text("SELECT row_version FROM core.entities WHERE entity_id = :e"), {"e": entity_id}
        ).scalar()
        assert isinstance(value, int)
        return value

    def row(self, entity_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return self.connection.execute(
            text("""
                SELECT cs.code AS canon, ls.code AS lifecycle, e.archived_at,
                       e.superseded_by_entity_id
                FROM core.entities e
                JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                WHERE e.entity_id = :e
            """),
            {"e": entity_id},
        ).one()

    def call(self, fn, entity_id: uuid.UUID, **kw):  # type: ignore[no-untyped-def]
        if "expected_row_version" not in kw:
            kw["expected_row_version"] = self.version(entity_id)
        return fn(
            self.connection,
            campaign_id=self.campaign,
            entity_id=entity_id,
            actor_user_id=kw.pop("actor", self.owner),
            **kw,
        )


@pytest.fixture
def ctx(db_connection: Connection) -> Ctx:
    return Ctx(db_connection)


# --- the full happy path -----------------------------------------------------------


def test_draft_to_canon_through_review(ctx: Ctx) -> None:
    place = ctx.location()
    submitted = ctx.call(cmd.submit_entity_for_review, place)
    assert (submitted.previous_canon_status, submitted.canon_status) == ("draft", "proposed")
    approved = ctx.call(cmd.approve_entity, place)
    assert approved.canon_status == "approved"
    published = ctx.call(cmd.publish_entity_as_canon, place)
    assert published.canon_status == "canon"
    assert ctx.row(place).canon == "canon"
    assert published.row_version == ctx.version(place)


@pytest.mark.parametrize(
    ("start", "fn", "kwargs", "expected"),
    [
        ("proposed", cmd.return_entity_to_draft, {}, "draft"),
        ("approved", cmd.return_entity_to_draft, {}, "draft"),
        ("rejected", cmd.return_entity_to_draft, {}, "draft"),
        ("draft", cmd.reject_entity, {"reason": "abandoned"}, "rejected"),
        ("proposed", cmd.reject_entity, {}, "rejected"),
    ],
)
def test_other_legal_transitions(ctx: Ctx, start: str, fn, kwargs: dict, expected: str) -> None:  # type: ignore[no-untyped-def]
    place = ctx.location(canon=start)
    assert ctx.call(fn, place, **kwargs).canon_status == expected


@pytest.mark.parametrize(
    ("start", "fn_name"),
    [
        ("canon", "submit_entity_for_review"),
        ("draft", "approve_entity"),
        ("draft", "publish_entity_as_canon"),
        ("proposed", "publish_entity_as_canon"),
        ("canon", "approve_entity"),
        ("canon", "return_entity_to_draft"),
        ("superseded", "submit_entity_for_review"),
        ("deprecated", "approve_entity"),
        ("rejected", "approve_entity"),
    ],
)
def test_illegal_canon_transitions_are_409_and_write_nothing(
    ctx: Ctx, start: str, fn_name: str
) -> None:
    place = ctx.location(canon=start)
    before = ctx.version(place)
    with pytest.raises(LifecycleTransitionNotAllowedError):
        ctx.call(getattr(cmd, fn_name), place)
    assert ctx.version(place) == before and ctx.row(place).canon == start


def test_publish_requires_a_complete_subtype_chain(ctx: Ctx) -> None:
    location_type = ctx.connection.execute(
        text("SELECT entity_type_id FROM core.entity_types WHERE code = 'location'")
    ).scalar()
    bare = make_entity(
        ctx.connection, ctx.world.world_id, location_type, "Bare", canon_status_code="approved"
    )
    with pytest.raises(SubtypeIncompleteError):
        ctx.call(cmd.publish_entity_as_canon, bare)
    complete = ctx.location("Complete", canon="approved")
    assert ctx.call(cmd.publish_entity_as_canon, complete).canon_status == "canon"


def test_organizations_walk_their_ancestry_for_subtypes(ctx: Ctx) -> None:
    org = make_organization(ctx.connection, ctx.world.world_id, name="Guild")
    ctx.set_canon(org, "approved")
    assert ctx.call(cmd.publish_entity_as_canon, org).canon_status == "canon"


# --- eligibility, scope, authority, concurrency ----------------------------------------


@pytest.mark.parametrize("kind", ["character", "event_like"])
def test_ineligible_types_are_refused(ctx: Ctx, kind: str) -> None:
    if kind == "character":
        target = make_character(ctx.connection, ctx.world.world_id, name="Hero")
    else:
        event_type = ctx.connection.execute(
            text("SELECT entity_type_id FROM core.entity_types WHERE code = 'event'")
        ).scalar()
        target = make_entity(
            ctx.connection, ctx.world.world_id, event_type, "E", canon_status_code="draft"
        )
    with pytest.raises(LifecycleNotSupportedError):
        ctx.call(cmd.submit_entity_for_review, target)


def test_an_entity_of_another_world_is_not_found(ctx: Ctx) -> None:
    other = make_authored_world(ctx.connection, owner_user_id=ctx.owner, name="Other")
    foreign = make_location(ctx.connection, other.world_id, name="Foreign")
    with pytest.raises(cmd.EntityNotFoundError):
        ctx.call(cmd.submit_entity_for_review, foreign, expected_row_version=1)
    with pytest.raises(cmd.EntityNotFoundError):
        ctx.call(cmd.submit_entity_for_review, uuid.uuid4(), expected_row_version=1)


def test_authority_is_canon_edit_not_creatorship(ctx: Ctx) -> None:
    place = ctx.location()
    stranger = make_user(ctx.connection, "Stranger")
    with pytest.raises(CampaignNotAuthorizedError):
        ctx.call(cmd.submit_entity_for_review, place, actor=stranger)
    # Even being recorded as the creator grants nothing.
    ctx.connection.execute(
        text("UPDATE core.entities SET created_by_user_id = :u WHERE entity_id = :e"),
        {"u": stranger, "e": place},
    )
    with pytest.raises(CampaignNotAuthorizedError):
        ctx.call(cmd.submit_entity_for_review, place, actor=stranger)


def test_a_stale_version_is_rejected_for_every_transition(ctx: Ctx) -> None:
    place = ctx.location()
    stale = ctx.version(place) - 1
    for fn in (cmd.submit_entity_for_review, cmd.approve_entity, cmd.publish_entity_as_canon):
        with pytest.raises(StaleWriteError):
            ctx.call(fn, place, expected_row_version=stale)


def test_approval_binds_to_the_reviewed_version(ctx: Ctx) -> None:
    place = ctx.location(canon="proposed")
    reviewed = ctx.version(place)
    ctx.connection.execute(
        text("UPDATE core.entities SET summary = 'edited after review' WHERE entity_id = :e"),
        {"e": place},
    )
    with pytest.raises(StaleWriteError):
        ctx.call(cmd.approve_entity, place, expected_row_version=reviewed)


# --- archive / restore ---------------------------------------------------------------------


def test_archive_and_restore_round_trip_and_keep_canon_status(ctx: Ctx) -> None:
    place = ctx.location(canon="canon")
    archived = ctx.call(cmd.archive_entity, place, reason="retired")
    assert (archived.lifecycle_status, archived.canon_status) == ("archived", "canon")
    assert ctx.row(place).archived_at is not None
    restored = ctx.call(cmd.restore_entity, place, reason="reinstated")
    assert (restored.lifecycle_status, restored.canon_status) == ("active", "canon")
    assert ctx.row(place).archived_at is None


def test_a_superseded_entity_restores_to_superseded(ctx: Ctx) -> None:
    old = ctx.location("Old", canon="canon")
    new = ctx.location("New", canon="canon")
    ctx.call(
        cmd.supersede_entity,
        old,
        replacement_entity_id=new,
        replacement_expected_row_version=ctx.version(new),
    )
    ctx.call(cmd.archive_entity, old)
    assert ctx.call(cmd.restore_entity, old, reason="why").canon_status == "superseded"


@pytest.mark.parametrize("canon", ["proposed", "approved"])
def test_an_entity_under_review_cannot_be_archived(ctx: Ctx, canon: str) -> None:
    with pytest.raises(LifecycleTransitionNotAllowedError):
        ctx.call(cmd.archive_entity, ctx.location(canon=canon))


def test_restore_requires_a_reason_an_archived_entity_and_a_complete_chain(ctx: Ctx) -> None:
    from dnd_ai.domain.authoring import AuthoringValidationError

    place = ctx.location(canon="canon")
    with pytest.raises(LifecycleTransitionNotAllowedError):
        ctx.call(cmd.restore_entity, place, reason="not archived")
    ctx.call(cmd.archive_entity, place)
    with pytest.raises(AuthoringValidationError):
        ctx.call(cmd.restore_entity, place, reason="   ")
    ctx.connection.execute(text("DELETE FROM world.locations WHERE location_id = :e"), {"e": place})
    with pytest.raises(SubtypeIncompleteError):
        ctx.call(cmd.restore_entity, place, reason="restore a hollow root")


def test_archiving_twice_is_refused(ctx: Ctx) -> None:
    place = ctx.location(canon="canon")
    ctx.call(cmd.archive_entity, place)
    with pytest.raises(LifecycleTransitionNotAllowedError):
        ctx.call(cmd.archive_entity, place)


# --- supersede ------------------------------------------------------------------------------


def test_supersede_links_both_rows_and_keeps_references(ctx: Ctx) -> None:
    old = ctx.location("Old", canon="canon")
    new = ctx.location("New", canon="approved")
    result = ctx.call(
        cmd.supersede_entity,
        old,
        replacement_entity_id=new,
        replacement_expected_row_version=ctx.version(new),
    )
    assert result.canon_status == "superseded"
    assert result.replacement is not None and result.replacement.canon_status == "canon"
    assert ctx.row(old).superseded_by_entity_id == new
    assert ctx.row(new).canon == "canon"
    # Nothing was moved or deleted: the old definition still resolves.
    assert ctx.row(old).canon == "superseded"


@pytest.mark.parametrize(
    "case", ["self", "missing", "other_world", "other_type", "draft", "archived"]
)
def test_invalid_replacements_are_one_400(ctx: Ctx, case: str) -> None:
    old = ctx.location("Old", canon="canon")
    if case == "self":
        target = old
    elif case == "missing":
        target = uuid.uuid4()
    elif case == "other_world":
        other = make_world(ctx.connection, "supersede-other")
        target = make_location(ctx.connection, other, name="Foreign")
    elif case == "other_type":
        target = make_organization(ctx.connection, ctx.world.world_id, name="Org")
        ctx.set_canon(target, "canon")
    elif case == "draft":
        target = ctx.location("Draft", canon="draft")
    else:
        target = ctx.location("Archived", canon="canon")
        ctx.call(cmd.archive_entity, target)
    with pytest.raises(SupersessionTargetInvalidError):
        ctx.call(
            cmd.supersede_entity,
            old,
            replacement_entity_id=target,
            replacement_expected_row_version=1,
        )


def test_supersede_checks_both_versions(ctx: Ctx) -> None:
    old = ctx.location("Old", canon="canon")
    new = ctx.location("New", canon="canon")
    with pytest.raises(StaleWriteError):
        ctx.call(
            cmd.supersede_entity,
            old,
            replacement_entity_id=new,
            replacement_expected_row_version=ctx.version(new) + 5,
        )
    with pytest.raises(StaleWriteError):
        ctx.call(
            cmd.supersede_entity,
            old,
            expected_row_version=ctx.version(old) + 5,
            replacement_entity_id=new,
            replacement_expected_row_version=ctx.version(new),
        )


def test_supersede_is_atomic_when_the_replacement_cannot_be_published(ctx: Ctx) -> None:
    """An approved replacement with a hollow subtype chain fails the whole
    command: the old entity must not be left superseded."""
    old = ctx.location("Old", canon="canon")
    location_type = ctx.connection.execute(
        text("SELECT entity_type_id FROM core.entity_types WHERE code = 'location'")
    ).scalar()
    hollow = make_entity(
        ctx.connection, ctx.world.world_id, location_type, "Hollow", canon_status_code="approved"
    )
    savepoint = ctx.connection.begin_nested()
    with pytest.raises(SubtypeIncompleteError):
        ctx.call(
            cmd.supersede_entity,
            old,
            replacement_entity_id=hollow,
            replacement_expected_row_version=ctx.version(hollow),
        )
    savepoint.rollback()
    assert ctx.row(old).canon == "canon" and ctx.row(old).superseded_by_entity_id is None


# --- delete draft ------------------------------------------------------------------------------


def test_an_unreferenced_draft_is_deleted_with_its_owned_rows(ctx: Ctx) -> None:
    place = ctx.location("Doomed", canon="draft")
    ctx.connection.execute(
        text(
            "INSERT INTO core.entity_names (entity_id, name_type_id, name) VALUES (:e, "
            "(SELECT name_type_id FROM core.name_types LIMIT 1), 'Alias')"
        ),
        {"e": place},
    )
    result = ctx.call(cmd.delete_draft_entity, place, reason="mistake")
    assert result.deleted is True
    assert result.changed_fields == {"canonical_name": "Doomed", "entity_type_code": "location"}
    for table, column in (
        ("core.entities", "entity_id"),
        ("world.locations", "location_id"),
        ("core.entity_names", "entity_id"),
    ):
        assert (
            ctx.connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :e"), {"e": place}
            ).scalar()
            == 0
        )


def test_a_referenced_draft_is_not_deleted(ctx: Ctx) -> None:
    parent = ctx.location("Parent", canon="draft")
    make_location(ctx.connection, ctx.world.world_id, name="Child", parent_location_id=parent)
    with pytest.raises(EntityReferencedError):
        ctx.call(cmd.delete_draft_entity, parent, reason="oops")
    assert ctx.row(parent).canon == "draft"


@pytest.mark.parametrize("canon", ["proposed", "approved", "canon", "superseded"])
def test_only_drafts_and_rejected_entities_may_be_deleted(ctx: Ctx, canon: str) -> None:
    with pytest.raises(LifecycleTransitionNotAllowedError):
        ctx.call(cmd.delete_draft_entity, ctx.location(canon=canon), reason="no")


def test_delete_requires_a_reason(ctx: Ctx) -> None:
    from dnd_ai.domain.authoring import AuthoringValidationError

    with pytest.raises(AuthoringValidationError):
        ctx.call(cmd.delete_draft_entity, ctx.location(), reason="")


def test_a_rejected_entity_may_be_deleted(ctx: Ctx) -> None:
    place = ctx.location(canon="rejected")
    assert ctx.call(cmd.delete_draft_entity, place, reason="gone").deleted is True
