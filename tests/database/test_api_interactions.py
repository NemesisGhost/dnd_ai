"""Tests for `dnd_ai.api.interactions` — Phase 10 workstream 9's command
endpoints over `dnd_ai.commands.interactions.perform_interaction`/
`.resolve_check` (docs/PLAN.md Phase 10 "command endpoints over the
existing command/application services", the last remaining
"interactions/events" domain the Phase 10 progress note names). Mirrors
`tests/database/test_api_quests.py`'s shape: `get_authenticated_user_id` is
overridden directly (the OIDC verification chain itself is already fully
covered by `tests/database/test_api_auth.py`) since these tests exercise
campaign-capability enforcement and the interaction commands' own HTTP
wiring, not token verification.

The `resolve_check` fixture (a conditional, lockpick-guarded route between
two dungeon areas) mirrors `tests/scenario/test_resolve_conditional_route_
check.py`'s own setup — this file proves the same command works correctly
when driven through HTTP, plus the campaign-ownership check
(`dnd_ai.commands.interactions._lock_interaction_for_check_resolution`)
that only exists at this layer, since `interaction.interactions` (unlike
`world.relationships`/`narrative.quest_objectives`) carries its own
`campaign_id`.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.interactions import CheckRequestSpec, TargetSpec, perform_interaction
from tests.factories import (
    lookup_id,
    make_ability,
    make_area_connection,
    make_area_hazard,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
    make_membership_role,
    make_party,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_session,
    make_skill,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

# Mirrors dnd_ai.api.interactions' own private command-name constants —
# duplicated here deliberately (tests assert on the public audit.change_log
# contract, not by importing the module's private constants).
_PERFORM_INTERACTION_COMMAND = "perform_interaction"
_RESOLVE_CHECK_COMMAND = "resolve_check"


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.session_id = make_session(connection, self.campaign_id, 1)

        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )
        self.other_session_id = make_session(connection, self.other_campaign_id, 1)

        self.actor_id = make_character(connection, self.world_id, name="Rin")

        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Vault")
        self.connection_id = make_area_connection(connection, self.area_a, self.area_b)
        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.ability_id = make_ability(connection, ruleset_version_id)
        self.skill_id = make_skill(connection, ruleset_version_id, self.ability_id)
        connection.execute(
            text(
                "UPDATE world.area_connections SET is_conditional = true, "
                "condition_description = 'locked until picked', required_check_kind = 'skill_check', "
                "required_skill_id = :s, required_difficulty = 15 WHERE area_connection_id = :c"
            ),
            {"s": self.skill_id, "c": self.connection_id},
        )

        self.gm_user_id = make_user(connection, "Interaction API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, role_id)

        # Membership in the *other* campaign too, with the same capability —
        # used to prove resolve_check rejects a check request that belongs
        # to a different campaign than the one named in the URL.
        other_gm_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.gm_user_id
        )
        other_role_id = make_role(
            connection, campaign_id=self.other_campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, other_role_id, canon_edit_id)
        make_membership_role(connection, other_gm_membership_id, other_role_id)

        self.capless_user_id = make_user(connection, "Interaction API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Interaction API Outsider")

        # Workstream 26: a hidden hazard with a matching knowledge item (for
        # the discovery consequence) plus a party to attribute it to.
        self.hazard_id = make_area_hazard(connection, self.area_a, is_hidden=True)
        self.hazard_knowledge_item_id = make_knowledge_item(
            connection, self.world_id, subject_area_hazard_id=self.hazard_id
        )
        self.party_id = make_party(connection, self.world_id)


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"interaction-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM campaign.area_connection_state WHERE timeline_id = :t
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.hazard_state WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM knowledge.party_discoveries WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.roles WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.campaign_memberships WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM campaign.sessions WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.idempotent_requests WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                ]
            },
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("""
                DELETE FROM interaction.interactions
                WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)
            """),
            {"w": fixture.world_id},
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


def _interactions_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/interactions"


def _resolve_url(campaign_id: uuid.UUID, check_request_id: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/checks/{check_request_id}/resolve"


def _pick_lock_body(f: Fixture, *, session_id: uuid.UUID | None = None) -> dict[str, object]:
    return {
        "world_time_id": str(f.world_time_id),
        "actor_entity_id": str(f.actor_id),
        "interaction_type_code": "pick_lock",
        "action_description": "Rin picks the vault door's lock.",
        "session_id": str(session_id) if session_id is not None else None,
        "targets": [{"target_area_connection_id": str(f.connection_id)}],
        "check_requests": [
            {"check_kind": "skill_check", "difficulty": 15, "skill_id": str(f.skill_id)}
        ],
    }


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(_interactions_url(f), json=_pick_lock_body(f))
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(_interactions_url(f), json=_pick_lock_body(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# perform_interaction
# ---------------------------------------------------------------------------


def test_performing_an_interaction_creates_the_full_structure(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _interactions_url(f), json=_pick_lock_body(f, session_id=f.session_id)
        )
    assert response.status_code == 201, response.text
    body = response.json()
    interaction_id = uuid.UUID(body["interaction_id"])
    assert len(body["target_ids"]) == 1
    assert len(body["check_request_ids"]) == 1

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT timeline_id, campaign_id, session_id, status "
                "FROM interaction.interactions WHERE interaction_id = :i"
            ),
            {"i": interaction_id},
        ).one()
        assert row.timeline_id == f.timeline_id
        assert row.campaign_id == f.campaign_id
        assert row.session_id == f.session_id
        assert row.status == "initiated"


def test_a_session_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _interactions_url(f), json=_pick_lock_body(f, session_id=f.other_session_id)
        )
    assert response.status_code == 404


def test_the_audit_row_uses_the_actor_as_the_concerned_entity(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(_interactions_url(f), json=_pick_lock_body(f))
    assert response.status_code == 201, response.text
    interaction_id = uuid.UUID(response.json()["interaction_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT actor_user_id, entity_id, world_id, event_id, ca.code AS change_action_code
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.record_id = :i AND cl.command_name = :c
            """),
            {"i": interaction_id, "c": _PERFORM_INTERACTION_COMMAND},
        ).one()
    assert row.actor_user_id == f.gm_user_id
    assert row.entity_id == f.actor_id
    assert row.world_id == f.world_id
    assert row.event_id is None
    assert row.change_action_code == "created"


