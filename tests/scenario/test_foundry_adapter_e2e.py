"""End-to-end verification for the FoundryVTT client module
(`foundry-module/`) — Phase 11 workstream 7's "reproducible Foundry test
harness," the alternative this phase's own exit criterion accepts to a
real, licensed Foundry client instance (`foundry-module/README.md`'s
"Manual live-Foundry verification" section documents the corresponding
manual procedure for whoever has one).

Drives the exact HTTP request sequence `foundry-module/scripts/
api-client.mjs`/`sync-engine.mjs` issue — real `Authorization:
FoundrySystem <id>.<key>` + `X-Foundry-Actor-Id` headers (the latter
renamed from `X-Foundry-User-Id`, and now purely descriptive metadata —
see `dnd_ai.domain.access.resolve_foundry_system_principal`'s docstring
for the second Phase 11 workstream 2 security correction this reflects),
real JSON bodies matching `foundry-module`'s own request-construction,
real `external_operation_id` reuse for the duplicate-delivery proof —
against the real FastAPI application and a real, disposable PostgreSQL 18
database (never the database directly, never a shortcut dependency
override for the parts under test), via `httpx`/`TestClient` standing in
for the browser `fetch()` a real Foundry client would use.

Proves the five claims docs/PLAN.md Phase 11's exit criterion and this
workstream's own request require:

1. A real encounter (combat-sync) and non-combat HP change update
   canonical state only through the application API.
2. Duplicate delivery (the same `external_operation_id`) creates no
   duplicate `narrative.events` row.
3. Reopening/reconnecting (`sync-state` + character reads, with no
   client-side state carried over) restores the updated state.
4. A credential authenticated for a different world's external system is
   rejected against this campaign (`ae80a29`'s world-binding correction,
   re-proven through the literal request shapes a real module sends).
5. The identical real credential cannot call the management-only routes
   (`register_external_system`/`link_foundry_identity`/`issue_foundry_
   system_key`) — the bounded adapter-facing surface `ae80a29` also
   established.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.integration import issue_foundry_system_key, link_foundry_identity
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_character_state,
    make_external_system,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.scenario


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.world_time_id = make_world_time(connection, self.world_id, 100)

        self.attacker_id = make_character(connection, self.world_id, name="Foundry Attacker")
        self.defender_id = make_character(connection, self.world_id, name="Foundry Defender")
        make_character_state(
            connection,
            self.timeline_id,
            self.defender_id,
            current_hit_points=20,
            maximum_hit_points=20,
        )

        # A second, unrelated world/campaign — proves a credential
        # authenticated for a system registered here cannot reach
        # self.campaign_id, per ae80a29's world-binding correction.
        self.other_world_id = make_world(connection, slug=f"{slug}-other")
        other_timeline_id = make_timeline(connection, self.other_world_id, is_primary=True)
        self.other_campaign_id = make_campaign(
            connection, other_timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        canon_edit_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        campaign_view_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )

        # gm_user_id holds every capability the adapter-facing routes
        # need (canon.edit, campaign.view) AND access.manage, in BOTH
        # campaigns — deliberately over-privileged on the OIDC side, so
        # claim 5 (management routes reject the Foundry credential) is a
        # real proof of the credential-scope restriction, not an
        # incidental capability gap.
        self.gm_user_id = make_user(connection, "Foundry E2E GM")
        for campaign_id in (self.campaign_id, self.other_campaign_id):
            membership_id = make_campaign_membership(connection, campaign_id, self.gm_user_id)
            role_id = make_role(
                connection, campaign_id=campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
            )
            make_role_capability(connection, role_id, canon_edit_id)
            make_role_capability(connection, role_id, campaign_view_id)
            make_role_capability(connection, role_id, access_manage_id)
            make_membership_role(connection, membership_id, role_id)


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"foundry-e2e-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        worlds = [fixture.world_id, fixture.other_world_id]
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns
                        WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds))
                    )
                )
            """),
            {"worlds": worlds},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns
                        WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds))
                    )
                )
            """),
            {"worlds": worlds},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns
                    WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds))
                )
            """),
            {"worlds": worlds},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns
                    WHERE timeline_id IN (SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds))
                )
            """),
            {"worlds": worlds},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.campaigns WHERE timeline_id IN (
                    SELECT timeline_id FROM campaign.timelines WHERE world_id = ANY(:worlds)
                )
            """),
            {"worlds": worlds},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = :u"), {"u": fixture.gm_user_id}
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = ANY(:worlds)"), {"worlds": worlds}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = ANY(:worlds)"), {"worlds": worlds}
        )


def _app_for(postgres_engine: Engine) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    return app


def _oidc_client(postgres_engine: Engine, user_id: uuid.UUID) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: postgres_engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
    return TestClient(app, raise_server_exceptions=False)


def _foundry_headers(
    external_system_id: uuid.UUID, raw_key: str, claimed_actor_id: str | None = None
) -> dict[str, str]:
    headers = {"Authorization": f"FoundrySystem {external_system_id}.{raw_key}"}
    if claimed_actor_id is not None:
        headers["X-Foundry-Actor-Id"] = claimed_actor_id
    return headers


