"""Tests for `dnd_ai.api.access_groups` — Phase 13E-B checkpoint 6's
campaign access-group management: create/update/deactivate/reactivate a
group, add/remove a group member, group-owned resource grants (reusing
`dnd_ai.api.access_grants`' existing character-target grant endpoints,
hardened this checkpoint to require the grantee group currently be
active), the access-overview `access_groups` read-contract addition, and
the audit-history `access_group`/`access_group_membership` categories.
Mirrors `tests/database/test_api_access_grants.py`'s shape:
`get_authenticated_user_id` is overridden directly, since these tests
exercise campaign-capability enforcement and the commands' own HTTP
wiring, not OIDC token verification.

Covers: access control (non-member 404, capless-member 403); group create
(success, blank/whitespace-only name rejected, duplicate name rejected,
case-sensitive names both succeed, inactive campaign rejected, idempotent
replay); group update (success rename, no-op rejected, blank name
rejected, archived group rejected, cross-campaign rejected, duplicate name
rejected); deactivate (success closes memberships/revokes grants, already-
archived no-op, cross-campaign rejected, bounded audit content); reactivate
(success flips status back without restoring memberships/grants, already-
active no-op, inactive campaign rejected, cross-campaign rejected); add
member (success, duplicate-active rejected, archived group rejected,
ended/disabled-account membership rejected, cross-campaign rejected,
inactive campaign rejected, idempotent replay); remove member (success,
no-op retry, cross-campaign rejected, sibling membership preserved); group-
owned resource grants (create succeeds, create against an archived group
rejected, revoke succeeds); the access-overview `access_groups` field
(active and archived groups both listed, archived group's members/grants
empty); and audit-history (`access_group`/`access_group_membership`
categories, correct labels/summaries, one row per event, no duplicates)."""

import uuid
from collections.abc import Callable, Iterator
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="active"
        )
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        admin_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, admin_role_id, access_manage_id)
        make_role_capability(connection, admin_role_id, view_capability_id)

        self.admin_user_id = make_user(connection, "Access Group API Admin")
        self.admin_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.admin_user_id
        )
        make_membership_role(connection, self.admin_membership_id, admin_role_id)

        self.capless_user_id = make_user(connection, "Access Group API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Access Group API Outsider")

        self.target_user_id = make_user(connection, "Access Group API Target Member")
        self.target_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.target_user_id
        )

        self.second_member_user_id = make_user(connection, "Access Group API Second Member")
        self.second_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.second_member_user_id
        )

        self.ended_member_user_id = make_user(connection, "Access Group API Ended Member")
        self.ended_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.ended_member_user_id, ended=True
        )

        self.disabled_account_user_id = make_user(
            connection, "Access Group API Disabled Account", status_code="inactive"
        )
        self.disabled_account_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.disabled_account_user_id
        )

        foreign_user_id = make_user(connection, "Access Group API Foreign Member")
        self.foreign_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, foreign_user_id
        )

        self.group_id = make_access_group(connection, self.campaign_id, name="Lore Circle")
        self.archived_group_id = make_access_group(
            connection,
            self.campaign_id,
            name="Retired Group",
            lifecycle_status_code="archived",
        )
        self.foreign_group_id = make_access_group(
            connection, self.other_campaign_id, name="Foreign Group"
        )

        self.character_id = make_character(connection, self.world_id, name="Aria")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"access-group-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM security.resource_grants WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.access_group_memberships WHERE access_group_id IN (
                    SELECT access_group_id FROM security.access_groups WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.access_groups WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.idempotent_requests WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM audit.change_log WHERE world_id = :w
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.campaigns WHERE timeline_id IN (
                    SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.admin_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.target_user_id,
                    fixture.second_member_user_id,
                    fixture.ended_member_user_id,
                    fixture.disabled_account_user_id,
                ]
            },
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _deactivate_campaign(postgres_engine: Engine, campaign_id: uuid.UUID) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE campaign.campaigns
                SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'pending'
                )
                WHERE campaign_id = :c
            """),
            {"c": campaign_id},
        )


def _reactivate_campaign(postgres_engine: Engine, campaign_id: uuid.UUID) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE campaign.campaigns
                SET lifecycle_status_id = (
                    SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
                )
                WHERE campaign_id = :c
            """),
            {"c": campaign_id},
        )


