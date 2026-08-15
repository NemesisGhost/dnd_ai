"""Tests for `dnd_ai.api.events` — Phase 10 workstream 9's command endpoint
over `dnd_ai.commands.events.record_event` (docs/PLAN.md Phase 10 "command
endpoints over the existing command/application services", the last
remaining "interactions/events" domain the Phase 10 progress note names).
Mirrors `tests/database/test_api_quests.py`'s shape: `get_authenticated_
user_id` is overridden directly (the OIDC verification chain itself is
already fully covered by `tests/database/test_api_auth.py`) since these
tests exercise campaign-capability enforcement and the event command's own
HTTP wiring, not token verification.
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
    make_membership_role,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

# Mirrors dnd_ai.api.events._RECORD_EVENT_COMMAND_NAME — duplicated here
# deliberately (tests assert on the public audit.change_log contract, not
# by importing the module's private constants).
_RECORD_EVENT_COMMAND = "record_event"


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

        self.gm_user_id = make_user(connection, "Event API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, role_id)

        self.capless_user_id = make_user(connection, "Event API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Event API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"event-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
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


def _events_url(f: Fixture) -> str:
    return f"/campaigns/{f.campaign_id}/events"


def _minimal_body(f: Fixture) -> dict[str, object]:
    return {
        "world_time_id": str(f.world_time_id),
        "event_type_code": "other",
        "name": "A quiet arrival",
    }


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(_events_url(f), json=_minimal_body(f))
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(_events_url(f), json=_minimal_body(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# record_event
# ---------------------------------------------------------------------------


def test_recording_an_event_creates_the_entity_and_events_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _events_url(f),
            json={
                "world_time_id": str(f.world_time_id),
                "event_type_code": "other",
                "name": "Rin acts",
                "details": "The party enters the ruin.",
                "session_id": str(f.session_id),
                "participants": [{"entity_id": str(f.actor_id), "role_code": "actor"}],
            },
        )
    assert response.status_code == 201, response.text
    event_id = uuid.UUID(response.json()["event_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT e.canonical_name, e.world_id, ev.timeline_id, ev.campaign_id,
                       ev.session_id
                FROM core.entities e
                JOIN narrative.events ev ON ev.event_id = e.entity_id
                WHERE e.entity_id = :id
            """),
            {"id": event_id},
        ).one()
        assert row.canonical_name == "Rin acts"
        assert row.world_id == f.world_id
        assert row.timeline_id == f.timeline_id
        assert row.campaign_id == f.campaign_id
        assert row.session_id == f.session_id

        participant_role = verify.execute(
            text("""
                SELECT r.code FROM narrative.event_participants p
                JOIN narrative.event_participant_roles r
                    ON r.event_participant_role_id = p.participant_role_id
                WHERE p.event_id = :e AND p.participant_entity_id = :actor
            """),
            {"e": event_id, "actor": f.actor_id},
        ).scalar()
        assert participant_role == "actor"


def test_a_session_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _events_url(f),
            json={**_minimal_body(f), "session_id": str(f.other_session_id)},
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Auditing (dnd_ai.api.audit, audit.change_log)
# ---------------------------------------------------------------------------


def test_the_audit_row_identifies_the_event_as_its_own_entity(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    correlation_id = str(uuid.uuid4())
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _events_url(f),
            json=_minimal_body(f),
            headers={"X-Correlation-Id": correlation_id},
        )
    assert response.status_code == 201, response.text
    event_id = uuid.UUID(response.json()["event_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT actor_user_id, correlation_id, command_name, event_id, entity_id, world_id,
                       ca.code AS change_action_code
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.event_id = :e AND cl.command_name = :c
            """),
            {"e": event_id, "c": _RECORD_EVENT_COMMAND},
        ).one()
    assert row.actor_user_id == f.gm_user_id
    assert row.correlation_id == uuid.UUID(correlation_id)
    assert row.event_id == event_id
    # narrative.events rows are core.entities rows (class-table
    # inheritance) — entity_id is the event_id directly.
    assert row.entity_id == event_id
    assert row.world_id == f.world_id
    assert row.change_action_code == "created"


# ---------------------------------------------------------------------------
# Idempotency (dnd_ai.api.idempotency, security.idempotent_requests)
# ---------------------------------------------------------------------------


def _event_count(postgres_engine: Engine, event_id: uuid.UUID) -> int:
    with postgres_engine.connect() as verify:
        return verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE event_id = :e"),
            {"e": event_id},
        ).scalar_one()


def test_a_sequential_replay_returns_the_original_response_with_no_new_event(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"replay-{uuid.uuid4().hex[:8]}"
    body = _minimal_body(f)
    with client_factory(f.gm_user_id) as client:
        first = client.post(_events_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_events_url(f), json=body, headers={"Idempotency-Key": key})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    event_id = uuid.UUID(first.json()["event_id"])
    assert _event_count(postgres_engine, event_id) == 1


def test_same_key_with_a_different_payload_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"mismatch-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        first = client.post(_events_url(f), json=_minimal_body(f), headers={"Idempotency-Key": key})
        second = client.post(
            _events_url(f),
            json={**_minimal_body(f), "name": "A different name"},
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
