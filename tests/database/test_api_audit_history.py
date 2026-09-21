"""Tests for `dnd_ai.api.audit_history` — the Phase 13E-B audit-history
read API (`GET /campaigns/{campaign_id}/audit-history`), the independent
foundation for a future Access-page "Audit history" panel. Mirrors
`tests/database/test_api_access_overview.py`'s shape: `get_authenticated_
user_id` is overridden directly, and every scenario is exercised through a
real `audit.change_log` row written by the identical `dnd_ai.api.audit.
record_change_log` every real command uses — never a synthetic row shape
this module invented.

The fixture pins every write inside one transaction, so PostgreSQL's own
`now()` (frozen for the transaction's duration) gives every `audit.
change_log.recorded_at` the *same* timestamp — deliberately exploited here
to prove the `change_log_id` tie-breaker actually orders (and paginates)
a real timestamp tie, not merely a hypothetical one.

Covers: access control (non-member 404, capless-member 403), successful
read of every one of the six curated categories, deterministic newest-
first ordering under a real timestamp tie, stable keyset pagination across
that same tie, page-size bounds, malformed-filter validation (category,
actor_user_id, datetime, cursor), empty history, cross-campaign isolation
on a *shared timeline* (the exact leak this endpoint's query design
exists to prevent — see `dnd_ai.queries.audit_history`'s own module
docstring), sensitive-metadata exclusion (`changed_fields`/`reason` never
appear in the response body), and the documented current-name-only
actor/target fidelity limitation (a renamed account/character shows its
current name; a deleted actor falls back to a fixed, non-UUID placeholder,
never a raw id)."""

import base64
import json
import uuid
from collections.abc import Callable, Iterator
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.audit import record_change_log
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_invitation,
    make_campaign_membership,
    make_capability,
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_membership_role,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
)

pytestmark = pytest.mark.database

