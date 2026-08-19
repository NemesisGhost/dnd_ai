"""Tests for `dnd_ai.api.integration` — Phase 10 workstream 10's command
endpoints over `dnd_ai.commands.integration.register_external_system`/
`.map_external_identifier` (docs/PLAN.md Phase 10 "command endpoints over
the existing command/application services", the `integration` domain), plus
Phase 11 workstream 1's `link_foundry_identity` endpoint. Mirrors
`tests/database/test_api_events.py`'s shape: `get_authenticated_user_id` is
overridden directly (the OIDC verification chain itself is already fully
covered by `tests/database/test_api_auth.py`) since these tests exercise
campaign-capability enforcement and the integration commands' own HTTP
wiring, not token verification.

`apply_foundry_combat_sync` has no endpoint (see `dnd_ai.api.integration`'s
own module docstring for why — deferred to a follow-up Phase 11 workstream)
and is not covered here; its command-layer behavior remains covered by
`tests/scenario/test_foundry_sync_commands.py`.
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
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

# Mirrors dnd_ai.api.integration's own private command-name constants —
# duplicated here deliberately (tests assert on the public audit.change_log
# contract, not by importing the module's private constants).
_REGISTER_EXTERNAL_SYSTEM_COMMAND = "register_external_system"
_MAP_EXTERNAL_IDENTIFIER_COMMAND = "map_external_identifier"
_LINK_FOUNDRY_IDENTITY_COMMAND = "link_foundry_identity"


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        self.actor_id = make_character(connection, self.world_id, name="Rin")

        # A second world/timeline/campaign, used only to prove
        # map_external_identifier rejects an external_system_id belonging
        # to a different world than the caller's own authorized campaign.
        self.other_world_id = make_world(connection, slug=f"{slug}-other")
        other_timeline_id = make_timeline(connection, self.other_world_id, is_primary=True)
        self.other_campaign_id = make_campaign(
            connection, other_timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        self.gm_user_id = make_user(connection, "Integration API GM")
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
        # used to prove the cross-world rejection is a real ownership check,
        # not just access control.
        other_gm_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.gm_user_id
        )
        other_role_id = make_role(
            connection, campaign_id=self.other_campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, other_role_id, canon_edit_id)
        make_membership_role(connection, other_gm_membership_id, other_role_id)

        self.capless_user_id = make_user(connection, "Integration API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Integration API Outsider")

        # link_foundry_identity_endpoint requires access.manage, not
        # canon.edit — a separate membership from self.gm_user_id (which
        # only holds canon.edit) so tests can prove that distinction, in
        # both this campaign and the other-world campaign (mirroring
        # gm_user_id's own cross-world setup above).
        self.admin_user_id = make_user(connection, "Integration API Admin")
        admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        admin_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        make_role_capability(connection, admin_role_id, access_manage_id)
        make_membership_role(connection, admin_membership_id, admin_role_id)

        other_admin_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.admin_user_id
        )
        other_admin_role_id = make_role(
            connection, campaign_id=self.other_campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, other_admin_role_id, access_manage_id)
        make_membership_role(connection, other_admin_membership_id, other_admin_role_id)

        # The platform user a Foundry user id gets linked to in the tests
        # below — distinct from every actor above so assertions can't
        # accidentally pass by coincidence.
        self.link_target_user_id = make_user(connection, "Integration API Link Target")
        self.other_link_target_user_id = make_user(connection, "Integration API Other Link Target")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"integration-api-{uuid.uuid4().hex[:8]}")
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
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.admin_user_id,
                    fixture.link_target_user_id,
                    fixture.other_link_target_user_id,
                ]
            },
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


def _register_url(campaign_id: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/integration/external-systems"


def _identifiers_url(campaign_id: uuid.UUID, external_system_id: uuid.UUID) -> str:
    return f"/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/identifiers"


def _foundry_identities_url(campaign_id: uuid.UUID, external_system_id: uuid.UUID) -> str:
    return (
        f"/campaigns/{campaign_id}/integration/external-systems/{external_system_id}"
        "/foundry-identities"
    )


def _register_body() -> dict[str, object]:
    return {"system_type": "foundry", "display_name": "Test Foundry World"}


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(_register_url(f.campaign_id), json=_register_body())
    assert response.status_code == 404


def test_a_member_without_the_capability_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(_register_url(f.campaign_id), json=_register_body())
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# register_external_system
# ---------------------------------------------------------------------------


def test_registering_an_external_system_creates_the_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _register_url(f.campaign_id),
            json={
                "system_type": "foundry",
                "display_name": "Test Foundry World",
                "external_reference": "foundry-world-123",
            },
        )
    assert response.status_code == 201, response.text
    external_system_id = uuid.UUID(response.json()["external_system_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT world_id, system_type, display_name, external_reference
                FROM integration.external_systems WHERE external_system_id = :s
            """),
            {"s": external_system_id},
        ).one()
    assert row.world_id == f.world_id
    assert row.system_type == "foundry"
    assert row.display_name == "Test Foundry World"
    assert row.external_reference == "foundry-world-123"


