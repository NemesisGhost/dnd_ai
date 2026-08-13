"""Tests for `dnd_ai.api.encounters` — the first command endpoints built on
top of `dnd_ai.api.access`/`dnd_ai.api.auth`/`dnd_ai.api.deps`
(docs/PLAN.md Phase 10 "command endpoints over the existing command/
application services"). `get_authenticated_user_id` is overridden directly
(the same shortcut `test_api_deps.py`/`test_api_integrity_errors.py` use for
`get_connection`) since the OIDC verification chain itself is already fully
covered by `tests/database/test_api_auth.py` — these tests exercise
campaign-capability enforcement and the encounter commands' own HTTP wiring,
not token verification.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_character_state,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant (revision 080) — these tests grant canon.edit, not
        # access.manage, and don't otherwise care about campaign lifecycle.
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.attacker_id = make_character(connection, self.world_id, name="Rin")
        self.defender_id = make_character(connection, self.world_id, name="Borrin")
        make_character_state(
            connection,
            self.timeline_id,
            self.defender_id,
            current_hit_points=20,
            maximum_hit_points=20,
        )

        self.gm_user_id = make_user(connection, "Encounter API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Encounter API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Encounter API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"encounter-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _start_encounter(
    client: TestClient, f: Fixture, *, participant_entity_ids: list[uuid.UUID] | None = None
) -> dict[str, str]:
    if participant_entity_ids is None:
        participant_entity_ids = [f.attacker_id, f.defender_id]
    response = client.post(
        f"/campaigns/{f.campaign_id}/encounters",
        json={
            "world_time_id": str(f.world_time_id),
            "participant_entity_ids": [str(e) for e in participant_entity_ids],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters",
            json={
                "world_time_id": str(f.world_time_id),
                "participant_entity_ids": [str(f.attacker_id)],
            },
        )
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters",
            json={
                "world_time_id": str(f.world_time_id),
                "participant_entity_ids": [str(f.attacker_id)],
            },
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# start_encounter
# ---------------------------------------------------------------------------


def test_starting_an_encounter_creates_it_with_its_participants(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        body = _start_encounter(client, f)

    encounter_id = uuid.UUID(body["encounter_id"])
    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, campaign_id, timeline_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": encounter_id},
        ).one()
        assert row.status == "active"
        assert row.campaign_id == f.campaign_id
        assert row.timeline_id == f.timeline_id

        participant_count = verify.execute(
            text("SELECT count(*) FROM narrative.encounter_participants WHERE encounter_id = :e"),
            {"e": encounter_id},
        ).scalar()
        assert participant_count == 2


def test_starting_an_encounter_with_no_participants_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters",
            json={"world_time_id": str(f.world_time_id), "participant_entity_ids": []},
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# resolve_combat_turn
# ---------------------------------------------------------------------------


def test_a_damaging_combat_turn_updates_persistent_character_state(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        started = _start_encounter(client, f)
        encounter_id = started["encounter_id"]

        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/turns",
            json={
                "round_number": 1,
                "turn_order": 0,
                "actor_entity_id": str(f.attacker_id),
                "world_time_id": str(f.world_time_id),
                "action_kind": "attack",
                "target_entity_id": str(f.defender_id),
                "hit": True,
                "damage_amount": 7,
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["previous_hit_points"] == 20
    assert body["new_hit_points"] == 13
    assert body["event_id"] is not None

    with postgres_engine.connect() as verify:
        hp = verify.execute(
            text(
                "SELECT current_hit_points FROM campaign.character_state "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"t": f.timeline_id, "c": f.defender_id},
        ).scalar()
        assert hp == 13


def test_a_turn_against_an_encounter_from_another_campaign_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient],
    f: Fixture,
    postgres_engine: Engine,
) -> None:
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, f.timeline_id, lifecycle_status_code="pending"
        )

    with client_factory(f.gm_user_id) as client:
        other_encounter = client.post(
            f"/campaigns/{other_campaign_id}/encounters",
            json={
                "world_time_id": str(f.world_time_id),
                "participant_entity_ids": [str(f.attacker_id)],
            },
        )
        assert other_encounter.status_code == 404  # gm_user_id has no membership there

    # Grant the GM access to the other campaign just to create the encounter,
    # then prove it's still unreachable through the *original* campaign's path.
    with postgres_engine.begin() as connection:
        membership_id = make_campaign_membership(connection, other_campaign_id, f.gm_user_id)
        role_id = make_role(
            connection, campaign_id=other_campaign_id, code=f"gm_other_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, membership_id, role_id)

    with client_factory(f.gm_user_id) as client:
        other_encounter = client.post(
            f"/campaigns/{other_campaign_id}/encounters",
            json={
                "world_time_id": str(f.world_time_id),
                "participant_entity_ids": [str(f.attacker_id)],
            },
        )
        assert other_encounter.status_code == 201, other_encounter.text
        other_encounter_id = other_encounter.json()["encounter_id"]

        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{other_encounter_id}/turns",
            json={
                "round_number": 1,
                "turn_order": 0,
                "actor_entity_id": str(f.attacker_id),
                "world_time_id": str(f.world_time_id),
            },
        )
    assert response.status_code == 404


def test_replaying_the_same_round_and_participant_conflicts_rather_than_duplicating(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """narrative.encounter_turns' UNIQUE(encounter_round_id, participant_id)
    (revision 078) is the safety net a naive client retry relies on — see
    dnd_ai.api.encounters' module docstring."""
    with client_factory(f.gm_user_id) as client:
        started = _start_encounter(client, f)
        encounter_id = started["encounter_id"]
        turn_body = {
            "round_number": 1,
            "turn_order": 0,
            "actor_entity_id": str(f.attacker_id),
            "world_time_id": str(f.world_time_id),
        }
        first = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/turns", json=turn_body
        )
        assert first.status_code == 201, first.text

        replay = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/turns", json=turn_body
        )
    assert replay.status_code == 409