_SENSITIVE_MARKER = "definitely-a-secret-value-should-never-leak"


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        # Every campaign below shares one timeline deliberately — proving
        # the query correctly scopes by campaign_id, not by world_id/
        # timeline_id, which two sibling campaigns can share
        # (campaign.campaigns' own "several campaigns may share one
        # timeline" comment) and which would otherwise leak Campaign A's
        # membership/role/grant history into Campaign B's audit view.
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        def _make_admin(campaign_id: uuid.UUID, label: str) -> tuple[uuid.UUID, uuid.UUID]:
            role_id = make_role(
                connection, campaign_id=campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
            )
            make_role_capability(connection, role_id, access_manage_id)
            make_role_capability(connection, role_id, view_capability_id)
            user_id = make_user(connection, label)
            membership_id = make_campaign_membership(connection, campaign_id, user_id)
            make_membership_role(connection, membership_id, role_id)
            return user_id, membership_id

        # --- Campaign A: the rich fixture, one event per curated command ---
        self.campaign_id = make_campaign(connection, self.timeline_id, "Audit History Campaign A")
        self.admin_user_id, self.admin_membership_id = _make_admin(
            self.campaign_id, "Audit History Admin A"
        )

        self.capless_user_id = make_user(connection, "Audit History Capless Member")
        self.capless_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.capless_user_id
        )

        self.outsider_user_id = make_user(connection, "Audit History Outsider")

        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        observer_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"observer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, observer_role_id, view_capability_id)

        self.member_user_id = make_user(connection, "Audit History Member")
        self.member_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.member_user_id
        )

        self.character_id = make_character(
            connection, self.world_id, name="Audit History Character"
        )
        viewer_type_id = make_character_relationship_type(
            connection, code=f"viewer_{uuid.uuid4().hex[:8]}"
        )
        portrayer_type_id = make_character_relationship_type(
            connection, code=f"portrayer_{uuid.uuid4().hex[:8]}"
        )

        grant_capability_id = make_capability(
            connection, code=f"test.audit_history_grant_{uuid.uuid4().hex[:8]}"
        )

        def _record(
            *,
            command: str,
            action: str,
            table: str,
            record_id: uuid.UUID,
            actor_user_id: uuid.UUID | None = None,
            previous_status: str | None = None,
            new_status: str | None = None,
            changed_fields: dict[str, object] | None = None,
        ) -> None:
            record_change_log(
                connection,
                change_action_code=action,
                schema_name="security" if table != "campaigns" else "campaign",
                table_name=table,
                record_id=record_id,
                entity_id=None,
                world_id=self.world_id,
                actor_user_id=actor_user_id if actor_user_id is not None else self.admin_user_id,
                correlation_id=None,
                command_name=command,
                event_id=None,
                previous_status=previous_status,
                new_status=new_status,
                changed_fields=changed_fields,
            )

        # 1. campaign creation
        _record(
            command="create_campaign",
            action="created",
            table="campaigns",
            record_id=self.campaign_id,
        )

        # 2. add member (also the "sensitive metadata never leaks" carrier)
        _record(
            command="add_campaign_member",
            action="created",
            table="campaign_memberships",
            record_id=self.member_membership_id,
            changed_fields={
                "secret_token": _SENSITIVE_MARKER,
                "note": "member added via test fixture",
            },
        )

        # 3. assign role
        assigned_role_id = make_membership_role(
            connection, self.member_membership_id, player_role_id
        )
        _record(
            command="assign_membership_role",
            action="created",
            table="membership_roles",
            record_id=assigned_role_id,
        )

        # 4. change role: revoke the assigned row, create a new one
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": assigned_role_id},
        )
        changed_role_id = make_membership_role(
            connection, self.member_membership_id, observer_role_id
        )
        self.changed_membership_role_id = changed_role_id
        player_code = connection.execute(
            text("SELECT code FROM security.roles WHERE role_id = :r"), {"r": player_role_id}
        ).scalar()
        observer_code = connection.execute(
            text("SELECT code FROM security.roles WHERE role_id = :r"), {"r": observer_role_id}
        ).scalar()
        _record(
            command="change_membership_role",
            action="updated",
            table="membership_roles",
            record_id=changed_role_id,
            previous_status=player_code,
            new_status=observer_code,
        )

        # 5. revoke role (a third, independent role row)
        third_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"third_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, third_role_id, view_capability_id)
        revoked_role_row_id = make_membership_role(
            connection, self.member_membership_id, third_role_id, revoked=True
        )
        _record(
            command="revoke_membership_role",
            action="updated",
            table="membership_roles",
            record_id=revoked_role_row_id,
        )

        # 6. grant character relationship
        granted_relationship_id = make_membership_character_relationship(
            connection, self.member_membership_id, self.character_id, viewer_type_id
        )
        self.granted_relationship_id = granted_relationship_id
        _record(
            command="grant_character_relationship",
            action="created",
            table="membership_character_relationships",
            record_id=granted_relationship_id,
        )

        # 7. change character relationship
        connection.execute(
            text(
                "UPDATE security.membership_character_relationships "
                "SET revoked_at = now() WHERE membership_character_relationship_id = :r"
            ),
            {"r": granted_relationship_id},
        )
        changed_relationship_id = make_membership_character_relationship(
            connection, self.member_membership_id, self.character_id, portrayer_type_id
        )
        viewer_code = connection.execute(
            text(
                "SELECT code FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": viewer_type_id},
        ).scalar()
        portrayer_code = connection.execute(
            text(
                "SELECT code FROM security.character_relationship_types "
                "WHERE character_relationship_type_id = :t"
            ),
            {"t": portrayer_type_id},
        ).scalar()
        _record(
            command="change_character_relationship",
            action="updated",
            table="membership_character_relationships",
            record_id=changed_relationship_id,
            previous_status=viewer_code,
            new_status=portrayer_code,
        )

        # 8. revoke character relationship (a second, independent character)
        other_character_id = make_character(
            connection, self.world_id, name="Audit History Other Character"
        )
        revoked_relationship_id = make_membership_character_relationship(
            connection, self.member_membership_id, other_character_id, viewer_type_id, revoked=True
        )
        _record(
            command="revoke_character_relationship",
            action="updated",
            table="membership_character_relationships",
            record_id=revoked_relationship_id,
        )

        # 9. create resource grant
        created_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            grant_capability_id,
            grantee_campaign_membership_id=self.member_membership_id,
            character_id=self.character_id,
        )
        self.created_grant_id = created_grant_id
        _record(
            command="create_resource_grant",
            action="created",
            table="resource_grants",
            record_id=created_grant_id,
        )

        # 10. revoke resource grant (a second, independent grant)
        revoked_grant_id = make_resource_grant(
            connection,
            self.campaign_id,
            grant_capability_id,
            grantee_campaign_membership_id=self.member_membership_id,
            character_id=self.character_id,
            revoked=True,
        )
        _record(
            command="revoke_resource_grant",
            action="updated",
            table="resource_grants",
            record_id=revoked_grant_id,
        )

        # 11. create invitation
        invitation_id = make_campaign_invitation(
            connection, self.campaign_id, self.admin_membership_id
        )
        _record(
            command="create_campaign_invitation",
            action="created",
            table="campaign_invitations",
            record_id=invitation_id,
        )

        # 11b. revoke invitation (a second, distinct invitation row)
        revoked_invitation_id = make_campaign_invitation(
            connection, self.campaign_id, self.admin_membership_id
        )
        connection.execute(
            text(
                "UPDATE security.campaign_invitations SET revoked_at = now() "
                "WHERE campaign_invitation_id = :i"
            ),
            {"i": revoked_invitation_id},
        )
        _record(
            command="revoke_campaign_invitation",
            action="updated",
            table="campaign_invitations",
            record_id=revoked_invitation_id,
        )

        # 12. accept invitation (actor is the accepting user, matching the
        # real command's own attribution — not the inviting admin)
        self.accepted_user_id = make_user(connection, "Audit History Accepted Member")
        accepted_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.accepted_user_id
        )
        _record(
            command="accept_campaign_invitation",
            action="updated",
            table="campaign_memberships",
            record_id=accepted_membership_id,
            actor_user_id=self.accepted_user_id,
        )

        # 13. end membership (a dedicated, closed membership)
        self.departing_user_id = make_user(connection, "Audit History Departing Member")
        self.departing_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.departing_user_id, status_code="revoked", ended=True
        )
        _record(
            command="end_campaign_membership",
            action="updated",
            table="campaign_memberships",
            record_id=self.departing_membership_id,
        )

        # A service-attributed event: audit.change_log.actor_service is set
        # *instead of* actor_user_id (dnd_ai.api.audit.record_change_log's
        # own contract — used today only by dnd_ai.api.local_auth's failed-
        # login writer, never by any of this endpoint's 13 curated
        # commands, all of which are access.manage-gated and therefore
        # always have a human actor). No curated command produces this
        # shape today, but the schema allows it (`ck_change_log_actor_
        # present` requires only "at least one of the two"), so this proves
        # dnd_ai.queries.audit_history resolves it correctly regardless —
        # forward-compatible with a future service-attributed category.
        #
        # Note on the "deleted actor" case this file does NOT test: an
        # attempt to delete a security.users row that is the *sole* actor
        # identifier of an existing audit.change_log row (actor_service
        # NULL) is itself rejected by ck_change_log_actor_present via the
        # ON DELETE SET NULL cascade — confirmed by exercising it directly
        # against this fixture during development, which raised
        # psycopg.errors.CheckViolation rather than orphaning the row. For
        # every one of this endpoint's 13 curated commands, "actor_label
        # falls back to a fixed placeholder because the actor account was
        # deleted" is therefore not merely unlikely but provably
        # unreachable while any referencing audit.change_log row survives
        # — see docs/AUDIT_HISTORY_API.md §6 and
        # tests/unit/test_audit_history_query.py (which exercises
        # `_resolve_actor`'s "unknown"/placeholder branches directly, as
        # pure defensive code with no live database path to reach them).
        record_change_log(
            connection,
            change_action_code="created",
            schema_name="security",
            table_name="campaign_invitations",
            record_id=make_campaign_invitation(
                connection, self.campaign_id, self.admin_membership_id
            ),
            entity_id=None,
            world_id=self.world_id,
            actor_user_id=None,
            actor_service="test.audit_history_fixture_service",
            correlation_id=None,
            command_name="create_campaign_invitation",
            event_id=None,
        )

        # --- Campaign B: isolation target, on the SAME timeline ---
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Audit History Campaign B"
        )
        self.other_admin_user_id, self.other_admin_membership_id = _make_admin(
            self.other_campaign_id, "Audit History Admin B"
        )
        self.other_member_user_id = make_user(connection, "Audit History Member B")
        other_member_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.other_member_user_id
        )
        record_change_log(
            connection,
            change_action_code="created",
            schema_name="security",
            table_name="campaign_memberships",
            record_id=other_member_membership_id,
            entity_id=None,
            world_id=self.world_id,
            actor_user_id=self.other_admin_user_id,
            correlation_id=None,
            command_name="add_campaign_member",
            event_id=None,
        )

        # --- Campaign C: no audit history at all ---
        self.empty_campaign_id = make_campaign(
            connection, self.timeline_id, "Audit History Campaign C"
        )
        self.empty_admin_user_id, self.empty_admin_membership_id = _make_admin(
            self.empty_campaign_id, "Audit History Admin C"
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"audit-history-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM audit.change_log WHERE world_id = :w
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.resource_grants WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM security.capabilities WHERE code LIKE 'test.audit_history_grant_%'")
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_character_relationships WHERE campaign_membership_id IN (
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
                "DELETE FROM security.character_relationship_types WHERE code LIKE 'viewer_%' "
                "OR code LIKE 'portrayer_%'"
            )
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_invitations WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
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
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
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
                    fixture.member_user_id,
                    fixture.accepted_user_id,
                    fixture.departing_user_id,
                    fixture.other_admin_user_id,
                    fixture.other_member_user_id,
                    fixture.empty_admin_user_id,
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


def _url(campaign_id: uuid.UUID, **params: object) -> str:
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
        response = client.get(_url(f.campaign_id))
    assert response.status_code == 404


def test_a_member_without_access_manage_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_url(f.campaign_id))
    assert response.status_code == 403


