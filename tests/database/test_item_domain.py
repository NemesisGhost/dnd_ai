"""rules.item_categories/.item_definitions, world.item_instances/.
item_containers, campaign.item_state/.item_ownership/.inventory_entries/.
item_attunements, knowledge.item_identification, and
campaign.character_inventory (revision 077).

Covers: item instance CTI/subtype enforcement, the ruleset-allowance guard
on item_instances (reusing rules.ruleset_allowed_for_world() from revision
029), same-world guards across the new domain, item_state's charges-range
CHECK, inventory_entries' at-most-one-place and no-self-container CHECKs,
item_attunements' broken-requires-attuned CHECK and one-active-attunement-
per-item partial unique index, item_identification's level CHECK and
per-(timeline, item, knower) uniqueness, and the character_inventory read
view.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DataError, IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_character,
    make_event,
    make_inventory_entry,
    make_item_attunement,
    make_item_container,
    make_item_definition,
    make_item_identification,
    make_item_instance,
    make_item_ownership,
    make_item_state,
    make_location,
    make_ruleset_version,
    make_ruleset_version_for_world,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError, DataError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.t0 = make_world_time(connection, self.world_id, 100)
        self.t1 = make_world_time(connection, self.world_id, 200)
        self.ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.item_definition_id = make_item_definition(
            connection, self.ruleset_version_id, code="test_longsword", display_name="Longsword"
        )
        self.item_instance_id = make_item_instance(
            connection, self.world_id, self.item_definition_id, name="A Longsword"
        )
        self.character_id = make_character(connection, self.world_id, name="Rin")
        self.location_id = make_location(connection, self.world_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "item-domain-world")


# ---------------------------------------------------------------------------
# rules.item_definitions / world.item_instances
# ---------------------------------------------------------------------------


def test_an_item_instance_can_be_created(db_connection: Connection, f: Fixture) -> None:
    assert f.item_instance_id is not None


def test_an_item_definitions_code_must_be_unique_per_ruleset_version(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_definition(
            db_connection, f.ruleset_version_id, code="test_longsword", display_name="Duplicate"
        )
    assert "ux_item_definitions_ruleset_version_code" in str(exc.value)


def test_an_item_definitions_rarity_must_be_valid(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_definition(db_connection, f.ruleset_version_id, rarity="not_a_rarity")
    assert "ck_item_definitions_rarity" in str(exc.value)


def test_an_item_instance_requires_a_ruleset_its_world_allows(db_connection: Connection) -> None:
    world_id = make_world(db_connection, slug="item-domain-ruleset-not-allowed")
    unallowed_ruleset_version_id = make_ruleset_version(db_connection)
    item_definition_id = make_item_definition(db_connection, unallowed_ruleset_version_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_instance(db_connection, world_id, item_definition_id)
    assert "ruleset is not allowed for world" in str(exc.value)


# ---------------------------------------------------------------------------
# world.item_containers
# ---------------------------------------------------------------------------


def test_an_item_instance_can_be_marked_as_a_container(
    db_connection: Connection, f: Fixture
) -> None:
    backpack_definition_id = make_item_definition(
        db_connection, f.ruleset_version_id, code="test_backpack", item_category_code="gear"
    )
    backpack_id = make_item_instance(db_connection, f.world_id, backpack_definition_id)
    make_item_container(db_connection, backpack_id, capacity_weight=30, capacity_items=20)


# ---------------------------------------------------------------------------
# campaign.item_state
# ---------------------------------------------------------------------------


def test_item_state_charges_current_must_not_exceed_maximum(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_state(
            db_connection,
            f.timeline_id,
            f.item_instance_id,
            charges_current=5,
            charges_maximum=3,
        )
    assert "ck_item_state_charges_range" in str(exc.value)


def test_item_state_must_share_its_timelines_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="item-domain-other-world")
    other_timeline = make_timeline(db_connection, other_world, is_primary=True)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_state(db_connection, other_timeline, f.item_instance_id)
    assert "belongs to world" in str(exc.value)


def test_item_state_last_event_must_share_its_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id, name="Other Branch")
    foreign_event_id = make_event(db_connection, f.world_id, other_timeline, f.t0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_state(
            db_connection, f.timeline_id, f.item_instance_id, last_event_id=foreign_event_id
        )
    assert "state provenance must cite an event on the same timeline" in str(exc.value)


def test_only_one_current_item_state_row_per_timeline_and_item(
    db_connection: Connection, f: Fixture
) -> None:
    make_item_state(db_connection, f.timeline_id, f.item_instance_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_state(db_connection, f.timeline_id, f.item_instance_id)
    assert "ux_item_state_timeline_item" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.item_ownership
# ---------------------------------------------------------------------------


def test_item_ownership_can_be_unclaimed(db_connection: Connection, f: Fixture) -> None:
    make_item_ownership(db_connection, f.timeline_id, f.item_instance_id, owner_entity_id=None)


def test_item_ownership_owner_must_share_its_timelines_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="item-domain-owner-other-world")
    foreign_character = make_character(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_ownership(
            db_connection, f.timeline_id, f.item_instance_id, owner_entity_id=foreign_character
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.inventory_entries
# ---------------------------------------------------------------------------


def test_an_inventory_entry_can_place_an_item_with_a_holder(
    db_connection: Connection, f: Fixture
) -> None:
    make_inventory_entry(
        db_connection, f.timeline_id, f.item_instance_id, holder_entity_id=f.character_id
    )


def test_an_inventory_entry_rejects_more_than_one_place(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_inventory_entry(
            db_connection,
            f.timeline_id,
            f.item_instance_id,
            holder_entity_id=f.character_id,
            location_id=f.location_id,
        )
    assert "ck_inventory_entries_at_most_one_place" in str(exc.value)


def test_an_inventory_entry_container_must_share_its_timelines_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="item-domain-container-other-world")
    other_ruleset_version = make_ruleset_version_for_world(db_connection, other_world)
    other_definition = make_item_definition(db_connection, other_ruleset_version)
    foreign_container_item = make_item_instance(db_connection, other_world, other_definition)
    foreign_container = make_item_container(db_connection, foreign_container_item)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_inventory_entry(
            db_connection, f.timeline_id, f.item_instance_id, container_id=foreign_container
        )
    assert "belongs to world" in str(exc.value)


def test_only_one_current_inventory_entry_per_timeline_and_item(
    db_connection: Connection, f: Fixture
) -> None:
    make_inventory_entry(
        db_connection, f.timeline_id, f.item_instance_id, holder_entity_id=f.character_id
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_inventory_entry(
            db_connection, f.timeline_id, f.item_instance_id, location_id=f.location_id
        )
    assert "ux_inventory_entries_timeline_item" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.item_attunements
# ---------------------------------------------------------------------------


def test_an_item_attunement_can_be_created(db_connection: Connection, f: Fixture) -> None:
    make_item_attunement(
        db_connection, f.timeline_id, f.item_instance_id, f.character_id, attuned_world_time_id=f.t0
    )


def test_item_attunement_broken_requires_attuned(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_attunement(
            db_connection,
            f.timeline_id,
            f.item_instance_id,
            f.character_id,
            broken_world_time_id=f.t1,
        )
    assert "ck_item_attunements_broken_requires_attuned" in str(exc.value)


def test_only_one_creature_may_be_actively_attuned_to_an_item(
    db_connection: Connection, f: Fixture
) -> None:
    other_character = make_character(db_connection, f.world_id, name="Borrin")
    make_item_attunement(
        db_connection, f.timeline_id, f.item_instance_id, f.character_id, attuned_world_time_id=f.t0
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_attunement(
            db_connection,
            f.timeline_id,
            f.item_instance_id,
            other_character,
            attuned_world_time_id=f.t0,
        )
    assert "ux_item_attunements_active_per_item" in str(exc.value)


def test_a_broken_attunement_does_not_block_a_new_one(
    db_connection: Connection, f: Fixture
) -> None:
    other_character = make_character(db_connection, f.world_id, name="Borrin")
    make_item_attunement(
        db_connection,
        f.timeline_id,
        f.item_instance_id,
        f.character_id,
        attuned_world_time_id=f.t0,
        broken_world_time_id=f.t1,
    )
    # A second, still-active attunement for a different character is fine
    # once the first is broken.
    make_item_attunement(
        db_connection,
        f.timeline_id,
        f.item_instance_id,
        other_character,
        attuned_world_time_id=f.t1,
    )


# ---------------------------------------------------------------------------
# knowledge.item_identification
# ---------------------------------------------------------------------------


def test_item_identification_level_must_be_valid(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_identification(
            db_connection,
            f.timeline_id,
            f.item_instance_id,
            f.character_id,
            identification_level="not_a_level",
        )
    assert "ck_item_identification_level" in str(exc.value)


def test_only_one_identification_row_per_timeline_item_and_knower(
    db_connection: Connection, f: Fixture
) -> None:
    make_item_identification(db_connection, f.timeline_id, f.item_instance_id, f.character_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_item_identification(db_connection, f.timeline_id, f.item_instance_id, f.character_id)
    assert "ux_item_identification_timeline_item_knower" in str(exc.value)


def test_different_knowers_may_hold_different_identification_levels(
    db_connection: Connection, f: Fixture
) -> None:
    other_character = make_character(db_connection, f.world_id, name="Borrin")
    make_item_identification(
        db_connection,
        f.timeline_id,
        f.item_instance_id,
        f.character_id,
        identification_level="fully_identified",
    )
    make_item_identification(
        db_connection,
        f.timeline_id,
        f.item_instance_id,
        other_character,
        identification_level="unidentified",
    )


# ---------------------------------------------------------------------------
# campaign.character_inventory (view)
# ---------------------------------------------------------------------------


def test_character_inventory_view_reflects_a_held_item(
    db_connection: Connection, f: Fixture
) -> None:
    make_item_state(db_connection, f.timeline_id, f.item_instance_id, quantity=2, is_equipped=True)
    make_item_ownership(
        db_connection, f.timeline_id, f.item_instance_id, owner_entity_id=f.character_id
    )
    make_inventory_entry(
        db_connection, f.timeline_id, f.item_instance_id, holder_entity_id=f.character_id
    )

    row = db_connection.execute(
        text("""
            SELECT item_definition_code, quantity, is_equipped, is_owned_by_holder
            FROM campaign.character_inventory
            WHERE timeline_id = :t AND character_id = :c AND item_instance_id = :i
        """),
        {"t": f.timeline_id, "c": f.character_id, "i": f.item_instance_id},
    ).one()

    assert row.item_definition_code == "test_longsword"
    assert row.quantity == 2
    assert row.is_equipped is True
    assert row.is_owned_by_holder is True


def test_character_inventory_view_excludes_items_not_held_by_a_character(
    db_connection: Connection, f: Fixture
) -> None:
    make_inventory_entry(
        db_connection, f.timeline_id, f.item_instance_id, location_id=f.location_id
    )

    count = db_connection.execute(
        text("""
            SELECT count(*) FROM campaign.character_inventory
            WHERE timeline_id = :t AND item_instance_id = :i
        """),
        {"t": f.timeline_id, "i": f.item_instance_id},
    ).scalar()
    assert count == 0
