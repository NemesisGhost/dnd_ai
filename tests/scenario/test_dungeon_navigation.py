"""A party navigates a multi-room dungeon (Phase 5 exit criterion).

docs/PLAN.md Phase 5's exit criteria require: "A party can enter and
navigate a multi-room dungeon" and "Actions can alter dungeon state." The
Phase 5 exit review found that a single character moving through dungeon
areas with no campaign, party, or party membership involved does not prove
either claim — a party's characters navigate together, and "party" is a
first-class concept (campaign.parties / campaign.party_memberships)
distinct from a bare character. This scenario builds the whole chain a real
session would: world -> timeline -> campaign -> party -> character ->
membership -> dungeon -> areas -> connections, then moves the character
room to room and checks both the resulting location history and dungeon
state, plus one case the database actually forbids: a party member cannot
occupy two rooms at once.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    lookup_id,
    make_area_connection,
    make_campaign,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_party,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.scenario

# Four ordered points in fictional chronology.
K0, K1, K2, K3 = 100, 200, 300, 400


def _add_party_to_campaign(connection: Connection, campaign_id, party_id) -> None:
    connection.execute(
        text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
        {"c": campaign_id, "p": party_id},
    )


def _join_party(connection: Connection, timeline_id, party_id, character_id, from_time) -> None:
    connection.execute(
        text("""
            INSERT INTO campaign.party_memberships
                (timeline_id, party_id, member_entity_id, effective_from_world_time_id)
            VALUES (:tl, :p, :m, :f)
        """),
        {"tl": timeline_id, "p": party_id, "m": character_id, "f": from_time},
    )


def _enter_location(
    connection: Connection, timeline_id, character_id, location_id, arrived_at, departed_at=None
) -> None:
    connection.execute(
        text("""
            INSERT INTO campaign.character_location_history
                (timeline_id, character_id, location_id,
                 arrived_at_world_time_id, departed_at_world_time_id)
            VALUES (:tl, :c, :l, :a, :d)
        """),
        {"tl": timeline_id, "c": character_id, "l": location_id, "a": arrived_at, "d": departed_at},
    )


def _close_open_location(connection: Connection, timeline_id, character_id, departed_at) -> None:
    connection.execute(
        text("""
            UPDATE campaign.character_location_history
            SET departed_at_world_time_id = :d
            WHERE timeline_id = :tl AND character_id = :c AND departed_at_world_time_id IS NULL
        """),
        {"tl": timeline_id, "c": character_id, "d": departed_at},
    )


def test_a_party_can_enter_and_navigate_a_multi_room_dungeon(db_connection: Connection) -> None:
    conn = db_connection

    # ---- World, timeline, campaign, party, character, membership ----------
    world_id = make_world(conn, slug="dungeon-navigation-scenario-world")
    timeline_id = make_timeline(conn, world_id, is_primary=True)
    campaign_id = make_campaign(conn, timeline_id, name="The Sunken Vault Campaign")
    party_id = make_party(conn, world_id, name="The Lantern Company")
    _add_party_to_campaign(conn, campaign_id, party_id)

    character_id = make_character(conn, world_id, name="Rin the Scout")
    times = {k: make_world_time(conn, world_id, k) for k in (K0, K1, K2, K3)}
    _join_party(conn, timeline_id, party_id, character_id, times[K0])

    # ---- A three-room dungeon, connected in a line -------------------------
    dungeon_id = make_dungeon(conn, world_id, name="The Sunken Vault")
    entry_hall = make_dungeon_area(conn, dungeon_id, name="Entry Hall")
    corridor = make_dungeon_area(conn, dungeon_id, name="Corridor")
    vault = make_dungeon_area(conn, dungeon_id, name="Vault Chamber")

    door_1 = make_area_connection(conn, entry_hall, corridor, connection_type_code="door")
    door_2 = make_area_connection(
        conn, corridor, vault, connection_type_code="secret_door", is_hidden=True
    )

    # ---- The party's character enters the dungeon and moves room to room --
    _enter_location(conn, timeline_id, character_id, entry_hall, times[K0])
    _close_open_location(conn, timeline_id, character_id, times[K1])
    _enter_location(conn, timeline_id, character_id, corridor, times[K1])
    _close_open_location(conn, timeline_id, character_id, times[K2])
    _enter_location(conn, timeline_id, character_id, vault, times[K2])

    # ---- Verify the resulting location history -----------------------------
    history = conn.execute(
        text("""
            SELECT location_id, location_period::text
            FROM campaign.character_location_history
            WHERE timeline_id = :tl AND character_id = :c
            ORDER BY location_period
        """),
        {"tl": timeline_id, "c": character_id},
    ).all()
    assert [tuple(row) for row in history] == [
        (entry_hall, f"[{K0},{K1})"),
        (corridor, f"[{K1},{K2})"),
        (vault, f"[{K2},)"),
    ]

    current_location = conn.execute(
        text(
            "SELECT location_id FROM campaign.character_location_history "
            "WHERE timeline_id = :tl AND character_id = :c AND departed_at_world_time_id IS NULL"
        ),
        {"tl": timeline_id, "c": character_id},
    ).scalar()
    assert current_location == vault

    # The character is still a party member throughout — the navigation is
    # the party's, not a bare character's.
    membership_count = conn.execute(
        text(
            "SELECT count(*) FROM campaign.party_memberships "
            "WHERE timeline_id = :tl AND party_id = :p AND member_entity_id = :c "
            "AND effective_to_world_time_id IS NULL"
        ),
        {"tl": timeline_id, "p": party_id, "c": character_id},
    ).scalar()
    assert membership_count == 1

    # ---- Actions alter dungeon state ---------------------------------------
    conn.execute(
        text(
            "INSERT INTO campaign.location_state (timeline_id, location_id, is_searched) "
            "VALUES (:tl, :l, true)"
        ),
        {"tl": timeline_id, "l": entry_hall},
    )
    open_status = lookup_id(conn, "campaign", "connection_statuses", "connection_status_id", "open")
    conn.execute(
        text(
            "INSERT INTO campaign.area_connection_state "
            "(timeline_id, area_connection_id, connection_status_id) VALUES (:tl, :c, :s)"
        ),
        {"tl": timeline_id, "c": door_1, "s": open_status},
    )

    entry_hall_searched = conn.execute(
        text(
            "SELECT is_searched FROM campaign.location_state "
            "WHERE timeline_id = :tl AND location_id = :l"
        ),
        {"tl": timeline_id, "l": entry_hall},
    ).scalar()
    assert entry_hall_searched is True

    door_1_status = conn.execute(
        text(
            "SELECT cs.code FROM campaign.area_connection_state acs "
            "JOIN campaign.connection_statuses cs "
            "ON cs.connection_status_id = acs.connection_status_id "
            "WHERE acs.timeline_id = :tl AND acs.area_connection_id = :c"
        ),
        {"tl": timeline_id, "c": door_1},
    ).scalar()
    assert door_1_status == "open"

    # The hidden connection stays hidden and structurally distinct from party
    # knowledge, even after the party has walked past it (docs/architecture/
    # DATABASE_MODEL.md §9.3 — covered in depth by
    # tests/database/test_knowledge_domain.py; checked here too since this
    # scenario is exactly the situation that exit criterion describes).
    door_2_hidden = conn.execute(
        text("SELECT is_hidden FROM world.area_connections WHERE area_connection_id = :c"),
        {"c": door_2},
    ).scalar()
    assert door_2_hidden is True

    # ---- Prohibited case: a party member cannot occupy two rooms at once --
    with pytest.raises(IntegrityError) as exc:
        _enter_location(conn, timeline_id, character_id, entry_hall, times[K1])
    assert "ex_character_location_history_no_overlap" in str(exc.value)