# ---------------------------------------------------------------------------
# resolve_check
# ---------------------------------------------------------------------------


def _perform_pick_lock_directly(postgres_engine: Engine, f: Fixture) -> uuid.UUID:
    """Bypasses the API to create the interaction/check_request directly
    against the command layer — used by tests below that need a
    check_request_id to resolve without also re-proving perform_interaction
    itself (already covered above)."""
    result = perform_interaction(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        actor_entity_id=f.actor_id,
        interaction_type_code="pick_lock",
        campaign_id=f.campaign_id,
        targets=(TargetSpec(target_area_connection_id=f.connection_id),),
        check_requests=(
            CheckRequestSpec(
                check_kind="skill_check", difficulty=15, skill_id=f.skill_id, target_index=0
            ),
        ),
    )
    return result.check_request_ids[0]


def test_resolving_a_successful_check_opens_the_route(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    check_request_id = _perform_pick_lock_directly(postgres_engine, f)

    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resolve_url(f.campaign_id, check_request_id),
            json={"degree_of_success": "success", "roll": 18, "total_modifier": 2, "total": 20},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["area_connection_opened"] is True
    event_id = uuid.UUID(body["event_id"])

    with postgres_engine.connect() as verify:
        status_code = verify.execute(
            text("""
                SELECT cs.code FROM campaign.area_connection_state acs
                JOIN campaign.connection_statuses cs
                    ON cs.connection_status_id = acs.connection_status_id
                WHERE acs.timeline_id = :t AND acs.area_connection_id = :c
            """),
            {"t": f.timeline_id, "c": f.connection_id},
        ).scalar_one()
        assert status_code == "open"

        event_row = verify.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :e"), {"e": event_id}
        ).one()
        assert event_row.campaign_id == f.campaign_id


def test_a_check_request_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    check_request_id = _perform_pick_lock_directly(postgres_engine, f)

    # f.gm_user_id also has canon.edit in f.other_campaign_id, so this
    # proves the campaign-ownership check itself, not merely access control.
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resolve_url(f.other_campaign_id, check_request_id),
            json={"degree_of_success": "success", "total": 20},
        )
    assert response.status_code == 404

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("SELECT count(*) FROM interaction.check_results WHERE check_request_id = :r"),
            {"r": check_request_id},
        ).scalar_one()
    assert count == 0


