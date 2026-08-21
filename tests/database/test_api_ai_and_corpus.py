"""API-layer smoke coverage for `dnd_ai.api.reference_corpus`,
`dnd_ai.api.ai_npc`, and `dnd_ai.api.ai_synthesis` (docs/PLAN.md Phase 12).

Deep behavioral correctness (audience filtering, proposal safety, corpus
edition/house-rule precedence, ...) is already covered at the command layer
(`tests/database/test_reference_corpus.py`, `.test_knowledge_reveal.py`,
`.test_ai_npc.py`, `.test_ai_synthesis.py`). This file only proves the HTTP
wiring itself: each route's capability gate actually gates, and a minimal
authorized request reaches the underlying command and gets a 2xx response —
the same "wiring, not re-proof" scope `tests/database/test_api_quests.py`'s
own docstring establishes for its domain.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.ai_npc import _resolve_provider
from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.domain.ai_provider import FakeAiProvider
from tests.factories import (
    cleanup_committed_ai_world,
    lookup_id,
    make_agent,
    make_agent_assignment,
    make_campaign,
    make_campaign_membership,
    make_campaign_party,
    make_character,
    make_membership_role,
    make_party,
    make_party_membership,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection,
            self.timeline_id,
            ruleset_version_id=self.ruleset_version_id,
            lifecycle_status_code="pending",
        )

        self.pc_id = make_character(connection, self.world_id, name="Hero")
        self.npc_id = make_character(connection, self.world_id, name="Innkeeper")
        self.party_id = make_party(connection, self.world_id)
        make_campaign_party(connection, self.campaign_id, self.party_id)
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.pc_id, self.world_time_id
        )

        self.agent_id = make_agent(connection)
        self.assignment_id = make_agent_assignment(
            connection, self.agent_id, self.campaign_id, self.npc_id
        )

        capability_codes = (
            "canon.edit",
            "rules_source.manage",
            "character.interact",
            "campaign.view",
        )
        capability_ids = {
            code: lookup_id(connection, "security", "capabilities", "capability_id", code)
            for code in capability_codes
        }

        self.gm_user_id = make_user(connection, "Corpus API GM")
        gm_membership_id = make_campaign_membership(connection, self.campaign_id, self.gm_user_id)
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        for capability_id in capability_ids.values():
            make_role_capability(connection, gm_role_id, capability_id)
        make_membership_role(connection, gm_membership_id, gm_role_id)

        self.viewer_user_id = make_user(connection, "Corpus API Viewer")
        viewer_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.viewer_user_id
        )
        viewer_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"viewer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, viewer_role_id, capability_ids["campaign.view"])
        make_membership_role(connection, viewer_membership_id, viewer_role_id)

        self.capless_user_id = make_user(connection, "Corpus API Capless")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Corpus API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"corpus-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id = :c
                )
            """),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.roles WHERE campaign_id = :c"), {"c": fixture.campaign_id}
        )
        cleanup.execute(
            text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": fixture.campaign_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.viewer_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                ]
            },
        )
        # The rest — core.entities, campaign.campaigns/.timelines/.
        # parties/.party_memberships/.campaign_parties, ai.*, core.worlds
        # — is the shared teardown every committed ai.* fixture needs;
        # see cleanup_committed_ai_world's own docstring for the full
        # explanation (still under the replica mode set above — this
        # fixture's own security.* rows deleted above are already
        # explicit, since cleanup_committed_ai_world doesn't touch that
        # schema at all).
        cleanup_committed_ai_world(
            cleanup,
            world_id=fixture.world_id,
            campaign_id=fixture.campaign_id,
            agent_id=fixture.agent_id,
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        app.dependency_overrides[_resolve_provider] = lambda: FakeAiProvider(
            dialogue="Welcome, traveler.", reveal_first_candidate=False
        )
        return TestClient(app, raise_server_exceptions=False)

    return _make


# ---------------------------------------------------------------------------
# dnd_ai.api.reference_corpus
# ---------------------------------------------------------------------------


def _register_source_body(f: Fixture) -> dict[str, object]:
    return {
        "source_type_code": "rulebook",
        "ruleset_version_id": str(f.ruleset_version_id),
        "title": "Test SRD",
        "classification": "srd",
        "file_hash": uuid.uuid4().hex,
        "source_version_label": "v1",
        "visibility": "general",
    }


def test_register_source_document_gm_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/reference-corpus/sources", json=_register_source_body(f)
        )
    assert response.status_code == 201
    assert uuid.UUID(response.json()["source_document_id"])


def test_register_source_document_capless_member_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/reference-corpus/sources", json=_register_source_body(f)
        )
    assert response.status_code == 403


def test_register_source_document_outsider_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/reference-corpus/sources", json=_register_source_body(f)
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# dnd_ai.api.ai_npc
# ---------------------------------------------------------------------------


def test_npc_conversation_own_character_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/npc-conversation",
            json={
                "agent_assignment_id": str(f.assignment_id),
                "requesting_character_id": str(f.pc_id),
                "requesting_party_id": str(f.party_id),
                "player_message": "Hello!",
                "world_time_id": str(f.world_time_id),
            },
        )
    assert response.status_code == 200
    assert response.json()["dialogue"] == "Welcome, traveler."


def test_npc_conversation_capless_member_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/npc-conversation",
            json={
                "agent_assignment_id": str(f.assignment_id),
                "requesting_character_id": str(f.pc_id),
                "requesting_party_id": str(f.party_id),
                "player_message": "Hello!",
                "world_time_id": str(f.world_time_id),
            },
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# dnd_ai.api.ai_synthesis
# ---------------------------------------------------------------------------


def test_observer_summary_viewer_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.viewer_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/synthesis",
            json={
                "agent_assignment_id": str(f.assignment_id),
                "audience_tier": "observer_summary",
                "question_text": "What's new?",
            },
        )
    assert response.status_code == 200


def test_gm_brief_viewer_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.viewer_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/synthesis",
            json={
                "agent_assignment_id": str(f.assignment_id),
                "audience_tier": "gm_brief",
                "question_text": "What's new?",
            },
        )
    assert response.status_code == 403


def test_gm_brief_gm_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            f"/campaigns/{f.campaign_id}/ai/synthesis",
            json={
                "agent_assignment_id": str(f.assignment_id),
                "audience_tier": "gm_brief",
                "question_text": "What's new?",
            },
        )
    assert response.status_code == 200