def test_an_unknown_campaign_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(uuid.uuid4()))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Successful reads, ordering, categories
# ---------------------------------------------------------------------------


def test_authorized_admin_reads_the_full_curated_history(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, limit=100))
    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    # 15 events recorded for campaign A (14 numbered + 1 ghost-actor event).
    assert len(body["items"]) == 15
    categories = {item["category"] for item in body["items"]}
    assert categories == {
        "membership",
        "role",
        "character_relationship",
        "resource_grant",
        "invitation",
        "campaign",
    }
    assert any(item["action_label"] == "Invitation revoked" for item in body["items"])


def test_ordering_is_deterministic_newest_first_under_a_real_timestamp_tie(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    # Every row in the fixture was written inside one transaction, so
    # PostgreSQL's frozen now() gives them all the identical recorded_at —
    # a genuine tie. Only the change_log_id tie-breaker can order them.
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, limit=100))
    body = response.json()
    ids = [item["change_log_id"] for item in body["items"]]
    assert ids == sorted(ids, reverse=True)
    timestamps = {item["occurred_at"] for item in body["items"]}
    assert len(timestamps) == 1, "fixture setup did not produce the expected timestamp tie"


def test_pagination_is_stable_across_the_timestamp_tie(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        page1 = client.get(_url(f.campaign_id, limit=5)).json()
        assert page1["next_cursor"] is not None
        assert len(page1["items"]) == 5

        page2 = client.get(_url(f.campaign_id, limit=5, cursor=page1["next_cursor"])).json()
        assert len(page2["items"]) == 5

        page3 = client.get(_url(f.campaign_id, limit=5, cursor=page2["next_cursor"])).json()
        assert page3["next_cursor"] is None
        assert len(page3["items"]) == 5  # 15 total - 5 - 5

    all_ids = [i["change_log_id"] for i in page1["items"] + page2["items"] + page3["items"]]
    assert len(all_ids) == len(set(all_ids)), "pagination must never repeat a row"
    assert all_ids == sorted(all_ids, reverse=True)

    with client_factory(f.admin_user_id) as client:
        full = client.get(_url(f.campaign_id, limit=100)).json()
    assert all_ids == [i["change_log_id"] for i in full["items"]]


@pytest.mark.parametrize(
    ("category", "expected_commands"),
    [
        ("membership", {"add_campaign_member", "end_campaign_membership"}),
        ("role", {"assign_membership_role", "revoke_membership_role", "change_membership_role"}),
        (
            "character_relationship",
            {
                "grant_character_relationship",
                "change_character_relationship",
                "revoke_character_relationship",
            },
        ),
        ("resource_grant", {"create_resource_grant", "revoke_resource_grant"}),
        (
            "invitation",
            {
                "create_campaign_invitation",
                "accept_campaign_invitation",
                "revoke_campaign_invitation",
            },
        ),
        ("campaign", {"create_campaign"}),
    ],
)
def test_category_filter_returns_only_that_category(
    client_factory: Callable[[uuid.UUID], TestClient],
    f: Fixture,
    category: str,
    expected_commands: set[str],
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, category=category, limit=100))
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) >= 1
    for item in body["items"]:
        assert item["category"] == category


