"""Tests for `dnd_ai.api.character_state` — Phase 11 workstream 6's
non-combat character-state endpoints (`adjust_hit_points`,
`apply_character_condition`, `remove_character_condition`,
`adjust_character_resource`). Mirrors `tests/database/
test_api_encounters.py`'s shape: `get_authenticated_user_id` is
overridden directly, since these tests exercise campaign-capability
enforcement and the commands' own HTTP wiring, not token verification.
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
    make_character_condition,
    make_character_resource,
    make_character_state,
    make_condition,
    make_membership_role,
    make_resource_definition,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
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
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.character_id = make_character(connection, self.world_id, name="Aria")
        make_character_state(
            connection,
            self.timeline_id,
            self.character_id,
            current_hit_points=10,
            maximum_hit_points=20,
        )

        self.poisoned_condition_id = make_condition(
            connection, self.ruleset_version_id, code="poisoned"
        )
        self.stunned_condition_id = make_condition(
            connection, self.ruleset_version_id, code="stunned"
        )
        self.ki_resource_definition_id = make_resource_definition(
            connection, self.ruleset_version_id, code="ki_points"
        )
        make_character_resource(
            connection,
            self.timeline_id,
            self.character_id,
            self.ki_resource_definition_id,
            current_amount=2,
            maximum_amount=4,
        )

        # A second, unrelated world/campaign — proves cross-world rejection.
        self.other_world_id = make_world(connection, slug=f"{slug}-other")
        other_timeline_id = make_timeline(connection, self.other_world_id, is_primary=True)
        self.other_campaign_id = make_campaign(
            connection, other_timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        self.gm_user_id = make_user(connection, "Character State API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, role_id)

        other_gm_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.gm_user_id
        )
        other_role_id = make_role(
            connection, campaign_id=self.other_campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, other_role_id, canon_edit_id)
        make_membership_role(connection, other_gm_membership_id, other_role_id)

        self.capless_user_id = make_user(connection, "Character State API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Character State API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"character-state-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns
                        WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines
                            WHERE world_id = ANY(:worlds)
                        )
                    )
                )
            """),
            {"worlds": [fixture.world_id, fixture.other_world_id]},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns
                        WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines
                            WHERE world_id = ANY(:worlds)
                        )
                    )
                )
            """),
            {"worlds": [fixture.world_id, fixture.other_world_id]},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns
                    WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds)
                    )
                )
            """),
            {"worlds": [fixture.world_id, fixture.other_world_id]},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns
                    WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds)
                    )
                )
            """),
            {"worlds": [fixture.world_id, fixture.other_world_id]},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.idempotent_requests WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns
                    WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds)
                    )
                )
            """),
            {"worlds": [fixture.world_id, fixture.other_world_id]},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.campaigns WHERE timeline_id IN (
                    SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds)
                )
            """),
            {"worlds": [fixture.world_id, fixture.other_world_id]},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {"users": [fixture.gm_user_id, fixture.capless_user_id, fixture.outsider_user_id]},
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = ANY(:worlds)"),
            {"worlds": [fixture.world_id, fixture.other_world_id]},
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = ANY(:worlds)"),
            {"worlds": [fixture.world_id, fixture.other_world_id]},
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _hp_url(campaign_id: uuid.UUID, character_id: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/characters/{character_id}/hit-points"


def _conditions_url(campaign_id: uuid.UUID, character_id: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/characters/{character_id}/conditions"


def _remove_condition_url(
    campaign_id: uuid.UUID, character_id: uuid.UUID, condition_id: uuid.UUID
) -> str:
    return f"/campaigns/{campaign_id}/characters/{character_id}/conditions/{condition_id}/remove"


def _resources_url(campaign_id: uuid.UUID, character_id: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/characters/{character_id}/resources"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _hp_url(f.campaign_id, f.character_id),
            json={"world_time_id": str(f.world_time_id), "delta": 5},
        )
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            _hp_url(f.campaign_id, f.character_id),
            json={"world_time_id": str(f.world_time_id), "delta": 5},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# adjust_hit_points
# ---------------------------------------------------------------------------


def test_healing_increases_hit_points(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _hp_url(f.campaign_id, f.character_id),
            json={"world_time_id": str(f.world_time_id), "delta": 6},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_hit_points"] == 10
    assert body["new_hit_points"] == 16
    assert body["changed"] is True
    assert body["event_id"] is not None

    with postgres_engine.connect() as verify:
        hp = verify.execute(
            text(
                "SELECT current_hit_points FROM campaign.character_state "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"t": f.timeline_id, "c": f.character_id},
        ).scalar()
    assert hp == 16


def test_healing_is_clamped_to_maximum_hit_points(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _hp_url(f.campaign_id, f.character_id),
            json={"world_time_id": str(f.world_time_id), "delta": 1000},
        )
    assert response.status_code == 200, response.text
    assert response.json()["new_hit_points"] == 20


def test_non_combat_damage_is_clamped_to_zero(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _hp_url(f.campaign_id, f.character_id),
            json={"world_time_id": str(f.world_time_id), "delta": -1000},
        )
    assert response.status_code == 200, response.text
    assert response.json()["new_hit_points"] == 0


def test_healing_a_character_already_at_maximum_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        first = client.post(
            _hp_url(f.campaign_id, f.character_id),
            json={"world_time_id": str(f.world_time_id), "delta": 1000},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            _hp_url(f.campaign_id, f.character_id),
            json={"world_time_id": str(f.world_time_id), "delta": 5},
        )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["changed"] is False
    assert body["event_id"] is None
    assert body["new_hit_points"] == 20


def test_a_sequential_replay_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"hp-replay-{uuid.uuid4().hex[:8]}"
    body = {"world_time_id": str(f.world_time_id), "delta": 3}
    with client_factory(f.gm_user_id) as client:
        first = client.post(
            _hp_url(f.campaign_id, f.character_id), json=body, headers={"Idempotency-Key": key}
        )
        second = client.post(
            _hp_url(f.campaign_id, f.character_id), json=body, headers={"Idempotency-Key": key}
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()

    with postgres_engine.connect() as verify:
        hp = verify.execute(
            text(
                "SELECT current_hit_points FROM campaign.character_state "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"t": f.timeline_id, "c": f.character_id},
        ).scalar()
    assert hp == 13


# ---------------------------------------------------------------------------
# apply_character_condition / remove_character_condition
# ---------------------------------------------------------------------------


def test_applying_a_condition_creates_the_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _conditions_url(f.campaign_id, f.character_id),
            json={
                "world_time_id": str(f.world_time_id),
                "condition_id": str(f.poisoned_condition_id),
                "source_description": "stepped in ooze",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["event_id"] is not None

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT source_description FROM campaign.character_conditions
                WHERE timeline_id = :t AND character_id = :c AND condition_id = :cond
            """),
            {"t": f.timeline_id, "c": f.character_id, "cond": f.poisoned_condition_id},
        ).one()
    assert row.source_description == "stepped in ooze"


