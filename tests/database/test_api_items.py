"""Tests for `dnd_ai.api.items` — Phase 10 workstream 6's command endpoints
over `dnd_ai.commands.items` (docs/PLAN.md Phase 10 "command endpoints over
the existing command/application services"). Mirrors
`tests/database/test_api_encounters.py`'s shape: `get_authenticated_user_id`
is overridden directly (the OIDC verification chain itself is already fully
covered by `tests/database/test_api_auth.py`) since these tests exercise
campaign-capability enforcement and the item commands' own HTTP wiring, not
token verification.
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
    make_item_definition,
    make_item_instance,
    make_location,
    make_membership_role,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_session,
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
        ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant (revision 080) — these tests grant canon.edit, not
        # access.manage, and don't otherwise care about campaign lifecycle.
        self.campaign_id = make_campaign(
            connection,
            self.timeline_id,
            ruleset_version_id=ruleset_version_id,
            lifecycle_status_code="pending",
        )
        self.session_id = make_session(connection, self.campaign_id, 1)

        # A second campaign/session on the same world/timeline, used only to
        # exercise SessionNotInCampaignError (a real session belonging to a
        # different campaign than the one named in the URL).
        self.other_campaign_id = make_campaign(
            connection,
            self.timeline_id,
            "Other Campaign",
            ruleset_version_id=ruleset_version_id,
            lifecycle_status_code="pending",
        )
        self.other_session_id = make_session(connection, self.other_campaign_id, 1)

        self.actor_id = make_character(connection, self.world_id, name="Rin")
        self.holder_id = make_character(connection, self.world_id, name="Borrin")
        self.location_id = make_location(connection, self.world_id)
        item_definition_id = make_item_definition(connection, ruleset_version_id)
        self.item_instance_id = make_item_instance(connection, self.world_id, item_definition_id)

        self.gm_user_id = make_user(connection, "Item API GM")
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
        self.capless_user_id = make_user(connection, "Item API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Item API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"item-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_encounters.py's identical cleanup
        # comment: session_replication_role = replica disables the cascade
        # DELETE FROM core.worlds below would otherwise apply to
        # campaign.campaigns/.sessions and security.roles/.role_
        # capabilities/.campaign_memberships/.membership_roles, and revision
        # 080's DEFERRABLE constraint triggers on several of those tables
        # can fail a later, unrelated test in the same pytest session if
        # they're left behind. Deleted explicitly here, in dependency
        # order, scoped by timeline_id to catch both campaigns this
        # fixture created.
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


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={"world_time_id": str(f.world_time_id), "holder_entity_id": str(f.holder_id)},
        )
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={"world_time_id": str(f.world_time_id), "holder_entity_id": str(f.holder_id)},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# transfer_item_possession
# ---------------------------------------------------------------------------


def test_transferring_possession_updates_the_inventory_entry(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={
                "world_time_id": str(f.world_time_id),
                "holder_entity_id": str(f.holder_id),
                "actor_entity_id": str(f.actor_id),
                "session_id": str(f.session_id),
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    event_id = uuid.UUID(body["event_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT holder_entity_id FROM campaign.inventory_entries
                WHERE timeline_id = :t AND item_instance_id = :i
            """),
            {"t": f.timeline_id, "i": f.item_instance_id},
        ).one()
        assert row.holder_entity_id == f.holder_id

        event_row = verify.execute(
            text("SELECT campaign_id, session_id FROM narrative.events WHERE event_id = :e"),
            {"e": event_id},
        ).one()
        assert event_row.campaign_id == f.campaign_id
        assert event_row.session_id == f.session_id


def test_a_session_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/transfer",
            json={
                "world_time_id": str(f.world_time_id),
                "holder_entity_id": str(f.holder_id),
                "session_id": str(f.other_session_id),
            },
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# identify_item
# ---------------------------------------------------------------------------


def test_identifying_an_item_updates_the_knowers_identification(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/identify",
            json={
                "world_time_id": str(f.world_time_id),
                "knower_entity_id": str(f.holder_id),
                "new_level": "fully_identified",
                "known_properties": {"bonus": "+1"},
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_level"] is None
    assert body["new_level"] == "fully_identified"

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT identification_level, known_properties_jsonb
                FROM knowledge.item_identification
                WHERE timeline_id = :t AND item_instance_id = :i AND knower_entity_id = :k
            """),
            {"t": f.timeline_id, "i": f.item_instance_id, "k": f.holder_id},
        ).one()
        assert row.identification_level == "fully_identified"
        assert row.known_properties_jsonb == {"bonus": "+1"}


def test_identifying_with_an_invalid_level_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/items/{f.item_instance_id}/identify",
            json={
                "world_time_id": str(f.world_time_id),
                "knower_entity_id": str(f.holder_id),
                "new_level": "not_a_real_level",
            },
        )
    assert response.status_code == 400