def test_resolving_a_check_against_an_already_terminal_interaction_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    check_request_id = _perform_pick_lock_directly(postgres_engine, f)
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE interaction.interactions SET status = 'cancelled'
                WHERE interaction_id = (
                    SELECT i.interaction_id FROM interaction.check_requests cr
                    JOIN interaction.actions a ON a.action_id = cr.action_id
                    JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
                    WHERE cr.check_request_id = :r
                )
            """),
            {"r": check_request_id},
        )

    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resolve_url(f.campaign_id, check_request_id),
            json={"degree_of_success": "success", "total": 20},
        )
    assert response.status_code == 409


def test_the_resolve_audit_row_uses_the_actor_as_the_concerned_entity(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    check_request_id = _perform_pick_lock_directly(postgres_engine, f)

    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resolve_url(f.campaign_id, check_request_id),
            json={"degree_of_success": "success", "total": 20},
        )
    assert response.status_code == 201, response.text
    check_result_id = uuid.UUID(response.json()["check_result_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT actor_user_id, entity_id, world_id
                FROM audit.change_log
                WHERE record_id = :r AND command_name = :c
            """),
            {"r": check_result_id, "c": _RESOLVE_CHECK_COMMAND},
        ).one()
    assert row.actor_user_id == f.gm_user_id
    assert row.entity_id == f.actor_id
    assert row.world_id == f.world_id


# ---------------------------------------------------------------------------
# Idempotency (dnd_ai.api.idempotency, security.idempotent_requests)
# ---------------------------------------------------------------------------


def test_a_sequential_replay_of_resolve_check_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    check_request_id = _perform_pick_lock_directly(postgres_engine, f)
    key = f"replay-{uuid.uuid4().hex[:8]}"
    body = {"degree_of_success": "success", "total": 20}

    with client_factory(f.gm_user_id) as client:
        first = client.post(
            _resolve_url(f.campaign_id, check_request_id),
            json=body,
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            _resolve_url(f.campaign_id, check_request_id),
            json=body,
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("SELECT count(*) FROM interaction.check_results WHERE check_request_id = :r"),
            {"r": check_request_id},
        ).scalar_one()
    assert count == 1


# ---------------------------------------------------------------------------
# resolve_check — hazard trigger/disarm, discovery (workstream 26)
# ---------------------------------------------------------------------------


def _perform_hazard_check_directly(postgres_engine: Engine, f: Fixture) -> uuid.UUID:
    result = perform_interaction(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        actor_entity_id=f.actor_id,
        interaction_type_code="disarm_trap",
        campaign_id=f.campaign_id,
        targets=(TargetSpec(target_area_hazard_id=f.hazard_id),),
        check_requests=(
            CheckRequestSpec(
                check_kind="skill_check", difficulty=15, skill_id=f.skill_id, target_index=0
            ),
        ),
    )
    return result.check_request_ids[0]


def test_resolving_a_disarm_check_updates_the_hazard(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    check_request_id = _perform_hazard_check_directly(postgres_engine, f)

    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resolve_url(f.campaign_id, check_request_id),
            json={"degree_of_success": "success", "roll": 18, "total_modifier": 2, "total": 20},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["hazard_status_code"] == "disarmed"

    with postgres_engine.connect() as verify:
        status_code = verify.execute(
            text("""
                SELECT hs.code FROM campaign.hazard_state hst
                JOIN campaign.hazard_statuses hs ON hs.hazard_status_id = hst.hazard_status_id
                WHERE hst.timeline_id = :t AND hst.area_hazard_id = :h
            """),
            {"t": f.timeline_id, "h": f.hazard_id},
        ).scalar_one()
        assert status_code == "disarmed"


def test_resolving_a_search_check_with_a_party_id_records_a_discovery(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    result = perform_interaction(
        postgres_engine,
        timeline_id=f.timeline_id,
        world_time_id=f.world_time_id,
        actor_entity_id=f.actor_id,
        interaction_type_code="search",
        campaign_id=f.campaign_id,
        targets=(TargetSpec(target_area_hazard_id=f.hazard_id),),
        check_requests=(
            CheckRequestSpec(
                check_kind="skill_check", difficulty=15, skill_id=f.skill_id, target_index=0
            ),
        ),
    )
    check_request_id = result.check_request_ids[0]

    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resolve_url(f.campaign_id, check_request_id),
            json={
                "degree_of_success": "success",
                "roll": 18,
                "total_modifier": 2,
                "total": 20,
                "party_id": str(f.party_id),
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["discovered_knowledge_item_id"] == str(f.hazard_knowledge_item_id)
    assert body["discovery_event_id"] is not None

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT party_id FROM knowledge.party_discoveries
                WHERE knowledge_item_id = :k
            """),
            {"k": f.hazard_knowledge_item_id},
        ).one()
        assert row.party_id == f.party_id