def _provision(
    postgres_engine: Engine, *, world_id: uuid.UUID, user_id: uuid.UUID, foundry_user_id: str
) -> tuple[uuid.UUID, str]:
    """The same three steps `scripts/foundry_provision.py` performs (in
    its own corrected order: register, link-identity, issue-key — a
    credential can only be bound to an already-linked Foundry user id per
    the second Phase 11 workstream 2 correction) — called directly through
    the command layer here purely to set up fixtures faster than driving
    three more HTTP round-trips per test; the provisioning script's own
    HTTP behavior is separately covered by `tests/database/test_foundry_
    provision.py`. Everything from this point on in every test below goes
    through the real HTTP API only."""
    with postgres_engine.begin() as connection:
        external_system_id = make_external_system(connection, world_id)
    link_foundry_identity(
        postgres_engine,
        external_system_id=external_system_id,
        foundry_user_id=foundry_user_id,
        user_id=user_id,
    )
    key_result = issue_foundry_system_key(
        postgres_engine,
        external_system_id=external_system_id,
        principal_foundry_user_id=foundry_user_id,
    )
    return external_system_id, key_result.raw_key


def _start_encounter(client: TestClient, f: Fixture) -> uuid.UUID:
    response = client.post(
        f"/campaigns/{f.campaign_id}/encounters",
        json={
            "world_time_id": str(f.world_time_id),
            "participant_entity_ids": [str(f.attacker_id), str(f.defender_id)],
        },
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["encounter_id"])


def _combat_sync_body(
    f: Fixture,
    encounter_id: uuid.UUID,
    *,
    external_system_id: uuid.UUID,
    external_operation_id: str,
) -> dict[str, object]:
    return {
        "external_system_id": str(external_system_id),
        "external_operation_id": external_operation_id,
        "encounter_id": str(encounter_id),
        "round_number": 1,
        "turn_order": 0,
        "actor_entity_id": str(f.attacker_id),
        "world_time_id": str(f.world_time_id),
        "action_kind": "attack",
        "target_entity_id": str(f.defender_id),
        "hit": True,
        "damage_amount": 7,
    }