def test_actor_filter_narrows_to_that_actor(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, actor_user_id=str(f.accepted_user_id), limit=100))
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["actor_label"] != str(f.accepted_user_id)


# ---------------------------------------------------------------------------
# Empty history and cross-campaign isolation
# ---------------------------------------------------------------------------


def test_a_campaign_with_no_history_returns_an_empty_page(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.empty_admin_user_id) as client:
        response = client.get(_url(f.empty_campaign_id))
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_campaign_b_never_sees_campaign_a_history_despite_sharing_a_timeline(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.other_admin_user_id) as client:
        response = client.get(_url(f.other_campaign_id, limit=100))
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["category"] == "membership"
    assert body["items"][0]["target_label"] == "Audit History Member B"


def test_campaign_a_never_sees_campaign_b_history(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, limit=100))
    body = response.json()
    change_log_ids = {item["change_log_id"] for item in body["items"]}
    assert len(change_log_ids) == 15
    # Every change_log_id here must have been produced for campaign A —
    # cross-checked structurally by re-querying campaign B and confirming
    # no overlap in ids at all.
    with client_factory(f.other_admin_user_id) as client:
        other_body = client.get(_url(f.other_campaign_id, limit=100)).json()
    other_ids = {item["change_log_id"] for item in other_body["items"]}
    assert change_log_ids.isdisjoint(other_ids)


