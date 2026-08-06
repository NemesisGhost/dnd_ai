"""interaction.interactions, .actions, .targets, .check_requests,
.check_results, .consequences, .external_messages (revisions 061, 067, 070).

Covers: the world-agreement guard on each table, the timeline/campaign/session
consistency chain on interactions, the check_requests kind/ability/skill
exclusivity rule and ruleset-allow-list enforcement, and the CHECK constraints
on targets/check_results/consequences/external_messages that don't depend on
cross-row lookups. Revision 067's structural append-only guard and revision
070's status-irreversibility and check_results-requires-an-open-interaction
guards are covered here too, directly against the database rather than only
through the application-layer scenario in
tests/scenario/test_resolve_conditional_route_check.py.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    lookup_id,
    make_ability,
    make_action,
    make_area_hazard,
    make_campaign,
    make_character,
    make_check_request,
    make_check_result,
    make_consequence,
    make_dungeon,
    make_dungeon_area,
    make_entity,
    make_event,
    make_interaction,
    make_knowledge_item,
    make_party,
    make_ruleset_version_for_world,
    make_session,
    make_skill,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(connection, self.timeline_id)
        self.session_id = make_session(connection, self.campaign_id, 1)
        self.actor_id = make_character(connection, self.world_id, name="Rin")
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_id = make_dungeon_area(connection, self.dungeon_id)
        self.hazard_id = make_area_hazard(connection, self.area_id)
        self.interaction_id = make_interaction(
            connection,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            session_id=self.session_id,
        )
        self.action_id = make_action(connection, self.interaction_id, self.actor_id)
        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.ability_id = make_ability(connection, ruleset_version_id)
        self.skill_id = make_skill(connection, ruleset_version_id, self.ability_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "interaction-world")


# ---------------------------------------------------------------------------
# interaction.interactions
# ---------------------------------------------------------------------------


def test_an_interaction_can_be_created_with_campaign_and_session(
    db_connection: Connection, f: Fixture
) -> None:
    row = db_connection.execute(
        text(
            "SELECT timeline_id, campaign_id, session_id, status FROM interaction.interactions "
            "WHERE interaction_id = :i"
        ),
        {"i": f.interaction_id},
    ).one()
    assert row.timeline_id == f.timeline_id
    assert row.campaign_id == f.campaign_id
    assert row.session_id == f.session_id
    assert row.status == "initiated"


def test_interaction_status_must_be_a_known_value(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_interaction(db_connection, f.timeline_id, f.world_time_id, status="bogus")
    assert "ck_interactions_status" in str(exc.value)


def test_interaction_world_time_must_belong_to_the_interactions_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="interaction-other-world")
    other_world_time = make_world_time(db_connection, other_world, 50)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_interaction(db_connection, f.timeline_id, other_world_time)
    assert "belongs to world" in str(exc.value)


def test_interaction_campaign_must_belong_to_the_interactions_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id, name="Other Timeline")
    other_campaign = make_campaign(db_connection, other_timeline)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_interaction(db_connection, f.timeline_id, f.world_time_id, campaign_id=other_campaign)
    assert "belongs to timeline" in str(exc.value)


def test_interaction_session_must_belong_to_the_interactions_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_interaction(db_connection, f.timeline_id, f.world_time_id, session_id=f.session_id)
    assert "campaign_id" in str(exc.value)


def test_interaction_resulting_event_must_belong_to_the_same_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id, name="Other Timeline")
    other_event = make_event(db_connection, f.world_id, other_timeline, f.world_time_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_interaction(
            db_connection, f.timeline_id, f.world_time_id, resulting_event_id=other_event
        )
    assert "belongs to timeline" in str(exc.value)


# ---------------------------------------------------------------------------
# interaction.actions
# ---------------------------------------------------------------------------


def test_actions_are_ordered_by_sequence_number(db_connection: Connection, f: Fixture) -> None:
    second = make_action(db_connection, f.interaction_id, f.actor_id, sequence_number=1)
    rows = db_connection.execute(
        text(
            "SELECT action_id FROM interaction.actions WHERE interaction_id = :i "
            "ORDER BY sequence_number"
        ),
        {"i": f.interaction_id},
    ).all()
    assert [r[0] for r in rows] == [f.action_id, second]


def test_two_actions_in_one_interaction_cannot_share_a_sequence_number(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_action(db_connection, f.interaction_id, f.actor_id, sequence_number=0)
    assert "ux_actions_interaction_sequence" in str(exc.value)


def test_action_actor_must_belong_to_the_interactions_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="interaction-actor-other-world")
    other_actor = make_character(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_action(db_connection, f.interaction_id, other_actor, sequence_number=5)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# interaction.targets
# ---------------------------------------------------------------------------


def test_a_target_can_reference_a_hazard(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text("INSERT INTO interaction.targets (action_id, target_area_hazard_id) VALUES (:a, :h)"),
        {"a": f.action_id, "h": f.hazard_id},
    )


def test_a_target_can_be_an_abstract_description_only(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO interaction.targets (action_id, target_description) "
            "VALUES (:a, 'the far wall')"
        ),
        {"a": f.action_id},
    )


def test_a_target_cannot_reference_two_typed_things_at_once(
    db_connection: Connection, f: Fixture
) -> None:
    other_entity = make_entity(
        db_connection,
        f.world_id,
        lookup_id(db_connection, "core", "entity_types", "entity_type_id", "location"),
    )
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO interaction.targets "
                "(action_id, target_entity_id, target_area_hazard_id) VALUES (:a, :e, :h)"
            ),
            {"a": f.action_id, "e": other_entity, "h": f.hazard_id},
        )
    assert "ck_targets_at_most_one_typed_target" in str(exc.value)


def test_a_target_must_identify_something(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text("INSERT INTO interaction.targets (action_id) VALUES (:a)"),
            {"a": f.action_id},
        )
    assert "ck_targets_identifies_something" in str(exc.value)


def test_a_target_must_belong_to_the_actions_world(db_connection: Connection, f: Fixture) -> None:
    other_world = make_world(db_connection, slug="interaction-target-other-world")
    other_hazard = _make_hazard_in(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO interaction.targets (action_id, target_area_hazard_id) VALUES (:a, :h)"
            ),
            {"a": f.action_id, "h": other_hazard},
        )
    assert "belongs to world" in str(exc.value)


def _make_hazard_in(connection, world_id):
    dungeon_id = make_dungeon(connection, world_id)
    area_id = make_dungeon_area(connection, dungeon_id)
    return make_area_hazard(connection, area_id)


# ---------------------------------------------------------------------------
# interaction.check_requests
# ---------------------------------------------------------------------------


def test_a_skill_check_can_be_requested(db_connection: Connection, f: Fixture) -> None:
    make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="skill_check",
        skill_id=f.skill_id,
        difficulty=15,
    )


def test_an_ability_check_can_be_requested(db_connection: Connection, f: Fixture) -> None:
    make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="ability_check",
        ability_id=f.ability_id,
        difficulty=12,
    )


def test_check_kind_must_be_a_known_value(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_check_request(
            db_connection,
            f.action_id,
            f.actor_id,
            check_kind="bogus",
            ability_id=f.ability_id,
        )
    assert "ck_check_requests_kind" in str(exc.value)


def test_a_skill_check_cannot_also_set_ability_id(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_check_request(
            db_connection,
            f.action_id,
            f.actor_id,
            check_kind="skill_check",
            skill_id=f.skill_id,
            ability_id=f.ability_id,
        )
    assert "ck_check_requests_kind_reference" in str(exc.value)


def test_an_ability_check_requires_ability_id(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_check_request(db_connection, f.action_id, f.actor_id, check_kind="ability_check")
    assert "ck_check_requests_kind_reference" in str(exc.value)


def test_advantage_state_must_be_a_known_value(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_check_request(
            db_connection,
            f.action_id,
            f.actor_id,
            check_kind="ability_check",
            ability_id=f.ability_id,
            advantage_state="bogus",
        )
    assert "ck_check_requests_advantage_state" in str(exc.value)


def test_check_request_actor_must_belong_to_the_actions_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="interaction-check-actor-other-world")
    other_actor = make_character(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_check_request(
            db_connection,
            f.action_id,
            other_actor,
            check_kind="ability_check",
            ability_id=f.ability_id,
        )
    assert "belongs to world" in str(exc.value)


def test_check_request_ability_must_be_from_a_ruleset_the_world_allows(
    db_connection: Connection, f: Fixture
) -> None:
    # A ruleset version associated with a different world, so it is not on
    # f.world_id's own rules.world_rulesets allow-list.
    other_world = make_world(db_connection, slug="interaction-ruleset-other-world")
    disallowed_ruleset_version = make_ruleset_version_for_world(db_connection, other_world)
    disallowed_ability = make_ability(db_connection, disallowed_ruleset_version)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_check_request(
            db_connection,
            f.action_id,
            f.actor_id,
            check_kind="ability_check",
            ability_id=disallowed_ability,
        )
    assert "not allowed for world" in str(exc.value)


# ---------------------------------------------------------------------------
# interaction.check_results
# ---------------------------------------------------------------------------


def test_a_check_result_can_be_recorded(db_connection: Connection, f: Fixture) -> None:
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="ability_check",
        ability_id=f.ability_id,
    )
    db_connection.execute(
        text(
            "INSERT INTO interaction.check_results "
            "(check_request_id, roll, total, degree_of_success) "
            "VALUES (:r, 15, 18, 'success')"
        ),
        {"r": request_id},
    )


def test_degree_of_success_must_be_a_known_value(db_connection: Connection, f: Fixture) -> None:
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="ability_check",
        ability_id=f.ability_id,
    )
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO interaction.check_results (check_request_id, degree_of_success) "
                "VALUES (:r, 'bogus')"
            ),
            {"r": request_id},
        )
    assert "ck_check_results_degree_of_success" in str(exc.value)


def test_at_most_one_result_per_check_request(db_connection: Connection, f: Fixture) -> None:
    request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="ability_check",
        ability_id=f.ability_id,
    )
    db_connection.execute(
        text(
            "INSERT INTO interaction.check_results (check_request_id, degree_of_success) "
            "VALUES (:r, 'success')"
        ),
        {"r": request_id},
    )
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO interaction.check_results (check_request_id, degree_of_success) "
                "VALUES (:r, 'failure')"
            ),
            {"r": request_id},
        )
    assert "ux_check_results_one_per_request" in str(exc.value)


# ---------------------------------------------------------------------------
# interaction.consequences
# ---------------------------------------------------------------------------


def test_a_consequence_can_be_proposed(db_connection: Connection, f: Fixture) -> None:
    make_consequence(db_connection, f.interaction_id, consequence_type="observation")


def test_consequence_type_must_be_a_known_value(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_consequence(db_connection, f.interaction_id, consequence_type="bogus")
    assert "ck_consequences_type" in str(exc.value)


def test_consequence_status_must_be_a_known_value(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_consequence(db_connection, f.interaction_id, status="bogus")
    assert "ck_consequences_status" in str(exc.value)


def test_consequence_resulting_event_must_belong_to_the_same_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id, name="Other Timeline")
    other_event = make_event(db_connection, f.world_id, other_timeline, f.world_time_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_consequence(
            db_connection,
            f.interaction_id,
            consequence_type="event",
            resulting_event_id=other_event,
        )
    assert "belongs to timeline" in str(exc.value)


def test_consequence_resulting_discovery_must_belong_to_the_same_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id, name="Other Timeline")
    party_id = make_party(db_connection, f.world_id)
    item_id = make_knowledge_item(db_connection, f.world_id)
    discovery_id = db_connection.execute(
        text(
            "INSERT INTO knowledge.party_discoveries (timeline_id, knowledge_item_id, party_id) "
            "VALUES (:tl, :k, :p) RETURNING party_discovery_id"
        ),
        {"tl": other_timeline, "k": item_id, "p": party_id},
    ).scalar()

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_consequence(
            db_connection,
            f.interaction_id,
            consequence_type="discovery",
            resulting_party_discovery_id=discovery_id,
        )
    assert "belongs to timeline" in str(exc.value)


# ---------------------------------------------------------------------------
# interaction.external_messages
# ---------------------------------------------------------------------------


def test_an_external_message_can_be_recorded(db_connection: Connection, f: Fixture) -> None:
    db_connection.execute(
        text(
            "INSERT INTO interaction.external_messages "
            "(interaction_id, source_system, external_id) VALUES (:i, 'discord', 'msg-123')"
        ),
        {"i": f.interaction_id},
    )


def test_external_message_source_system_must_be_a_known_value(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO interaction.external_messages "
                "(interaction_id, source_system, external_id) VALUES (:i, 'bogus', 'msg-1')"
            ),
            {"i": f.interaction_id},
        )
    assert "ck_external_messages_source_system" in str(exc.value)


def test_the_same_external_message_cannot_be_ingested_twice(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text(
            "INSERT INTO interaction.external_messages "
            "(interaction_id, source_system, external_id) VALUES (:i, 'foundry', 'evt-42')"
        ),
        {"i": f.interaction_id},
    )
    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "INSERT INTO interaction.external_messages "
                "(interaction_id, source_system, external_id) VALUES (:i, 'foundry', 'evt-42')"
            ),
            {"i": f.interaction_id},
        )
    assert "ux_external_messages_source_external_id" in str(exc.value)


# ---------------------------------------------------------------------------
# Interaction status irreversibility (revision 070) — a terminal status
# (resolved/failed/cancelled) can never change, which is what keeps revision
# 067's structural append-only guard from being bypassed by first reverting
# the status.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_status", ["resolved", "failed", "cancelled"])
@pytest.mark.parametrize("target_status", ["initiated", "resolving"])
def test_a_terminal_interaction_cannot_revert_to_a_nonterminal_status(
    db_connection: Connection, f: Fixture, terminal_status: str, target_status: str
) -> None:
    interaction_id = make_interaction(
        db_connection, f.timeline_id, f.world_time_id, status=terminal_status
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE interaction.interactions SET status = :s WHERE interaction_id = :i"),
            {"s": target_status, "i": interaction_id},
        )
    assert "terminal status" in str(exc.value)


@pytest.mark.parametrize("terminal_status", ["resolved", "failed", "cancelled"])
def test_a_terminal_interaction_cannot_move_to_a_different_terminal_status(
    db_connection: Connection, f: Fixture, terminal_status: str
) -> None:
    interaction_id = make_interaction(
        db_connection, f.timeline_id, f.world_time_id, status=terminal_status
    )
    other_terminal = next(s for s in ("resolved", "failed", "cancelled") if s != terminal_status)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE interaction.interactions SET status = :s WHERE interaction_id = :i"),
            {"s": other_terminal, "i": interaction_id},
        )
    assert "terminal status" in str(exc.value)


@pytest.mark.parametrize("terminal_status", ["resolved", "failed", "cancelled"])
def test_a_terminal_interactions_status_can_be_rewritten_to_itself(
    db_connection: Connection, f: Fixture, terminal_status: str
) -> None:
    """A no-op write (e.g. an idempotent retry) is not a transition and must
    not be rejected."""
    interaction_id = make_interaction(
        db_connection, f.timeline_id, f.world_time_id, status=terminal_status
    )
    db_connection.execute(
        text("UPDATE interaction.interactions SET status = :s WHERE interaction_id = :i"),
        {"s": terminal_status, "i": interaction_id},
    )


def test_an_interaction_can_move_from_initiated_through_resolving_to_resolved(
    db_connection: Connection, f: Fixture
) -> None:
    """Normal creation and resolution: every transition before a terminal
    status is reached remains unrestricted."""
    db_connection.execute(
        text("UPDATE interaction.interactions SET status = 'resolving' WHERE interaction_id = :i"),
        {"i": f.interaction_id},
    )
    db_connection.execute(
        text("UPDATE interaction.interactions SET status = 'resolved' WHERE interaction_id = :i"),
        {"i": f.interaction_id},
    )
    status = db_connection.execute(
        text("SELECT status FROM interaction.interactions WHERE interaction_id = :i"),
        {"i": f.interaction_id},
    ).scalar()
    assert status == "resolved"


@pytest.mark.parametrize(
    ("attempt", "table"),
    [
        ("update", "actions"),
        ("delete", "actions"),
        ("update", "check_requests"),
        ("delete", "check_requests"),
    ],
)
def test_a_resolved_interactions_structural_history_cannot_be_edited_or_deleted(
    db_connection: Connection, f: Fixture, attempt: str, table: str
) -> None:
    """DB-level companion to tests/scenario/test_resolve_conditional_route_
    check.py's test_structural_records_are_immutable_after_resolution —
    revision 067's guard, exercised directly here rather than only through
    the application layer."""
    check_request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="ability_check",
        ability_id=f.ability_id,
    )
    db_connection.execute(
        text("UPDATE interaction.interactions SET status = 'resolved' WHERE interaction_id = :i"),
        {"i": f.interaction_id},
    )

    row_id = f.action_id if table == "actions" else check_request_id
    pk_column = "action_id" if table == "actions" else "check_request_id"
    update_column = "description" if table == "actions" else "stakes"

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        if attempt == "update":
            db_connection.execute(
                text(
                    f"UPDATE interaction.{table} SET {update_column} = 'x' WHERE {pk_column} = :id"
                ),
                {"id": row_id},
            )
        else:
            db_connection.execute(
                text(f"DELETE FROM interaction.{table} WHERE {pk_column} = :id"), {"id": row_id}
            )
    assert "append-only once resolution begins" in str(exc.value)


def test_a_check_result_cannot_be_recorded_against_an_already_resolved_interaction(
    db_connection: Connection, f: Fixture
) -> None:
    """Revision 070's other guard: a check_results row requires its
    interaction still be 'initiated' at INSERT time, not just at UPDATE/
    DELETE time (revision 067)."""
    check_request_id = make_check_request(
        db_connection,
        f.action_id,
        f.actor_id,
        check_kind="ability_check",
        ability_id=f.ability_id,
    )
    db_connection.execute(
        text("UPDATE interaction.interactions SET status = 'resolved' WHERE interaction_id = :i"),
        {"i": f.interaction_id},
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_check_result(db_connection, check_request_id, degree_of_success="success")
    assert "append-only once resolution begins" in str(exc.value)