def _groups_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/access-groups"


def _update_url(
    f: Fixture, access_group_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/access-groups/{access_group_id}/update"


def _deactivate_url(
    f: Fixture, access_group_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/access-groups/{access_group_id}/deactivate"


def _reactivate_url(
    f: Fixture, access_group_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/access-groups/{access_group_id}/reactivate"


def _add_member_url(
    f: Fixture, access_group_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/access-groups/{access_group_id}/members"


def _remove_member_url(
    f: Fixture, access_group_membership_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return (
        f"/campaigns/{campaign_id or f.campaign_id}/access-group-memberships/"
        f"{access_group_membership_id}/remove"
    )


def _grants_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/resource-grants"


def _revoke_grant_url(
    f: Fixture, resource_grant_id: uuid.UUID, campaign_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/resource-grants/{resource_grant_id}/revoke"


def _overview_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/access-overview"


def _audit_url(campaign_id: uuid.UUID, **params: object) -> str:
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v is not None)
    base = f"/campaigns/{campaign_id}/audit-history"
    return f"{base}?{query}" if query else base


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(_groups_url(f), json={"name": "New Group"})
    assert response.status_code == 404


def test_a_member_without_access_manage_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(_groups_url(f), json={"name": "New Group"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# create_access_group
# ---------------------------------------------------------------------------


def test_creating_a_group_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _groups_url(f), json={"name": "Livestream Observers", "description": "For the stream"}
        )
    assert response.status_code == 201, response.text
    access_group_id = uuid.UUID(response.json()["access_group_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT ag.name, ag.description, ls.code AS status_code
                FROM security.access_groups ag
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id
                WHERE ag.access_group_id = :g
            """),
            {"g": access_group_id},
        ).one()
        assert row.name == "Livestream Observers"
        assert row.description == "For the stream"
        assert row.status_code == "active"


def test_creating_a_group_trims_the_name(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_groups_url(f), json={"name": "  Padded Name  "})
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Padded Name"


def test_creating_a_group_with_a_blank_name_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_groups_url(f), json={"name": "   "})
    assert response.status_code == 422, response.text


def test_creating_a_group_with_an_over_length_name_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_groups_url(f), json={"name": "x" * 201})
    # Pydantic's own Field(max_length=200) rejects this before the request
    # body ever reaches dnd_ai.commands.access_groups.create_access_group.
    assert response.status_code == 422, response.text


def test_creating_a_group_with_an_over_length_description_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _groups_url(f), json={"name": "Bounded Group", "description": "x" * 2001}
        )
    assert response.status_code == 422, response.text


def test_creating_a_group_with_a_maximum_length_name_and_description_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_groups_url(f), json={"name": "y" * 200, "description": "z" * 2000})
    assert response.status_code == 201, response.text


def test_creating_a_group_with_a_whitespace_only_description_records_null_in_the_audit(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`changed_fields.description` must reflect the normalized, persisted
    value (`create_access_group`'s own trim-then-blank-to-None rule), never
    the raw request body — a whitespace-only description is stored (and
    thus audited) as NULL, not as the literal whitespace string."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _groups_url(f), json={"name": "Whitespace Description Group", "description": "   "}
        )
    assert response.status_code == 201, response.text
    access_group_id = uuid.UUID(response.json()["access_group_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT description, changed_fields FROM security.access_groups ag
                JOIN audit.change_log cl
                    ON cl.table_name = 'access_groups' AND cl.record_id = ag.access_group_id
                WHERE ag.access_group_id = :g AND cl.command_name = 'create_access_group'
            """),
            {"g": access_group_id},
        ).one()
        assert row.description is None
        assert row.changed_fields == {"name": "Whitespace Description Group", "description": None}


def test_a_direct_database_insert_with_an_over_length_description_is_rejected(
    f: Fixture, postgres_engine: Engine
) -> None:
    """`ck_access_groups_description_length` (migration 106) is the last
    line of defense against an over-length description reaching this
    column at all — proven here by inserting directly, bypassing both the
    API's Pydantic `Field(max_length=...)` and `dnd_ai.commands.
    access_groups.create_access_group`'s own pre-check entirely."""
    with pytest.raises(IntegrityError) as exc, postgres_engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO security.access_groups
                    (campaign_id, name, description, lifecycle_status_id)
                VALUES (
                    :campaign, 'Direct Insert Group', :description,
                    (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active')
                )
            """),
            {"campaign": f.campaign_id, "description": "x" * 2001},
        )
    assert "ck_access_groups_description_length" in str(exc.value)


def test_creating_a_group_with_a_duplicate_name_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_groups_url(f), json={"name": "Lore Circle"})
    assert response.status_code == 409, response.text


def test_creating_a_group_with_a_different_case_name_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """Group names are case-sensitive, matching `ux_access_groups_campaign_
    name`'s own plain-text comparison — a deliberate choice, not an
    oversight."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(_groups_url(f), json={"name": "LORE CIRCLE"})
    assert response.status_code == 201, response.text


def test_creating_a_group_on_an_inactive_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(_groups_url(f), json={"name": "Should Not Exist"})
        assert response.status_code == 409, response.text
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)


def test_a_sequential_replay_of_create_group_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"create-group-{uuid.uuid4().hex[:8]}"
    body = {"name": f"Replay Group {uuid.uuid4().hex[:8]}"}
    with client_factory(f.admin_user_id) as client:
        first = client.post(_groups_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_groups_url(f), json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


def test_creating_a_group_records_bounded_audit_content(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _groups_url(f), json={"name": "Audited Group", "description": "desc"}
        )
    assert response.status_code == 201, response.text
    access_group_id = uuid.UUID(response.json()["access_group_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT command_name, changed_fields, actor_user_id
                FROM audit.change_log
                WHERE table_name = 'access_groups' AND record_id = :g
            """),
            {"g": access_group_id},
        ).one()
        assert row.command_name == "create_access_group"
        assert row.actor_user_id == f.admin_user_id
        assert row.changed_fields == {"name": "Audited Group", "description": "desc"}


# ---------------------------------------------------------------------------
# update_access_group
# ---------------------------------------------------------------------------


def test_updating_a_group_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _update_url(f, f.group_id), json={"name": "Renamed Circle", "description": "new"}
        )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed Circle"

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("SELECT name, description FROM security.access_groups WHERE access_group_id = :g"),
            {"g": f.group_id},
        ).one()
        assert row.name == "Renamed Circle"
        assert row.description == "new"


def test_updating_a_group_with_no_change_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _update_url(f, f.group_id), json={"name": "Lore Circle", "description": None}
        )
    assert response.status_code == 422, response.text


def test_updating_a_group_with_a_blank_name_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_update_url(f, f.group_id), json={"name": "  "})
    assert response.status_code == 422, response.text


def test_updating_a_group_with_an_over_length_name_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_update_url(f, f.group_id), json={"name": "x" * 201})
    assert response.status_code == 422, response.text


def test_updating_a_group_with_an_over_length_description_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _update_url(f, f.group_id), json={"name": "Lore Circle", "description": "x" * 2001}
        )
    assert response.status_code == 422, response.text


def test_updating_a_group_with_a_whitespace_only_description_records_null_in_the_audit(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    # The name must actually change too — a request that would leave both
    # name and (normalized) description identical to the group's current
    # values is rejected as a no-op (AccessGroupUpdateNoOpError) before this
    # normalization behavior could even be observed.
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _update_url(f, f.group_id),
            json={"name": "Lore Circle Renamed", "description": "   "},
        )
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT description, changed_fields FROM security.access_groups ag
                JOIN audit.change_log cl
                    ON cl.table_name = 'access_groups' AND cl.record_id = ag.access_group_id
                WHERE ag.access_group_id = :g AND cl.command_name = 'update_access_group'
            """),
            {"g": f.group_id},
        ).one()
        assert row.description is None
        assert row.changed_fields == {"description": None}


def test_updating_an_archived_group_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_update_url(f, f.archived_group_id), json={"name": "New Name"})
    assert response.status_code == 409, response.text


def test_updating_a_group_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_update_url(f, f.foreign_group_id), json={"name": "New Name"})
    assert response.status_code == 404, response.text


def test_updating_a_group_to_a_duplicate_name_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_update_url(f, f.group_id), json={"name": "Retired Group"})
    assert response.status_code == 409, response.text


def test_updating_a_group_records_a_rename_change_summary(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_update_url(f, f.group_id), json={"name": "Renamed Again"})
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT previous_status, new_status FROM audit.change_log
                WHERE table_name = 'access_groups' AND record_id = :g
                  AND command_name = 'update_access_group'
            """),
            {"g": f.group_id},
        ).one()
        assert row.previous_status == "Lore Circle"
        assert row.new_status == "Renamed Again"


# ---------------------------------------------------------------------------
# deactivate_access_group / reactivate_access_group
# ---------------------------------------------------------------------------


def test_deactivating_a_group_closes_memberships_and_revokes_grants(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        member_response = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        assert member_response.status_code == 201, member_response.text
        access_group_membership_id = uuid.UUID(member_response.json()["access_group_membership_id"])

        grant_response = client.post(
            _grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(f.group_id),
            },
        )
        assert grant_response.status_code == 201, grant_response.text
        resource_grant_id = uuid.UUID(grant_response.json()["resource_grant_id"])

        response = client.post(_deactivate_url(f, f.group_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        status_code = verify.execute(
            text("""
                SELECT ls.code FROM security.access_groups ag
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id
                WHERE ag.access_group_id = :g
            """),
            {"g": f.group_id},
        ).scalar_one()
        assert status_code == "archived"

        removed_at = verify.execute(
            text(
                "SELECT removed_at FROM security.access_group_memberships "
                "WHERE access_group_membership_id = :m"
            ),
            {"m": access_group_membership_id},
        ).scalar_one()
        assert removed_at is not None

        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :r"),
            {"r": resource_grant_id},
        ).scalar_one()
        assert revoked_at is not None


def test_deactivating_a_group_with_many_dependents_records_bounded_audit_samples(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """More dependent rows than `dnd_ai.api.access_groups.
    _DEACTIVATE_AUDIT_ID_SAMPLE_LIMIT` (20) — proves deactivation still
    closes/revokes every one of them (unbounded cleanup, unaffected by the
    audit-bound correction), immediately removes their authorization
    effect, and records exactly one audit row with a bounded representation
    (exact `count`, a capped `sample_ids` prefix, `sample_truncated`)
    rather than the full, unbounded id list this checkpoint's first cut
    wrote."""
    dependent_count = 25
    extra_user_ids: list[uuid.UUID] = []
    extra_membership_ids: list[uuid.UUID] = []
    extra_character_ids: list[uuid.UUID] = []
    try:
        with postgres_engine.begin() as connection:
            for i in range(dependent_count):
                user_id = make_user(connection, f"Deactivate Sample Member {i}")
                extra_user_ids.append(user_id)
                extra_membership_ids.append(
                    make_campaign_membership(connection, f.campaign_id, user_id)
                )
                extra_character_ids.append(
                    make_character(connection, f.world_id, name=f"Sample Character {i}")
                )

        with client_factory(f.admin_user_id) as client:
            for membership_id in extra_membership_ids:
                response = client.post(
                    _add_member_url(f, f.group_id),
                    json={"campaign_membership_id": str(membership_id)},
                )
                assert response.status_code == 201, response.text

            for character_id in extra_character_ids:
                response = client.post(
                    _grants_url(f),
                    json={
                        "character_id": str(character_id),
                        "capability_code": "character.view_summary",
                        "grantee_access_group_id": str(f.group_id),
                    },
                )
                assert response.status_code == 201, response.text

            deactivate_response = client.post(_deactivate_url(f, f.group_id))
        assert deactivate_response.status_code == 200, deactivate_response.text

        with postgres_engine.connect() as verify:
            open_memberships = verify.execute(
                text("""
                    SELECT count(*) FROM security.access_group_memberships
                    WHERE access_group_id = :g AND removed_at IS NULL
                """),
                {"g": f.group_id},
            ).scalar_one()
            assert open_memberships == 0

            active_grants = verify.execute(
                text("""
                    SELECT count(*) FROM security.resource_grants
                    WHERE grantee_access_group_id = :g AND revoked_at IS NULL
                """),
                {"g": f.group_id},
            ).scalar_one()
            assert active_grants == 0

            audit_rows = verify.execute(
                text("""
                    SELECT changed_fields FROM audit.change_log
                    WHERE table_name = 'access_groups' AND record_id = :g
                      AND command_name = 'deactivate_access_group'
                """),
                {"g": f.group_id},
            ).all()
            assert len(audit_rows) == 1
            changed_fields = audit_rows[0].changed_fields

            memberships_summary = changed_fields["removed_access_group_memberships"]
            assert memberships_summary["count"] == dependent_count
            assert len(memberships_summary["sample_ids"]) == 20
            assert memberships_summary["sample_truncated"] is True

            grants_summary = changed_fields["revoked_resource_grants"]
            assert grants_summary["count"] == dependent_count
            assert len(grants_summary["sample_ids"]) == 20
            assert grants_summary["sample_truncated"] is True

        # A subsequent retry against the now-archived group remains the
        # documented no-op — no second audit row.
        with client_factory(f.admin_user_id) as client:
            retry = client.post(_deactivate_url(f, f.group_id))
        assert retry.status_code == 200, retry.text

        with postgres_engine.connect() as verify:
            audit_count = verify.execute(
                text("""
                    SELECT count(*) FROM audit.change_log
                    WHERE table_name = 'access_groups' AND record_id = :g
                      AND command_name = 'deactivate_access_group'
                """),
                {"g": f.group_id},
            ).scalar_one()
            assert audit_count == 1
    finally:
        with postgres_engine.begin() as cleanup:
            cleanup.execute(
                text(
                    "DELETE FROM security.campaign_memberships "
                    "WHERE user_id = ANY(:users) AND campaign_id = :campaign"
                ),
                {"users": extra_user_ids, "campaign": f.campaign_id},
            )
            cleanup.execute(
                text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
                {"users": extra_user_ids},
            )


def test_deactivating_an_already_archived_group_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_deactivate_url(f, f.archived_group_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        audit_count = verify.execute(
            text("""
                SELECT count(*) FROM audit.change_log
                WHERE table_name = 'access_groups' AND record_id = :g
                  AND command_name = 'deactivate_access_group'
            """),
            {"g": f.archived_group_id},
        ).scalar_one()
        assert audit_count == 0


def test_deactivating_a_group_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_deactivate_url(f, f.foreign_group_id))
    assert response.status_code == 404, response.text


def test_deactivating_a_group_does_not_affect_a_sibling_direct_grant(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        direct_grant = client.post(
            _grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_campaign_membership_id": str(f.target_membership_id),
            },
        )
        assert direct_grant.status_code == 201, direct_grant.text
        direct_grant_id = uuid.UUID(direct_grant.json()["resource_grant_id"])

        response = client.post(_deactivate_url(f, f.group_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :r"),
            {"r": direct_grant_id},
        ).scalar_one()
        assert revoked_at is None


def test_reactivating_a_group_does_not_restore_membership_or_grants(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        member_response = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        access_group_membership_id = uuid.UUID(member_response.json()["access_group_membership_id"])
        grant_response = client.post(
            _grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(f.group_id),
            },
        )
        resource_grant_id = uuid.UUID(grant_response.json()["resource_grant_id"])

        assert client.post(_deactivate_url(f, f.group_id)).status_code == 200
        response = client.post(_reactivate_url(f, f.group_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        status_code = verify.execute(
            text("""
                SELECT ls.code FROM security.access_groups ag
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id
                WHERE ag.access_group_id = :g
            """),
            {"g": f.group_id},
        ).scalar_one()
        assert status_code == "active"

        removed_at = verify.execute(
            text(
                "SELECT removed_at FROM security.access_group_memberships "
                "WHERE access_group_membership_id = :m"
            ),
            {"m": access_group_membership_id},
        ).scalar_one()
        assert removed_at is not None

        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :r"),
            {"r": resource_grant_id},
        ).scalar_one()
        assert revoked_at is not None


def test_reactivating_an_already_active_group_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_reactivate_url(f, f.group_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        audit_count = verify.execute(
            text("""
                SELECT count(*) FROM audit.change_log
                WHERE table_name = 'access_groups' AND record_id = :g
                  AND command_name = 'reactivate_access_group'
            """),
            {"g": f.group_id},
        ).scalar_one()
        assert audit_count == 0


def test_reactivating_a_group_on_an_inactive_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        assert client.post(_deactivate_url(f, f.group_id)).status_code == 200

    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(_reactivate_url(f, f.group_id))
        assert response.status_code == 409, response.text
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)


def test_reactivating_a_group_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(_reactivate_url(f, f.foreign_group_id))
    assert response.status_code == 404, response.text


def test_deactivating_a_group_requires_deliberate_confirmation_shaped_request(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The route itself accepts no body (nothing to confirm server-side
    beyond the path) — this documents that deliberate confirmation is a
    portal-level UI affordance, not a server-enforced request shape,
    matching every other revoke/end/remove route in this codebase."""
    with client_factory(f.admin_user_id) as client:
        response = client.post(_deactivate_url(f, f.group_id), json={})
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# add_access_group_member / remove_access_group_member
# ---------------------------------------------------------------------------


def test_adding_a_member_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
    assert response.status_code == 201, response.text
    access_group_membership_id = uuid.UUID(response.json()["access_group_membership_id"])

    with postgres_engine.connect() as verify:
        row = verify.execute(
            text("""
                SELECT access_group_id, campaign_membership_id, removed_at
                FROM security.access_group_memberships WHERE access_group_membership_id = :m
            """),
            {"m": access_group_membership_id},
        ).one()
        assert row.access_group_id == f.group_id
        assert row.campaign_membership_id == f.target_membership_id
        assert row.removed_at is None


def test_adding_a_duplicate_active_member_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        first = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        assert first.status_code == 201, first.text
        second = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
    assert second.status_code == 409, second.text


def test_adding_a_member_to_an_archived_group_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _add_member_url(f, f.archived_group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
    assert response.status_code == 409, response.text


def test_adding_an_ended_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.ended_membership_id)},
        )
    assert response.status_code == 409, response.text


def test_adding_a_membership_with_a_disabled_account_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.disabled_account_membership_id)},
        )
    assert response.status_code == 409, response.text