# ---------------------------------------------------------------------------
# Page-size bounds and malformed filters
# ---------------------------------------------------------------------------


def test_limit_zero_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, limit=0))
    assert response.status_code == 422


def test_limit_over_the_maximum_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, limit=101))
    assert response.status_code == 422


def test_an_unrecognized_category_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, category="not_a_real_category"))
    assert response.status_code == 422


def test_a_malformed_actor_user_id_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, actor_user_id="not-a-uuid"))
    assert response.status_code == 422


def test_a_malformed_datetime_filter_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, occurred_from="not-a-date"))
    assert response.status_code == 422


def test_a_malformed_cursor_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, cursor="not-a-real-cursor"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_a_cursor_from_a_different_endpoint_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    foreign_cursor = (
        base64.urlsafe_b64encode(
            json.dumps([1, "world_entities", ["x", str(uuid.uuid4())]]).encode()
        )
        .decode()
        .rstrip("=")
    )
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, cursor=foreign_cursor))
    assert response.status_code == 422


def test_an_inverted_date_range_yields_an_empty_page_not_an_error(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(
            _url(
                f.campaign_id,
                occurred_from="2099-01-01T00:00:00Z",
                occurred_to="2000-01-01T00:00:00Z",
            )
        )
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


# ---------------------------------------------------------------------------
# Safe-presentation projection: sensitive metadata never leaks
# ---------------------------------------------------------------------------


def test_changed_fields_and_other_unsafe_columns_never_appear_in_the_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        response = client.get(_url(f.campaign_id, limit=100))
    raw_body = response.text
    assert _SENSITIVE_MARKER not in raw_body
    assert "secret_token" not in raw_body
    assert "changed_fields" not in raw_body
    assert "correlation_id" not in raw_body
    assert "causation_id" not in raw_body


def test_no_raw_uuid_is_ever_the_only_actor_or_target_label(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.admin_user_id) as client:
        body = client.get(_url(f.campaign_id, limit=100)).json()
    for item in body["items"]:
        try:
            uuid.UUID(item["actor_label"])
        except ValueError:
            pass
        else:
            raise AssertionError(f"actor_label was a raw UUID: {item}")
        if item["target_label"] is not None:
            try:
                uuid.UUID(item["target_label"])
            except ValueError:
                pass
            else:
                raise AssertionError(f"target_label was a raw UUID: {item}")


# ---------------------------------------------------------------------------
# Actor/target fidelity: current name only, service actor attribution
# ---------------------------------------------------------------------------


def test_a_service_attributed_event_resolves_the_service_label_not_a_uuid(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    # No curated command sets actor_service today (all 13 are access.manage-
    # gated and therefore always have a human actor) — this row was written
    # directly by the fixture to prove the query resolves this schema-legal
    # shape correctly regardless. See the fixture's own comment for why the
    # "actor account was deleted" case is not separately tested here: it is
    # provably unreachable (`ck_change_log_actor_present` blocks the delete
    # outright) rather than merely untested — covered instead by
    # tests/unit/test_audit_history_query.py against the pure fallback logic.
    with client_factory(f.admin_user_id) as client:
        body = client.get(_url(f.campaign_id, category="invitation", limit=100)).json()
    service_items = [i for i in body["items"] if i["actor_type"] == "service"]
    assert len(service_items) == 1
    assert service_items[0]["actor_label"] == "test.audit_history_fixture_service"


def test_a_renamed_account_shows_its_current_name_not_the_historical_one(
    postgres_engine: Engine,
    client_factory: Callable[[uuid.UUID], TestClient],
    f: Fixture,
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("UPDATE security.users SET display_name = :n WHERE user_id = :u"),
            {"n": "Renamed Admin (current)", "u": f.admin_user_id},
        )
    with client_factory(f.admin_user_id) as client:
        body = client.get(_url(f.campaign_id, category="campaign", limit=100)).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["actor_label"] == "Renamed Admin (current)"


def test_a_renamed_character_target_shows_its_current_name(
    postgres_engine: Engine,
    client_factory: Callable[[uuid.UUID], TestClient],
    f: Fixture,
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text("UPDATE core.entities SET canonical_name = :n WHERE entity_id = :c"),
            {"n": "Renamed Character (current)", "c": f.character_id},
        )
    with client_factory(f.admin_user_id) as client:
        body = client.get(_url(f.campaign_id, category="character_relationship", limit=100)).json()
    matching = [i for i in body["items"] if i["target_label"] == "Renamed Character (current)"]
    assert len(matching) >= 1
