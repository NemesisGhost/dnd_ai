"""Tests for `dnd_ai.api.campaigns` — the campaign-creation bootstrap
command endpoint (docs/PLAN.md Phase 10 "Still to come" list).

Covers: any authenticated user may create a campaign (no pre-existing
membership needed, unlike every other command endpoint), the created
campaign's own retained-access-manager invariant (proven indirectly: a
201 response is only possible once `tr_campaigns_retain_access_manager`'s
deferred check passes at commit), a nonexistent timeline, a nonexistent
ruleset version, and a ruleset version belonging to a different world's
ruleset family.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import make_ruleset_version_for_world, make_timeline, make_user, make_world

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)

        other_world_id = make_world(connection, slug=f"{slug}-other")
        self.foreign_ruleset_version_id = make_ruleset_version_for_world(connection, other_world_id)
        self.other_world_id = other_world_id

        self.creator_user_id = make_user(connection, "Campaign API Creator")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"campaign-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
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
            text("DELETE FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                UPDATE core.worlds SET default_ruleset_id = NULL
                WHERE world_id IN (:w, :other)
            """),
            {"w": fixture.world_id, "other": fixture.other_world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM rules.world_rulesets WHERE world_id IN (:w, :other)
            """),
            {"w": fixture.world_id, "other": fixture.other_world_id},
        )
        ruleset_ids = (
            cleanup.execute(
                text(
                    "SELECT ruleset_id FROM rules.ruleset_versions "
                    "WHERE ruleset_version_id IN (:r, :foreign)"
                ),
                {"r": fixture.ruleset_version_id, "foreign": fixture.foreign_ruleset_version_id},
            )
            .scalars()
            .all()
        )
        cleanup.execute(
            text("DELETE FROM rules.ruleset_versions WHERE ruleset_id = ANY(:rulesets)"),
            {"rulesets": ruleset_ids},
        )
        cleanup.execute(
            text("DELETE FROM rules.rulesets WHERE ruleset_id = ANY(:rulesets)"),
            {"rulesets": ruleset_ids},
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id IN (:w, :other)"),
            {"w": fixture.world_id, "other": fixture.other_world_id},
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id IN (:w, :other)"),
            {"w": fixture.world_id, "other": fixture.other_world_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"),
            {"u": fixture.creator_user_id},
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _body(f: Fixture, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "timeline_id": str(f.timeline_id),
        "ruleset_version_id": str(f.ruleset_version_id),
        "name": "New Campaign",
    }
    body.update(overrides)
    return body


def test_any_authenticated_user_can_create_a_campaign(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.creator_user_id) as client:
        response = client.post("/campaigns", json=_body(f))
    assert response.status_code == 201, response.text
    payload = response.json()
    campaign_id = uuid.UUID(payload["campaign_id"])
    campaign_membership_id = uuid.UUID(payload["campaign_membership_id"])

    with postgres_engine.connect() as verify:
        campaign_row = verify.execute(
            text("""
                SELECT c.timeline_id, c.name, c.ruleset_version_id, ls.code AS status_code
                FROM campaign.campaigns c
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
                WHERE c.campaign_id = :c
            """),
            {"c": campaign_id},
        ).one()
        assert campaign_row.timeline_id == f.timeline_id
        assert campaign_row.name == "New Campaign"
        assert campaign_row.ruleset_version_id == f.ruleset_version_id
        assert campaign_row.status_code == "active"

        membership_row = verify.execute(
            text("""
                SELECT cm.user_id, cm.campaign_id, ms.code AS status_code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": campaign_membership_id},
        ).one()
        assert membership_row.user_id == f.creator_user_id
        assert membership_row.campaign_id == campaign_id
        assert membership_row.status_code == "active"

        role_row = verify.execute(
            text("""
                SELECT r.code, mr.granted_by_membership_id, mr.revoked_at
                FROM security.membership_roles mr
                JOIN security.roles r ON r.role_id = mr.role_id
                WHERE mr.campaign_membership_id = :m
            """),
            {"m": campaign_membership_id},
        ).one()
        assert role_row.code == "campaign_owner"
        assert role_row.granted_by_membership_id is None
        assert role_row.revoked_at is None

        audit_row = verify.execute(
            text("""
                SELECT schema_name, table_name, record_id, entity_id, world_id, actor_user_id
                FROM audit.change_log
                WHERE schema_name = 'campaign' AND table_name = 'campaigns' AND record_id = :c
            """),
            {"c": campaign_id},
        ).one()
        assert audit_row.entity_id is None
        assert audit_row.world_id == f.world_id
        assert audit_row.actor_user_id == f.creator_user_id


def test_creating_a_campaign_with_a_nonexistent_timeline_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.creator_user_id) as client:
        response = client.post("/campaigns", json=_body(f, timeline_id=str(uuid.uuid4())))
    assert response.status_code == 400, response.text


def test_creating_a_campaign_with_a_nonexistent_ruleset_version_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.creator_user_id) as client:
        response = client.post("/campaigns", json=_body(f, ruleset_version_id=str(uuid.uuid4())))
    assert response.status_code == 400, response.text


def test_creating_a_campaign_with_a_disallowed_ruleset_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.creator_user_id) as client:
        response = client.post(
            "/campaigns",
            json=_body(f, ruleset_version_id=str(f.foreign_ruleset_version_id)),
        )
    assert response.status_code == 400, response.text
