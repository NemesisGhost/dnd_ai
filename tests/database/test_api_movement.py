"""Tests for `dnd_ai.api.movement` — `enter_location` (docs/PLAN.md §25
step 7, "Move the party into the dungeon"), the write path no earlier
phase built (see `dnd_ai.commands.movement`'s own module docstring).

Covers: access control (non-member 404, capless-member 403), a successful
move (history row created, audit row recorded), the same-location no-op
(no new event, no audit row), idempotent replay of a genuine move, and a
foreign-world location rejected.
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
    make_dungeon,
    make_dungeon_area,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database

_ENTER_LOCATION_COMMAND = "enter_location"


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_1 = make_world_time(connection, self.world_id, 100)
        self.world_time_2 = make_world_time(connection, self.world_id, 200)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Vault")

        self.other_world_id = make_world(connection, slug=f"{slug}-other")
        self.foreign_location_id = make_dungeon(connection, self.other_world_id)

        self.actor_id = make_character(connection, self.world_id, name="Rin")

        self.gm_user_id = make_user(connection, "Movement API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, role_id)

        self.capless_user_id = make_user(connection, "Movement API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Movement API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"movement-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM campaign.character_location_history WHERE timeline_id = :t"),
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
                "DELETE FROM security.idempotent_requests WHERE campaign_id IN "
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
        for world_id in (fixture.world_id, fixture.other_world_id):
            cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
            cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _location_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/characters/{f.actor_id}/location"


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _location_url(f),
            json={"world_time_id": str(f.world_time_1), "location_id": str(f.area_a)},
        )
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            _location_url(f),
            json={"world_time_id": str(f.world_time_1), "location_id": str(f.area_a)},
        )
    assert response.status_code == 403


def test_entering_a_location_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _location_url(f),
            json={"world_time_id": str(f.world_time_1), "location_id": str(f.area_a)},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["moved"] is True
    history_id = uuid.UUID(body["character_location_history_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT location_id, departed_at_world_time_id "
                "FROM campaign.character_location_history WHERE character_location_history_id = :h"
            ),
            {"h": history_id},
        ).one()
        assert row.location_id == f.area_a
        assert row.departed_at_world_time_id is None

        audit_row = verify.execute(
            text("""
                SELECT actor_user_id, entity_id, world_id
                FROM audit.change_log
                WHERE record_id = :h AND command_name = :c
            """),
            {"h": history_id, "c": _ENTER_LOCATION_COMMAND},
        ).one()
        assert audit_row.actor_user_id == f.gm_user_id
        assert audit_row.entity_id == f.actor_id
        assert audit_row.world_id == f.world_id


def test_entering_the_same_location_again_is_a_no_op_with_no_audit_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        first = client.post(
            _location_url(f),
            json={"world_time_id": str(f.world_time_1), "location_id": str(f.area_a)},
        )
        second = client.post(
            _location_url(f),
            json={"world_time_id": str(f.world_time_2), "location_id": str(f.area_a)},
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["moved"] is False
    assert second.json()["event_id"] is None
    history_id = uuid.UUID(first.json()["character_location_history_id"])

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log WHERE command_name = :c AND record_id = :h"
            ),
            {"c": _ENTER_LOCATION_COMMAND, "h": history_id},
        ).scalar_one()
        assert count == 1


def test_entering_a_foreign_world_location_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _location_url(f),
            json={
                "world_time_id": str(f.world_time_1),
                "location_id": str(f.foreign_location_id),
            },
        )
    assert response.status_code == 404, response.text


def test_a_sequential_replay_of_a_move_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"move-{uuid.uuid4().hex[:8]}"
    body = {"world_time_id": str(f.world_time_1), "location_id": str(f.area_a)}
    with client_factory(f.gm_user_id) as client:
        first = client.post(_location_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_location_url(f), json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM campaign.character_location_history "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"t": f.timeline_id, "c": f.actor_id},
        ).scalar_one()
        assert count == 1