# ---------------------------------------------------------------------------
# end_encounter
# ---------------------------------------------------------------------------


def test_ending_an_encounter_marks_it_completed_with_outcomes(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        started = _start_encounter(client, f)
        encounter_id = started["encounter_id"]

        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/end",
            json={
                "world_time_id": str(f.world_time_id),
                "outcomes": [
                    {"participant_entity_id": str(f.attacker_id), "outcome": "escaped"},
                    {"participant_entity_id": str(f.defender_id), "outcome": "defeated"},
                ],
                "summary": "The party wins.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_id"] is not None

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": encounter_id},
        ).one()
        assert row.status == "completed"
        assert str(row.resulting_event_id) == body["event_id"]

        outcome = verify.execute(
            text(
                "SELECT outcome FROM narrative.encounter_participants "
                "WHERE encounter_id = :e AND participant_entity_id = :p"
            ),
            {"e": encounter_id, "p": f.defender_id},
        ).scalar()
        assert outcome == "defeated"


def test_ending_an_encounter_from_another_campaign_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        other_campaign_id = make_campaign(
            connection, f.timeline_id, lifecycle_status_code="pending"
        )
        membership_id = make_campaign_membership(connection, other_campaign_id, f.gm_user_id)
        role_id = make_role(
            connection, campaign_id=other_campaign_id, code=f"gm_other_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, membership_id, role_id)

    with client_factory(f.gm_user_id) as client:
        other_encounter = client.post(
            f"/campaigns/{other_campaign_id}/encounters",
            json={
                "world_time_id": str(f.world_time_id),
                "participant_entity_ids": [str(f.attacker_id)],
            },
        )
        assert other_encounter.status_code == 201, other_encounter.text
        other_encounter_id = other_encounter.json()["encounter_id"]

        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{other_encounter_id}/end",
            json={"world_time_id": str(f.world_time_id)},
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Encounter lifecycle enforcement
# ---------------------------------------------------------------------------


def test_a_turn_after_the_encounter_is_completed_is_conflict(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        started = _start_encounter(client, f)
        encounter_id = started["encounter_id"]

        end_response = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/end",
            json={"world_time_id": str(f.world_time_id)},
        )
        assert end_response.status_code == 200, end_response.text

        turn_response = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/turns",
            json={
                "round_number": 1,
                "turn_order": 0,
                "actor_entity_id": str(f.attacker_id),
                "world_time_id": str(f.world_time_id),
                "target_entity_id": str(f.defender_id),
                "hit": True,
                "damage_amount": 7,
            },
        )

    assert turn_response.status_code == 409
    body = turn_response.json()
    assert str(f.campaign_id) not in body["error"]["message"]
    assert str(encounter_id) not in body["error"]["message"]


def test_ending_an_already_completed_encounter_is_conflict_and_does_not_change_resulting_event(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        started = _start_encounter(client, f)
        encounter_id = started["encounter_id"]

        first = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/end",
            json={"world_time_id": str(f.world_time_id), "summary": "First."},
        )
        assert first.status_code == 200, first.text
        first_event_id = first.json()["event_id"]

        second = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/end",
            json={"world_time_id": str(f.world_time_id), "summary": "Second."},
        )

    assert second.status_code == 409
    body = second.json()
    assert str(encounter_id) not in body["error"]["message"]
    assert first_event_id not in body["error"]["message"]

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id, summary FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": encounter_id},
        ).one()
        assert row.status == "completed"
        assert str(row.resulting_event_id) == first_event_id
        assert row.summary == "First."


# ---------------------------------------------------------------------------
# End-encounter outcome validation
# ---------------------------------------------------------------------------


def test_ending_with_an_unknown_outcome_participant_is_rejected_without_side_effects(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        stranger_id = make_character(connection, f.world_id, name="Stranger")

    with client_factory(f.gm_user_id) as client:
        started = _start_encounter(client, f)
        encounter_id = started["encounter_id"]

        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/end",
            json={
                "world_time_id": str(f.world_time_id),
                "outcomes": [{"participant_entity_id": str(stranger_id), "outcome": "defeated"}],
            },
        )

    assert response.status_code == 400
    body = response.json()
    assert str(stranger_id) not in body["error"]["message"]

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": encounter_id},
        ).one()
        assert row.status == "active"
        assert row.resulting_event_id is None


def test_ending_with_duplicate_outcome_participants_is_rejected_without_side_effects(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        started = _start_encounter(client, f)
        encounter_id = started["encounter_id"]

        response = client.post(
            f"/campaigns/{f.campaign_id}/encounters/{encounter_id}/end",
            json={
                "world_time_id": str(f.world_time_id),
                "outcomes": [
                    {"participant_entity_id": str(f.defender_id), "outcome": "defeated"},
                    {"participant_entity_id": str(f.defender_id), "outcome": "escaped"},
                ],
            },
        )

    assert response.status_code == 400
    body = response.json()
    assert str(f.defender_id) not in body["error"]["message"]

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT status, resulting_event_id FROM narrative.encounters "
                "WHERE encounter_id = :e"
            ),
            {"e": encounter_id},
        ).one()
        assert row.status == "active"
        assert row.resulting_event_id is None

        outcome = verify.execute(
            text(
                "SELECT outcome FROM narrative.encounter_participants "
                "WHERE encounter_id = :e AND participant_entity_id = :p"
            ),
            {"e": encounter_id, "p": f.defender_id},
        ).scalar()
        assert outcome is None