def test_adding_a_foreign_campaign_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.foreign_membership_id)},
        )
    assert response.status_code == 404, response.text


def test_adding_a_member_to_a_foreign_campaign_group_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _add_member_url(f, f.foreign_group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
    assert response.status_code == 404, response.text


def test_adding_a_member_on_an_inactive_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    _deactivate_campaign(postgres_engine, f.campaign_id)
    try:
        with client_factory(f.admin_user_id) as client:
            response = client.post(
                _add_member_url(f, f.group_id),
                json={"campaign_membership_id": str(f.target_membership_id)},
            )
        assert response.status_code == 409, response.text
    finally:
        _reactivate_campaign(postgres_engine, f.campaign_id)


def test_a_sequential_replay_of_add_member_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"add-member-{uuid.uuid4().hex[:8]}"
    body = {"campaign_membership_id": str(f.target_membership_id)}
    with client_factory(f.admin_user_id) as client:
        first = client.post(
            _add_member_url(f, f.group_id), json=body, headers={"Idempotency-Key": key}
        )
        second = client.post(
            _add_member_url(f, f.group_id), json=body, headers={"Idempotency-Key": key}
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()


def test_removing_a_member_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        add = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        access_group_membership_id = uuid.UUID(add.json()["access_group_membership_id"])
        response = client.post(_remove_member_url(f, access_group_membership_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        removed_at = verify.execute(
            text(
                "SELECT removed_at FROM security.access_group_memberships "
                "WHERE access_group_membership_id = :m"
            ),
            {"m": access_group_membership_id},
        ).scalar_one()
        assert removed_at is not None


def test_removing_an_already_removed_member_is_a_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        add = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        access_group_membership_id = uuid.UUID(add.json()["access_group_membership_id"])
        assert client.post(_remove_member_url(f, access_group_membership_id)).status_code == 200
        response = client.post(_remove_member_url(f, access_group_membership_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        audit_count = verify.execute(
            text("""
                SELECT count(*) FROM audit.change_log
                WHERE table_name = 'access_group_memberships' AND record_id = :m
                  AND command_name = 'remove_access_group_member'
            """),
            {"m": access_group_membership_id},
        ).scalar_one()
        assert audit_count == 1


def test_removing_a_member_preserves_a_sibling_group_membership(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        other_group_id = make_access_group(connection, f.campaign_id, name="Second Group")

    with client_factory(f.admin_user_id) as client:
        first = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        first_membership_id = uuid.UUID(first.json()["access_group_membership_id"])
        second = client.post(
            _add_member_url(f, other_group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        second_membership_id = uuid.UUID(second.json()["access_group_membership_id"])

        response = client.post(_remove_member_url(f, first_membership_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        removed_at = verify.execute(
            text(
                "SELECT removed_at FROM security.access_group_memberships "
                "WHERE access_group_membership_id = :m"
            ),
            {"m": second_membership_id},
        ).scalar_one()
        assert removed_at is None


def test_removing_a_member_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        foreign_membership_link = make_access_group_membership(
            connection, f.foreign_group_id, f.foreign_membership_id
        )

    with client_factory(f.admin_user_id) as client:
        response = client.post(_remove_member_url(f, foreign_membership_link))
    assert response.status_code == 404, response.text


def test_self_removal_from_a_group_is_permitted(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        add = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.admin_membership_id)},
        )
        access_group_membership_id = uuid.UUID(add.json()["access_group_membership_id"])
        response = client.post(_remove_member_url(f, access_group_membership_id))
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Group-owned resource grants (dnd_ai.api.access_grants, hardened this
# checkpoint to require an active grantee group)
# ---------------------------------------------------------------------------


def test_creating_a_character_grant_for_the_group_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(f.group_id),
            },
        )
    assert response.status_code == 201, response.text


def test_creating_a_grant_for_an_archived_group_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.post(
            _grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(f.archived_group_id),
            },
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM security.resource_grants WHERE grantee_access_group_id = :g"
            ),
            {"g": f.archived_group_id},
        ).scalar_one()
        assert count == 0


def test_revoking_a_group_owned_grant_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.admin_user_id) as client:
        grant = client.post(
            _grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(f.group_id),
            },
        )
        resource_grant_id = uuid.UUID(grant.json()["resource_grant_id"])
        response = client.post(_revoke_grant_url(f, resource_grant_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.resource_grants WHERE resource_grant_id = :r"),
            {"r": resource_grant_id},
        ).scalar_one()
        assert revoked_at is not None


# ---------------------------------------------------------------------------
# Access overview: access_groups
# ---------------------------------------------------------------------------


def test_access_overview_lists_active_and_archived_groups(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as connection:
        make_access_group_membership(connection, f.archived_group_id, f.target_membership_id)

    with client_factory(f.admin_user_id) as client:
        add = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        assert add.status_code == 201, add.text
        grant = client.post(
            _grants_url(f),
            json={
                "character_id": str(f.character_id),
                "capability_code": "character.view_summary",
                "grantee_access_group_id": str(f.group_id),
            },
        )
        assert grant.status_code == 201, grant.text

        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text

    groups_by_id = {group["access_group_id"]: group for group in response.json()["access_groups"]}
    active_group = groups_by_id[str(f.group_id)]
    assert active_group["status_code"] == "active"
    assert len(active_group["members"]) == 1
    assert active_group["members"][0]["campaign_membership_id"] == str(f.target_membership_id)
    assert len(active_group["grants"]) == 1
    assert active_group["grants"][0]["capability_code"] == "character.view_summary"

    archived_group = groups_by_id[str(f.archived_group_id)]
    assert archived_group["status_code"] == "archived"
    # The archived group's own membership row was inserted directly by the
    # factory above (bypassing deactivate_access_group's own cleanup) —
    # it still must not appear, because the group itself was never active
    # through this checkpoint's own create flow. This proves the overview's
    # own read-side filters (not deactivate_access_group's cleanup alone)
    # are what keep an inactive group's membership from ever being counted
    # as currently effective.
    assert archived_group["members"] == []


def test_access_overview_reports_account_is_active_per_member(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """Checkpoint-6 correction: the read contract exposes exactly one
    minimal, derived boolean per member (`account_is_active`) — never the
    account's raw lifecycle status code, login name, email, or identity
    subject — so the portal's own access-group "Add member" selector can
    filter out an account `add_access_group_member` would reject anyway."""
    with client_factory(f.admin_user_id) as client:
        response = client.get(_overview_url(f))
    assert response.status_code == 200, response.text

    members_by_membership_id = {
        member["campaign_membership_id"]: member for member in response.json()["members"]
    }
    assert members_by_membership_id[str(f.target_membership_id)]["account_is_active"] is True
    assert (
        members_by_membership_id[str(f.disabled_account_membership_id)]["account_is_active"]
        is False
    )
    # The disabled account's membership still appears on the overview at
    # all — this field narrows what the group selector offers, it does not
    # hide the member from the read contract itself.
    assert str(f.disabled_account_membership_id) in members_by_membership_id


# ---------------------------------------------------------------------------
# Audit history: access_group / access_group_membership categories
# ---------------------------------------------------------------------------


def test_audit_history_records_one_row_per_group_lifecycle_event(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        create = client.post(_groups_url(f), json={"name": "Audit Trail Group"})
        access_group_id = create.json()["access_group_id"]
        assert (
            client.post(
                _update_url(f, uuid.UUID(access_group_id)), json={"name": "Renamed Trail"}
            ).status_code
            == 200
        )
        assert client.post(_deactivate_url(f, uuid.UUID(access_group_id))).status_code == 200
        assert client.post(_reactivate_url(f, uuid.UUID(access_group_id))).status_code == 200

        response = client.get(_audit_url(f.campaign_id, category="access_group", limit=100))
    assert response.status_code == 200, response.text
    items = response.json()["items"]

    matching = [item for item in items if item["target_label"] == "Renamed Trail"]
    action_labels = [item["action_label"] for item in matching]
    assert action_labels.count("Access group created") == 1
    assert action_labels.count("Access group updated") == 1
    assert action_labels.count("Access group deactivated") == 1
    assert action_labels.count("Access group reactivated") == 1
    # Every change_log_id in this slice is unique — the regression class
    # test_api_audit_history_role_lookup.py guards against (a join that
    # matches more than one row turning one event into two response items).
    change_log_ids = [item["change_log_id"] for item in matching]
    assert len(change_log_ids) == len(set(change_log_ids))

    update_item = next(item for item in matching if item["action_label"] == "Access group updated")
    assert update_item["change_summary"] == "Audit Trail Group → Renamed Trail"
    assert update_item["target_type"] == "access_group"


def test_audit_history_records_group_membership_events(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        add = client.post(
            _add_member_url(f, f.group_id),
            json={"campaign_membership_id": str(f.target_membership_id)},
        )
        access_group_membership_id = add.json()["access_group_membership_id"]
        assert (
            client.post(_remove_member_url(f, uuid.UUID(access_group_membership_id))).status_code
            == 200
        )

        response = client.get(
            _audit_url(f.campaign_id, category="access_group_membership", limit=100)
        )
    assert response.status_code == 200, response.text
    items = response.json()["items"]

    matching = [item for item in items if item["target_label"] == "Access Group API Target Member"]
    assert len(matching) == 2
    action_labels = {item["action_label"] for item in matching}
    assert action_labels == {"Access group member added", "Access group member removed"}
    for item in matching:
        assert item["target_type"] == "account"
        assert item["change_summary"] == "Lore Circle"
    change_log_ids = [item["change_log_id"] for item in matching]
    assert len(change_log_ids) == len(set(change_log_ids))


def test_audit_history_never_exposes_raw_ids_for_group_events(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        create = client.post(_groups_url(f), json={"name": "No Raw Ids Group"})
        access_group_id = create.json()["access_group_id"]

        response = client.get(_audit_url(f.campaign_id, category="access_group", limit=100))
    body = response.text
    assert access_group_id not in body