def test_the_register_audit_row_has_no_entity_id(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.post(_register_url(f.campaign_id), json=_register_body())
    assert response.status_code == 201, response.text
    external_system_id = uuid.UUID(response.json()["external_system_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT actor_user_id, entity_id, world_id, event_id, ca.code AS change_action_code
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.record_id = :s AND cl.command_name = :c
            """),
            {"s": external_system_id, "c": _REGISTER_EXTERNAL_SYSTEM_COMMAND},
        ).one()
    assert row.actor_user_id == f.gm_user_id
    assert row.entity_id is None
    assert row.world_id == f.world_id
    assert row.event_id is None
    assert row.change_action_code == "created"


def test_a_sequential_replay_returns_the_original_response_with_no_new_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"replay-{uuid.uuid4().hex[:8]}"
    body = _register_body()
    with client_factory(f.gm_user_id) as client:
        first = client.post(
            _register_url(f.campaign_id), json=body, headers={"Idempotency-Key": key}
        )
        second = client.post(
            _register_url(f.campaign_id), json=body, headers={"Idempotency-Key": key}
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("SELECT count(*) FROM integration.external_systems WHERE world_id = :w"),
            {"w": f.world_id},
        ).scalar_one()
    assert count == 1


def test_same_key_with_a_different_payload_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"mismatch-{uuid.uuid4().hex[:8]}"
    with client_factory(f.gm_user_id) as client:
        first = client.post(
            _register_url(f.campaign_id), json=_register_body(), headers={"Idempotency-Key": key}
        )
        second = client.post(
            _register_url(f.campaign_id),
            json={**_register_body(), "display_name": "A different name"},
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text


# ---------------------------------------------------------------------------
# map_external_identifier
# ---------------------------------------------------------------------------


def _register_system(client: TestClient, campaign_id: uuid.UUID) -> uuid.UUID:
    response = client.post(_register_url(campaign_id), json=_register_body())
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["external_system_id"])


def test_mapping_an_identifier_creates_the_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        external_system_id = _register_system(client, f.campaign_id)
        response = client.post(
            _identifiers_url(f.campaign_id, external_system_id),
            json={"entity_id": str(f.actor_id), "external_kind": "actor", "external_id": "actor-1"},
        )
    assert response.status_code == 200, response.text
    external_identifier_id = uuid.UUID(response.json()["external_identifier_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT external_system_id, entity_id, external_kind, external_id
                FROM integration.external_identifiers WHERE external_identifier_id = :i
            """),
            {"i": external_identifier_id},
        ).one()
    assert row.external_system_id == external_system_id
    assert row.entity_id == f.actor_id
    assert row.external_kind == "actor"
    assert row.external_id == "actor-1"


def test_remapping_the_same_external_object_upserts_rather_than_duplicates(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        external_system_id = _register_system(client, f.campaign_id)
        body = {"entity_id": str(f.actor_id), "external_kind": "actor", "external_id": "actor-1"}
        first = client.post(_identifiers_url(f.campaign_id, external_system_id), json=body)
        second = client.post(_identifiers_url(f.campaign_id, external_system_id), json=body)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM integration.external_identifiers "
                "WHERE external_system_id = :s"
            ),
            {"s": external_system_id},
        ).scalar_one()
    assert count == 1


def test_an_external_system_from_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    # f.gm_user_id also has canon.edit in f.other_campaign_id (a different
    # world), so this proves the cross-world ownership check itself, not
    # merely access control.
    with client_factory(f.gm_user_id) as client:
        foreign_external_system_id = _register_system(client, f.other_campaign_id)
        response = client.post(
            _identifiers_url(f.campaign_id, foreign_external_system_id),
            json={"entity_id": str(f.actor_id), "external_kind": "actor", "external_id": "actor-1"},
        )
    assert response.status_code == 404

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM integration.external_identifiers "
                "WHERE external_system_id = :s"
            ),
            {"s": foreign_external_system_id},
        ).scalar_one()
    assert count == 0


