"""State-changing commands refuse draft and archived definitions (Phase 15.1).

Once a GM can create drafts routinely, a draft or archived definition must not
become reachable through timeline state: movement into a location, a knowledge
reveal, quest objective advancement, an item transfer to a holder or location,
an organization status change, or event participation. Each refusal is the
same fixed 404 a nonexistent record gets, and published (`canon`+`active`)
targets keep working.
"""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands._shared import EntityNotTargetableError
from dnd_ai.commands.events import EventParticipant, _record_event_impl
from dnd_ai.commands.items import _transfer_item_possession_impl
from dnd_ai.commands.knowledge import _reveal_knowledge_to_party_impl
from dnd_ai.commands.movement import _enter_location_impl
from dnd_ai.commands.quests import _advance_objective_impl
from dnd_ai.commands.relationships import _update_organization_status_impl
from tests.factories import (
    make_campaign,
    make_campaign_party,
    make_character,
    make_item_definition,
    make_item_instance,
    make_knowledge_item,
    make_location,
    make_organization,
    make_party,
    make_quest,
    make_quest_objective,
    make_quest_stage,
    make_ruleset_version_for_world,
    make_timeline,
    make_world,
    make_world_time,
    status_id,
)

pytestmark = pytest.mark.database

UNPUBLISHED = [
    ("draft", "active"),
    ("proposed", "active"),
    ("approved", "active"),
    ("rejected", "active"),
    ("superseded", "active"),
    ("canon", "archived"),
]


class World:
    def __init__(self, connection: Connection) -> None:
        self.c = connection
        self.world_id = make_world(connection, slug=f"guard-{uuid.uuid4().hex[:8]}")
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(connection, self.timeline_id)
        self.party_id = make_party(connection, self.world_id)
        make_campaign_party(connection, self.campaign_id, self.party_id)
        self.character_id = make_character(connection, self.world_id, entity_type_code="character")

    def set_status(self, entity_id: uuid.UUID, canon: str, lifecycle: str) -> None:
        self.c.execute(
            text(
                "UPDATE core.entities SET canon_status_id = :c, lifecycle_status_id = :l "
                "WHERE entity_id = :e"
            ),
            {
                "c": status_id(self.c, "canon_statuses", canon),
                "l": status_id(self.c, "lifecycle_statuses", lifecycle),
                "e": entity_id,
            },
        )


@pytest.fixture
def w(db_connection: Connection) -> World:
    return World(db_connection)


def _movement(w: World, entity: uuid.UUID) -> Callable[[], object]:
    return lambda: _enter_location_impl(
        w.c,
        timeline_id=w.timeline_id,
        world_time_id=w.world_time_id,
        character_id=w.character_id,
        location_id=entity,
        campaign_id=w.campaign_id,
    )


def _reveal(w: World, entity: uuid.UUID) -> Callable[[], object]:
    return lambda: _reveal_knowledge_to_party_impl(
        w.c,
        knowledge_item_id=entity,
        party_id=w.party_id,
        timeline_id=w.timeline_id,
        world_time_id=w.world_time_id,
        campaign_id=w.campaign_id,
    )


def _make(w: World, kind: str) -> tuple[uuid.UUID, Callable[[], object]]:
    if kind == "location":
        entity = make_location(w.c, w.world_id)
        return entity, _movement(w, entity)
    if kind == "knowledge":
        entity = make_knowledge_item(w.c, w.world_id)
        return entity, _reveal(w, entity)
    if kind == "quest":
        entity = make_quest(w.c, w.world_id)
        objective = make_quest_objective(w.c, make_quest_stage(w.c, entity))
        return entity, lambda: _advance_objective_impl(
            w.c,
            quest_objective_id=objective,
            timeline_id=w.timeline_id,
            world_time_id=w.world_time_id,
            new_status_code="completed",
            campaign_id=w.campaign_id,
        )
    if kind == "organization":
        entity = make_organization(w.c, w.world_id)
        return entity, lambda: _update_organization_status_impl(
            w.c,
            organization_id=entity,
            timeline_id=w.timeline_id,
            world_time_id=w.world_time_id,
            new_status_code="active",
            campaign_id=w.campaign_id,
        )
    if kind == "item_holder":
        holder = make_location(w.c, w.world_id, name="Holder")
        version = make_ruleset_version_for_world(w.c, w.world_id)
        item = make_item_instance(w.c, w.world_id, make_item_definition(w.c, version))
        return holder, lambda: _transfer_item_possession_impl(
            w.c,
            item_instance_id=item,
            timeline_id=w.timeline_id,
            world_time_id=w.world_time_id,
            location_id=holder,
            campaign_id=w.campaign_id,
        )
    if kind == "event_participant":
        entity = make_location(w.c, w.world_id, name="Participant")
        return entity, lambda: _record_event_impl(
            w.c,
            world_id=w.world_id,
            timeline_id=w.timeline_id,
            world_time_id=w.world_time_id,
            event_type_code="other",
            name="Something happened",
            campaign_id=w.campaign_id,
            participants=(EventParticipant(entity_id=entity, role_code="actor"),),
        )
    raise AssertionError(kind)


KINDS = ["location", "knowledge", "quest", "organization", "item_holder", "event_participant"]


@pytest.mark.parametrize("kind", KINDS)
def test_published_active_targets_still_work(w: World, kind: str) -> None:
    _entity, run = _make(w, kind)
    run()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(("canon", "lifecycle"), UNPUBLISHED)
def test_unpublished_or_archived_targets_are_refused(
    w: World, kind: str, canon: str, lifecycle: str
) -> None:
    entity, run = _make(w, kind)
    w.set_status(entity, canon, lifecycle)
    with pytest.raises(EntityNotTargetableError) as raised:
        run()
    assert raised.value.safe_status_code == 404
    assert str(entity) not in raised.value.safe_message


def test_a_refused_command_writes_no_event(w: World) -> None:
    entity, run = _make(w, "location")
    w.set_status(entity, "draft", "active")
    before = w.c.execute(text("SELECT count(*) FROM narrative.events")).scalar()
    with pytest.raises(EntityNotTargetableError):
        run()
    assert w.c.execute(text("SELECT count(*) FROM narrative.events")).scalar() == before


def test_a_draft_participant_is_refused_for_every_event_path(w: World) -> None:
    entity, run = _make(w, "event_participant")
    w.set_status(entity, "draft", "active")
    with pytest.raises(EntityNotTargetableError):
        run()


def test_a_player_character_is_not_a_guarded_type(w: World) -> None:
    pc = make_character(w.c, w.world_id, entity_type_code="character", name="Hero")
    w.set_status(pc, "draft", "active")
    _record_event_impl(
        w.c,
        world_id=w.world_id,
        timeline_id=w.timeline_id,
        world_time_id=w.world_time_id,
        event_type_code="other",
        name="Hero acts",
        campaign_id=w.campaign_id,
        participants=(EventParticipant(entity_id=pc, role_code="actor"),),
    )