def test_claim_1_a_real_encounter_updates_canonical_state_only_through_the_api(
    postgres_engine: Engine, f: Fixture
) -> None:
    external_system_id, raw_key = _provision(
        postgres_engine, world_id=f.world_id, user_id=f.gm_user_id, foundry_user_id="foundry-gm"
    )
    headers = _foundry_headers(external_system_id, raw_key, "foundry-gm")

    with _oidc_client(postgres_engine, f.gm_user_id) as oidc_client:
        encounter_id = _start_encounter(oidc_client, f)

    with TestClient(_app_for(postgres_engine), raise_server_exceptions=False) as adapter_client:
        response = adapter_client.post(
            f"/campaigns/{f.campaign_id}/integration/foundry/combat-sync",
            json=_combat_sync_body(
                f, encounter_id, external_system_id=external_system_id, external_operation_id="op-1"
            ),
            headers=headers,
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["previous_hit_points"] == 20
    assert body["new_hit_points"] == 13

    with postgres_engine.connect() as verify:
        hp = verify.execute(
            text(
                "SELECT current_hit_points FROM campaign.character_state "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"t": f.timeline_id, "c": f.defender_id},
        ).scalar()
    assert hp == 13


def test_claim_1b_a_non_combat_hp_change_updates_canonical_state_only_through_the_api(
    postgres_engine: Engine, f: Fixture
) -> None:
    external_system_id, raw_key = _provision(
        postgres_engine, world_id=f.world_id, user_id=f.gm_user_id, foundry_user_id="foundry-gm"
    )
    headers = _foundry_headers(external_system_id, raw_key, "foundry-gm")

    with TestClient(_app_for(postgres_engine), raise_server_exceptions=False) as adapter_client:
        response = adapter_client.post(
            f"/campaigns/{f.campaign_id}/characters/{f.defender_id}/hit-points",
            json={"world_time_id": str(f.world_time_id), "delta": -5},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert response.json()["new_hit_points"] == 15

    with postgres_engine.connect() as verify:
        hp = verify.execute(
            text(
                "SELECT current_hit_points FROM campaign.character_state "
                "WHERE timeline_id = :t AND character_id = :c"
            ),
            {"t": f.timeline_id, "c": f.defender_id},
        ).scalar()
    assert hp == 15


def test_claim_2_duplicate_delivery_creates_no_duplicate_event(
    postgres_engine: Engine, f: Fixture
) -> None:
    external_system_id, raw_key = _provision(
        postgres_engine, world_id=f.world_id, user_id=f.gm_user_id, foundry_user_id="foundry-gm"
    )
    headers = _foundry_headers(external_system_id, raw_key, "foundry-gm")

    with _oidc_client(postgres_engine, f.gm_user_id) as oidc_client:
        encounter_id = _start_encounter(oidc_client, f)

    body = _combat_sync_body(
        f, encounter_id, external_system_id=external_system_id, external_operation_id="op-duplicate"
    )
    with TestClient(_app_for(postgres_engine), raise_server_exceptions=False) as adapter_client:
        first = adapter_client.post(
            f"/campaigns/{f.campaign_id}/integration/foundry/combat-sync",
            json=body,
            headers=headers,
        )
        second = adapter_client.post(
            f"/campaigns/{f.campaign_id}/integration/foundry/combat-sync",
            json=body,
            headers=headers,
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["replayed"] is False
    assert second.json()["replayed"] is True
    assert second.json()["event_id"] == first.json()["event_id"]

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("SELECT count(*) FROM narrative.events WHERE event_id = :event"),
            {"event": first.json()["event_id"]},
        ).scalar_one()
    assert count == 1


def test_claim_3_reconnecting_restores_the_updated_state(
    postgres_engine: Engine, f: Fixture
) -> None:
    external_system_id, raw_key = _provision(
        postgres_engine, world_id=f.world_id, user_id=f.gm_user_id, foundry_user_id="foundry-gm"
    )
    headers = _foundry_headers(external_system_id, raw_key, "foundry-gm")

    with _oidc_client(postgres_engine, f.gm_user_id) as oidc_client:
        encounter_id = _start_encounter(oidc_client, f)

    with TestClient(_app_for(postgres_engine), raise_server_exceptions=False) as adapter_client:
        sync_response = adapter_client.post(
            f"/campaigns/{f.campaign_id}/integration/foundry/combat-sync",
            json=_combat_sync_body(
                f,
                encounter_id,
                external_system_id=external_system_id,
                external_operation_id="op-reconnect",
            ),
            headers=headers,
        )
        assert sync_response.status_code == 201, sync_response.text

    # "Reconnect": a brand-new client/app instance, no in-memory state
    # carried over — exactly what a fresh Foundry page load looks like
    # to the server. Reads only (sync-state + character), mirroring
    # foundry-module's own SyncEngine.restoreFromServer.
    with TestClient(_app_for(postgres_engine), raise_server_exceptions=False) as reconnect_client:
        sync_state_response = reconnect_client.get(
            f"/campaigns/{f.campaign_id}/integration/external-systems/{external_system_id}/sync-state",
            params={"target_encounter_id": str(encounter_id)},
            headers=headers,
        )
        character_response = reconnect_client.get(
            f"/campaigns/{f.campaign_id}/characters/{f.defender_id}", headers=headers
        )

    assert sync_state_response.status_code == 200, sync_state_response.text
    assert sync_state_response.json()["sync_status"] == "synced"
    assert sync_state_response.json()["last_sync_job_status"] == "completed"

    assert character_response.status_code == 200, character_response.text
    assert character_response.json()["current_hit_points"] == 13


def test_claim_4_a_foreign_world_credential_is_rejected(
    postgres_engine: Engine, f: Fixture
) -> None:
    # Registered under other_world_id, linked to a user who genuinely
    # holds canon.edit/campaign.view in BOTH campaigns — the credential
    # itself, not the linked user's membership, must be what's checked.
    foreign_system_id, foreign_raw_key = _provision(
        postgres_engine,
        world_id=f.other_world_id,
        user_id=f.gm_user_id,
        foundry_user_id="foundry-gm-foreign",
    )
    headers = _foundry_headers(foreign_system_id, foreign_raw_key, "foundry-gm-foreign")

    with TestClient(_app_for(postgres_engine), raise_server_exceptions=False) as adapter_client:
        response = adapter_client.get(
            f"/campaigns/{f.campaign_id}/characters/{f.defender_id}", headers=headers
        )
    assert response.status_code == 404


def test_claim_5_the_same_credential_cannot_call_management_only_routes(
    postgres_engine: Engine, f: Fixture
) -> None:
    external_system_id, raw_key = _provision(
        postgres_engine, world_id=f.world_id, user_id=f.gm_user_id, foundry_user_id="foundry-gm"
    )
    headers = _foundry_headers(external_system_id, raw_key, "foundry-gm")

    with TestClient(_app_for(postgres_engine), raise_server_exceptions=False) as adapter_client:
        register_response = adapter_client.post(
            f"/campaigns/{f.campaign_id}/integration/external-systems",
            json={"system_type": "foundry", "display_name": "Should Not Work"},
            headers=headers,
        )
        link_response = adapter_client.post(
            f"/campaigns/{f.campaign_id}/integration/external-systems/{external_system_id}/foundry-identities",
            json={"foundry_user_id": "someone-else", "user_id": str(f.gm_user_id)},
            headers=headers,
        )
        issue_key_response = adapter_client.post(
            f"/campaigns/{f.campaign_id}/integration/external-systems/{external_system_id}/foundry-system-key",
            json={"foundry_user_id": "foundry-gm"},
            headers=headers,
        )

    assert register_response.status_code == 403
    assert link_response.status_code == 403
    assert issue_key_response.status_code == 403