def test_the_map_audit_row_uses_the_mapped_entity(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.gm_user_id) as client:
        external_system_id = _register_system(client, f.campaign_id)
        response = client.post(
            _identifiers_url(f.campaign_id, external_system_id),
            json={"entity_id": str(f.actor_id), "external_kind": "actor", "external_id": "actor-1"},
        )
    assert response.status_code == 200, response.text
    external_identifier_id = uuid.UUID(response.json()["external_identifier_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT actor_user_id, entity_id, world_id, ca.code AS change_action_code
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.record_id = :i AND cl.command_name = :c
            """),
            {"i": external_identifier_id, "c": _MAP_EXTERNAL_IDENTIFIER_COMMAND},
        ).one()
    assert row.actor_user_id == f.gm_user_id
    assert row.entity_id == f.actor_id
    assert row.world_id == f.world_id
    assert row.change_action_code == "updated"


# ---------------------------------------------------------------------------
# link_foundry_identity
# ---------------------------------------------------------------------------


def _register_system_as_gm(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, campaign_id: uuid.UUID
) -> uuid.UUID:
    """register_external_system requires canon.edit, which f.admin_user_id
    (access.manage only, for link_foundry_identity below) deliberately does
    not hold — see test_a_member_with_only_canon_edit_gets_forbidden_for_
    foundry_identity_link. Registration therefore always happens as
    f.gm_user_id, on its own client, before a separate f.admin_user_id
    client performs the actual foundry-identity link under test."""
    with client_factory(f.gm_user_id) as client:
        return _register_system(client, campaign_id)


def test_a_member_with_only_canon_edit_gets_forbidden_for_foundry_identity_link(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    # f.gm_user_id holds canon.edit (sufficient for register/map above) but
    # not access.manage — proving link_foundry_identity_endpoint really
    # requires the narrower, distinct capability documented in
    # dnd_ai.api.integration's own module docstring, not just any
    # integration-administration-shaped capability.
    external_system_id = _register_system_as_gm(client_factory, f, f.campaign_id)
    with client_factory(f.gm_user_id) as client:
        response = client.post(
            _foundry_identities_url(f.campaign_id, external_system_id),
            json={"foundry_user_id": "foundry-user-1", "user_id": str(f.link_target_user_id)},
        )
    assert response.status_code == 403


def test_linking_a_foundry_identity_creates_the_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    external_system_id = _register_system_as_gm(client_factory, f, f.campaign_id)
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _foundry_identities_url(f.campaign_id, external_system_id),
            json={"foundry_user_id": "foundry-user-1", "user_id": str(f.link_target_user_id)},
        )
    assert response.status_code == 200, response.text
    external_identity_id = uuid.UUID(response.json()["external_identity_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT user_id, issuer, subject, revoked_at
                FROM security.external_identities WHERE external_identity_id = :i
            """),
            {"i": external_identity_id},
        ).one()
    assert row.user_id == f.link_target_user_id
    assert row.issuer == f"foundry:{external_system_id}"
    assert row.subject == "foundry-user-1"
    assert row.revoked_at is None


def test_relinking_the_same_foundry_user_reassigns_rather_than_duplicates(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    external_system_id = _register_system_as_gm(client_factory, f, f.campaign_id)
    with client_factory(f.admin_user_id) as client:
        first = client.post(
            _foundry_identities_url(f.campaign_id, external_system_id),
            json={"foundry_user_id": "foundry-user-1", "user_id": str(f.link_target_user_id)},
        )
        second = client.post(
            _foundry_identities_url(f.campaign_id, external_system_id),
            json={
                "foundry_user_id": "foundry-user-1",
                "user_id": str(f.other_link_target_user_id),
            },
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    external_identity_id = uuid.UUID(first.json()["external_identity_id"])
    assert uuid.UUID(second.json()["external_identity_id"]) == external_identity_id

    with postgres_engine.connect() as verify:
        rows = verify.execute(
            text("""
                SELECT user_id FROM security.external_identities
                WHERE issuer = :issuer AND subject = 'foundry-user-1'
            """),
            {"issuer": f"foundry:{external_system_id}"},
        ).all()
    assert len(rows) == 1
    assert rows[0].user_id == f.other_link_target_user_id


def test_a_foundry_link_for_an_external_system_from_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    # f.admin_user_id also has access.manage in f.other_campaign_id (a
    # different world), so this proves the cross-world ownership check
    # itself, not merely access control — mirrors
    # test_an_external_system_from_a_different_world_is_rejected above.
    foreign_external_system_id = _register_system_as_gm(client_factory, f, f.other_campaign_id)
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _foundry_identities_url(f.campaign_id, foreign_external_system_id),
            json={"foundry_user_id": "foundry-user-1", "user_id": str(f.link_target_user_id)},
        )
    assert response.status_code == 404

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("SELECT count(*) FROM security.external_identities WHERE issuer = :issuer"),
            {"issuer": f"foundry:{foreign_external_system_id}"},
        ).scalar_one()
    assert count == 0


def test_a_nonexistent_target_user_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    external_system_id = _register_system_as_gm(client_factory, f, f.campaign_id)
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _foundry_identities_url(f.campaign_id, external_system_id),
            json={"foundry_user_id": "foundry-user-1", "user_id": str(uuid.uuid4())},
        )
    assert response.status_code == 400


def test_the_foundry_identity_audit_row_has_no_entity_id(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    external_system_id = _register_system_as_gm(client_factory, f, f.campaign_id)
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _foundry_identities_url(f.campaign_id, external_system_id),
            json={"foundry_user_id": "foundry-user-1", "user_id": str(f.link_target_user_id)},
        )
    assert response.status_code == 200, response.text
    external_identity_id = uuid.UUID(response.json()["external_identity_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT actor_user_id, entity_id, world_id, event_id, ca.code AS change_action_code
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.record_id = :i AND cl.command_name = :c
            """),
            {"i": external_identity_id, "c": _LINK_FOUNDRY_IDENTITY_COMMAND},
        ).one()
    assert row.actor_user_id == f.admin_user_id
    assert row.entity_id is None
    assert row.world_id == f.world_id
    assert row.event_id is None
    assert row.change_action_code == "updated"
