"""Tests for `dnd_ai.api.sessions` — `end_session` (docs/PLAN.md §25 step
14, "End the session and generate a summary"), the write half `GET
/campaigns/{campaign_id}/summary` never had (see `dnd_ai.commands.
sessions`'s own module docstring).

Covers: access control (non-member 404, capless-member 403), a successful
end (row updated, audit row recorded), ending an already-ended session as
a no-op (no audit row, prior summary untouched), and idempotent replay of
the first end call.
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

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

_END_SESSION_COMMAND = "end_session"


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.start_world_time_id = make_world_time(connection, self.world_id, 100)
        self.end_world_time_id = make_world_time(connection, self.world_id, 200)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.session_id = make_session(
            connection,
            self.campaign_id,
            1,
            start_world_time_id=self.start_world_time_id,
        )
        already_ended_started_at = datetime.now(UTC)
        self.already_ended_session_id = make_session(
            connection,
            self.campaign_id,
            2,
            start_world_time_id=self.start_world_time_id,
            end_world_time_id=self.end_world_time_id,
            started_at=already_ended_started_at,
            # ck_sessions_ended_after_started requires ended_at > started_at
            # strictly; two independent datetime.now(UTC) calls can land on
            # the same instant under a coarse system clock, so derive this
            # one from the first instead of sampling the clock again.
            ended_at=already_ended_started_at + timedelta(seconds=1),
        )

        self.gm_user_id = make_user(connection, "Session API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        make_role_capability(connection, role_id, canon_edit_id)
        make_membership_role(connection, gm_membership_id, role_id)

        self.capless_user_id = make_user(connection, "Session API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Session API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"session-api-{uuid.uuid4().hex[:8]}")
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
            text(
                "DELETE FROM campaign.sessions WHERE campaign_id IN "
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


def _end_url(f: Fixture, session_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/sessions/{session_id or f.session_id}/end"


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(_end_url(f), json={"end_world_time_id": str(f.end_world_time_id)})
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(_end_url(f), json={"end_world_time_id": str(f.end_world_time_id)})
    assert response.status_code == 403


def test_ending_a_session_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _end_url(f),
            json={"end_world_time_id": str(f.end_world_time_id), "summary": "The party rested."},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["already_ended"] is False

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text(
                "SELECT ended_at, end_world_time_id, summary FROM campaign.sessions "
                "WHERE session_id = :s"
            ),
            {"s": f.session_id},
        ).one()
        assert row.ended_at is not None
        assert row.end_world_time_id == f.end_world_time_id
        assert row.summary == "The party rested."

        audit_row = verify.execute(
            text("""
                SELECT actor_user_id, entity_id, world_id
                FROM audit.change_log
                WHERE record_id = :s AND command_name = :c
            """),
            {"s": f.session_id, "c": _END_SESSION_COMMAND},
        ).one()
        assert audit_row.actor_user_id == f.gm_user_id
        assert audit_row.entity_id is None
        assert audit_row.world_id == f.world_id


def test_ending_an_already_ended_session_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _end_url(f, f.already_ended_session_id),
            json={"end_world_time_id": str(f.end_world_time_id), "summary": "Overwritten?"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["already_ended"] is True

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log WHERE record_id = :s AND command_name = :c"
            ),
            {"s": f.already_ended_session_id, "c": _END_SESSION_COMMAND},
        ).scalar_one()
        assert count == 0


def test_a_sequential_replay_of_end_session_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"end-session-{uuid.uuid4().hex[:8]}"
    body = {"end_world_time_id": str(f.end_world_time_id)}
    with client_factory(f.gm_user_id) as client:
        first = client.post(_end_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_end_url(f), json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