def test_applying_an_already_applied_condition_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        make_character_condition(connection, f.timeline_id, f.character_id, f.stunned_condition_id)

    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _conditions_url(f.campaign_id, f.character_id),
            json={
                "world_time_id": str(f.world_time_id),
                "condition_id": str(f.stunned_condition_id),
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is False
    assert body["event_id"] is None

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("""
                SELECT count(*) FROM campaign.character_conditions
                WHERE timeline_id = :t AND character_id = :c AND condition_id = :cond
            """),
            {"t": f.timeline_id, "c": f.character_id, "cond": f.stunned_condition_id},
        ).scalar_one()
    assert count == 1


def test_removing_a_present_condition_deletes_the_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        make_character_condition(connection, f.timeline_id, f.character_id, f.poisoned_condition_id)

    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _remove_condition_url(f.campaign_id, f.character_id, f.poisoned_condition_id),
            json={"world_time_id": str(f.world_time_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["event_id"] is not None

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("""
                SELECT count(*) FROM campaign.character_conditions
                WHERE timeline_id = :t AND character_id = :c AND condition_id = :cond
            """),
            {"t": f.timeline_id, "c": f.character_id, "cond": f.poisoned_condition_id},
        ).scalar_one()
    assert count == 0


def test_removing_an_absent_condition_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _remove_condition_url(f.campaign_id, f.character_id, f.poisoned_condition_id),
            json={"world_time_id": str(f.world_time_id)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is False
    assert body["event_id"] is None


def test_a_condition_change_for_a_character_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _conditions_url(f.other_campaign_id, f.character_id),
            json={
                "world_time_id": str(f.world_time_id),
                "condition_id": str(f.poisoned_condition_id),
            },
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# adjust_character_resource
# ---------------------------------------------------------------------------


def test_spending_a_resource_decreases_the_amount(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resources_url(f.campaign_id, f.character_id),
            json={
                "world_time_id": str(f.world_time_id),
                "resource_definition_id": str(f.ki_resource_definition_id),
                "delta": -1,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_amount"] == 2
    assert body["new_amount"] == 1
    assert body["changed"] is True

    with postgres_engine.connect() as verify:
        amount = verify.execute(
            text("""
                SELECT current_amount FROM campaign.character_resources
                WHERE timeline_id = :t AND character_id = :c AND resource_definition_id = :r
            """),
            {"t": f.timeline_id, "c": f.character_id, "r": f.ki_resource_definition_id},
        ).scalar()
    assert amount == 1


def test_a_net_zero_delta_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resources_url(f.campaign_id, f.character_id),
            json={
                "world_time_id": str(f.world_time_id),
                "resource_definition_id": str(f.ki_resource_definition_id),
                "delta": 0,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is False
    assert body["event_id"] is None


def test_spending_more_than_available_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resources_url(f.campaign_id, f.character_id),
            json={
                "world_time_id": str(f.world_time_id),
                "resource_definition_id": str(f.ki_resource_definition_id),
                "delta": -100,
            },
        )
    assert response.status_code == 400, response.text

    with postgres_engine.connect() as verify:
        amount = verify.execute(
            text("""
                SELECT current_amount FROM campaign.character_resources
                WHERE timeline_id = :t AND character_id = :c AND resource_definition_id = :r
            """),
            {"t": f.timeline_id, "c": f.character_id, "r": f.ki_resource_definition_id},
        ).scalar()
    assert amount == 2


def test_restoring_past_the_maximum_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resources_url(f.campaign_id, f.character_id),
            json={
                "world_time_id": str(f.world_time_id),
                "resource_definition_id": str(f.ki_resource_definition_id),
                "delta": 100,
            },
        )
    assert response.status_code == 400, response.text


def test_adjusting_an_untracked_resource_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        untracked_resource_definition_id = make_resource_definition(
            connection, f.ruleset_version_id, code="rage_uses"
        )

    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _resources_url(f.campaign_id, f.character_id),
            json={
                "world_time_id": str(f.world_time_id),
                "resource_definition_id": str(untracked_resource_definition_id),
                "delta": -1,
            },
        )
    assert response.status_code == 404
