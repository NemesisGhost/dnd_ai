"""Tests for `dnd_ai.api.memberships`/`.access_overview`'s Phase 13E-B
checkpoint 3 additions: the eligible-account lookup
(`GET /campaigns/{campaign_id}/eligible-accounts`), the hardened add-member
mutation (`POST /campaigns/{campaign_id}/memberships`, now requiring an
initial `role_id`), and the new remove-member mutation
(`POST /campaigns/{campaign_id}/memberships/{campaign_membership_id}/end`).

Mirrors `tests/database/test_api_memberships.py`'s shape:
`get_authenticated_user_id` is overridden directly, exercising campaign-
capability enforcement and the commands' own HTTP wiring, not OIDC token
verification. See `dnd_ai.commands.memberships.add_campaign_member`/
`.end_campaign_membership` and `dnd_ai.queries.access_overview.
find_eligible_campaign_account` for the full documented contract each test
below checks.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_external_identity,
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
        self.campaign_id = make_campaign(connection, self.timeline_id, "Lifecycle Campaign")
        # "pending" sidesteps the active-campaign access-manager retention
        # invariant — this campaign never gets an owning membership of its
        # own, matching test_api_memberships.py's identical Fixture
        # pattern for its own other_campaign_id.
        self.other_campaign_id = make_campaign(
            connection,
            self.timeline_id,
            "Lifecycle Other Campaign",
            lifecycle_status_code="pending",
        )
        self.pending_campaign_id = make_campaign(
            connection,
            self.timeline_id,
            "Lifecycle Pending Campaign",
            lifecycle_status_code="pending",
        )

        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        self.manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.manager_role_id, access_manage_id)
        make_role_capability(connection, self.manager_role_id, view_capability_id)

        self.player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.player_role_id, view_capability_id)

        self.second_player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player2_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, self.second_player_role_id, view_capability_id)

        # A system-template role (campaign_id NULL) — usable by any campaign.
        self.system_role_id = make_role(
            connection, campaign_id=None, code=f"system_{uuid.uuid4().hex[:8]}"
        )

        # Scoped to the *other* campaign — not usable by self.campaign_id.
        self.foreign_role_id = make_role(
            connection, campaign_id=self.other_campaign_id, code=f"foreign_{uuid.uuid4().hex[:8]}"
        )

        self.inactive_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"inactive_{uuid.uuid4().hex[:8]}"
        )
        connection.execute(
            text("UPDATE security.roles SET is_active = false WHERE role_id = :r"),
            {"r": self.inactive_role_id},
        )

        self.manager_user_id = make_user(connection, "Lifecycle Manager")
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.manager_user_id
        )
        self.manager_membership_role_id = make_membership_role(
            connection, self.manager_membership_id, self.manager_role_id
        )

        # A second manager — the second qualifying access.manage holder
        # every "safe self-removal"/"safe self-revocation" scenario needs.
        self.second_manager_user_id = make_user(connection, "Lifecycle Second Manager")
        self.second_manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.second_manager_user_id
        )
        self.second_manager_membership_role_id = make_membership_role(
            connection, self.second_manager_membership_id, self.manager_role_id
        )

        self.capless_user_id = make_user(connection, "Lifecycle Capless")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Lifecycle Outsider")

        # --- Eligible-account lookup fixtures ---

        self.eligible_login_name = f"eligible.{uuid.uuid4().hex[:8]}"
        self.eligible_user_id = make_user(connection, "Lifecycle Eligible")
        make_external_identity(
            connection,
            self.eligible_user_id,
            issuer=LOCAL_AUTH_ISSUER,
            subject=self.eligible_login_name,
        )

        # A local login already an active member of self.campaign_id — must
        # never appear as eligible there (even though it exists, is
        # platform-active, and has a local login).
        self.already_member_login_name = f"already.{uuid.uuid4().hex[:8]}"
        self.already_member_user_id = make_user(connection, "Lifecycle Already Member")
        make_external_identity(
            connection,
            self.already_member_user_id,
            issuer=LOCAL_AUTH_ISSUER,
            subject=self.already_member_login_name,
        )
        self.already_member_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.already_member_user_id
        )

        # A platform-disabled account with a local login — must never
        # appear as eligible anywhere.
        self.disabled_login_name = f"disabled.{uuid.uuid4().hex[:8]}"
        self.disabled_user_id = make_user(connection, "Lifecycle Disabled", status_code="inactive")
        make_external_identity(
            connection,
            self.disabled_user_id,
            issuer=LOCAL_AUTH_ISSUER,
            subject=self.disabled_login_name,
        )

        # --- Add-member fixtures ---

        # Already has an open membership in self.campaign_id — the target
        # of a duplicate-open-membership rejection test.
        self.duplicate_target_login_name = f"dup.{uuid.uuid4().hex[:8]}"
        self.duplicate_target_user_id = make_user(connection, "Lifecycle Duplicate Target")
        make_external_identity(
            connection,
            self.duplicate_target_user_id,
            issuer=LOCAL_AUTH_ISSUER,
            subject=self.duplicate_target_login_name,
        )
        make_campaign_membership(connection, self.campaign_id, self.duplicate_target_user_id)

        # --- Remove-member fixtures ---

        # An ordinary member holding two independent roles — proves both
        # get revoked, and neither an unrelated role nor an unrelated
        # membership is touched.
        self.member_user_id = make_user(connection, "Lifecycle Removable Member")
        self.member_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.member_user_id
        )
        self.member_membership_role_id_1 = make_membership_role(
            connection, self.member_membership_id, self.player_role_id
        )
        self.member_membership_role_id_2 = make_membership_role(
            connection, self.member_membership_id, self.second_player_role_id
        )

        # A membership belonging only to the *other* campaign — proves
        # removal never touches a sibling campaign's own memberships.
        self.sibling_user_id = make_user(connection, "Lifecycle Sibling")
        self.sibling_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.sibling_user_id
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"membership-lifecycle-{uuid.uuid4().hex[:8]}")
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
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                ) OR role_id = :system_role
            """),
            {"t": fixture.timeline_id, "system_role": fixture.system_role_id},
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
            text("DELETE FROM security.roles WHERE role_id = :system_role"),
            {"system_role": fixture.system_role_id},
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
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.manager_user_id,
                    fixture.second_manager_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.eligible_user_id,
                    fixture.already_member_user_id,
                    fixture.disabled_user_id,
                    fixture.duplicate_target_user_id,
                    fixture.member_user_id,
                    fixture.sibling_user_id,
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


def _eligible_accounts_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/eligible-accounts"


def _memberships_url(f: Fixture, campaign_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/memberships"


def _end_url(
    f: Fixture, membership_id: uuid.UUID | None = None, campaign_id: uuid.UUID | None = None
) -> str:
    return (
        f"/campaigns/{campaign_id or f.campaign_id}/memberships/"
        f"{membership_id or f.member_membership_id}/end"
    )


# ---------------------------------------------------------------------------
# find_eligible_campaign_account (GET .../eligible-accounts)
# ---------------------------------------------------------------------------


def test_an_eligible_account_is_found_by_exact_login_name(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.get(
            _eligible_accounts_url(f), params={"login_name": f.eligible_login_name}
        )
    assert response.status_code == 200, response.text
    account = response.json()["account"]
    assert account is not None
    assert account["user_id"] == str(f.eligible_user_id)
    assert account["display_name"] == "Lifecycle Eligible"


def test_the_lookup_is_case_and_whitespace_normalized(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.get(
            _eligible_accounts_url(f),
            params={"login_name": f"  {f.eligible_login_name.upper()}  "},
        )
    assert response.status_code == 200, response.text
    account = response.json()["account"]
    assert account is not None
    assert account["user_id"] == str(f.eligible_user_id)


def test_a_non_member_is_denied_the_eligible_account_lookup(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(
            _eligible_accounts_url(f), params={"login_name": f.eligible_login_name}
        )
    assert response.status_code == 404


def test_a_member_without_access_manage_is_denied_the_eligible_account_lookup(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(
            _eligible_accounts_url(f), params={"login_name": f.eligible_login_name}
        )
    assert response.status_code == 403


def test_an_already_active_member_is_excluded_from_eligibility(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.get(
            _eligible_accounts_url(f), params={"login_name": f.already_member_login_name}
        )
    assert response.status_code == 200, response.text
    assert response.json()["account"] is None


def test_a_platform_disabled_account_is_excluded_from_eligibility(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.get(
            _eligible_accounts_url(f), params={"login_name": f.disabled_login_name}
        )
    assert response.status_code == 200, response.text
    assert response.json()["account"] is None


def test_an_unknown_login_name_returns_no_match_without_disclosure(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.get(
            _eligible_accounts_url(f), params={"login_name": f"nonexistent.{uuid.uuid4().hex}"}
        )
    assert response.status_code == 200, response.text
    assert response.json()["account"] is None


def test_an_account_eligible_in_one_campaign_is_not_eligible_in_the_campaign_it_already_joined(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    # already_member_user_id has no membership in f.other_campaign_id at
    # all — eligible there, even though it is already a member of
    # f.campaign_id.
    with client_factory(f.manager_user_id) as client:
        response = client.get(
            _eligible_accounts_url(f, f.other_campaign_id),
            params={"login_name": f.already_member_login_name},
        )
    assert response.status_code == 404  # manager_user_id is not a member of other_campaign_id


def test_a_login_name_over_the_bound_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.get(_eligible_accounts_url(f), params={"login_name": "x" * 65})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# add_campaign_member (POST .../memberships)
# ---------------------------------------------------------------------------


def test_adding_a_member_with_an_initial_role_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.player_role_id)},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    membership_id = uuid.UUID(body["campaign_membership_id"])
    membership_role_id = uuid.UUID(body["membership_role_id"])

    with postgres_engine.connect() as verify:
        membership_row = verify.execute(
            text("""
                SELECT cm.user_id, cm.ended_at, ms.code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": membership_id},
        ).one()
        assert membership_row.user_id == f.eligible_user_id
        assert membership_row.ended_at is None
        assert membership_row.code == "active"

        role_row = verify.execute(
            text("""
                SELECT campaign_membership_id, role_id, revoked_at
                FROM security.membership_roles WHERE membership_role_id = :r
            """),
            {"r": membership_role_id},
        ).one()
        assert role_row.campaign_membership_id == membership_id
        assert role_row.role_id == f.player_role_id
        assert role_row.revoked_at is None


def test_adding_a_member_with_a_system_template_role_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.system_role_id)},
        )
    assert response.status_code == 201, response.text


def test_a_non_member_cannot_add_a_campaign_member(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.player_role_id)},
        )
    assert response.status_code == 404


def test_a_member_without_access_manage_cannot_add_a_campaign_member(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.player_role_id)},
        )
    assert response.status_code == 403


def test_adding_a_member_to_a_non_active_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    # The pending campaign needs its own access-manager membership (with a
    # role actually scoped to it) for the caller to reach the command at
    # all.
    with postgres_engine.begin() as connection:
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        pending_role_id = make_role(
            connection,
            campaign_id=f.pending_campaign_id,
            code=f"pending_manager_{uuid.uuid4().hex[:8]}",
        )
        make_role_capability(connection, pending_role_id, access_manage_id)
        pending_manager_membership_id = make_campaign_membership(
            connection, f.pending_campaign_id, f.manager_user_id
        )
        make_membership_role(connection, pending_manager_membership_id, pending_role_id)

    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f, f.pending_campaign_id),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.system_role_id)},
        )
    assert response.status_code == 409, response.text

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": f.pending_campaign_id, "u": f.eligible_user_id},
        ).scalar()
        assert count == 0


def test_adding_a_platform_disabled_account_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.disabled_user_id), "role_id": str(f.player_role_id)},
        )
    assert response.status_code == 404, response.text


def test_adding_a_nonexistent_account_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(uuid.uuid4()), "role_id": str(f.player_role_id)},
        )
    assert response.status_code == 404, response.text


def test_adding_an_account_that_already_has_an_open_membership_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={
                "user_id": str(f.duplicate_target_user_id),
                "role_id": str(f.player_role_id),
            },
        )
    assert response.status_code == 409, response.text


def test_adding_a_member_with_a_role_scoped_to_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.foreign_role_id)},
        )
    assert response.status_code == 404, response.text


def test_adding_a_member_with_an_inactive_role_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.inactive_role_id)},
        )
    assert response.status_code == 404, response.text


def test_a_rejected_add_leaves_no_membership_or_role_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.inactive_role_id)},
        )
    assert response.status_code == 404

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": f.campaign_id, "u": f.eligible_user_id},
        ).scalar()
        assert count == 0


def test_a_sequential_replay_of_add_member_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"add-member-{uuid.uuid4().hex[:8]}"
    body = {"user_id": str(f.eligible_user_id), "role_id": str(f.player_role_id)}
    with client_factory(f.manager_user_id) as client:
        first = client.post(_memberships_url(f), json=body, headers={"Idempotency-Key": key})
        second = client.post(_memberships_url(f), json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_id = :c AND user_id = :u"
            ),
            {"c": f.campaign_id, "u": f.eligible_user_id},
        ).scalar()
        assert count == 1


def test_reusing_an_add_member_idempotency_key_for_a_different_payload_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    key = f"add-member-{uuid.uuid4().hex[:8]}"
    with client_factory(f.manager_user_id) as client:
        first = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.player_role_id)},
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.system_role_id)},
            headers={"Idempotency-Key": key},
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text


def test_audit_change_log_records_both_the_membership_and_role_creation(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _memberships_url(f),
            json={"user_id": str(f.eligible_user_id), "role_id": str(f.player_role_id)},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    membership_id = uuid.UUID(body["campaign_membership_id"])
    membership_role_id = uuid.UUID(body["membership_role_id"])

    with postgres_engine.connect() as verify:
        membership_audit = verify.execute(
            text("""
                SELECT ca.code AS action_code, cl.actor_user_id
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.table_name = 'campaign_memberships' AND cl.record_id = :record
            """),
            {"record": membership_id},
        ).one()
        assert membership_audit.action_code == "created"
        assert membership_audit.actor_user_id == f.manager_user_id

        role_audit = verify.execute(
            text("""
                SELECT ca.code AS action_code, cl.actor_user_id
                FROM audit.change_log cl
                JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                WHERE cl.table_name = 'membership_roles' AND cl.record_id = :record
            """),
            {"record": membership_role_id},
        ).one()
        assert role_audit.action_code == "created"
        assert role_audit.actor_user_id == f.manager_user_id

        serialized = str(dict(membership_audit._mapping)) + str(dict(role_audit._mapping))
        assert "password" not in serialized.lower()
        assert "csrf" not in serialized.lower()
        assert "token" not in serialized.lower()


# ---------------------------------------------------------------------------
# end_campaign_membership (POST .../memberships/{id}/end)
# ---------------------------------------------------------------------------


def test_ending_a_membership_succeeds_and_revokes_its_roles(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(_end_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["campaign_membership_id"] == str(f.member_membership_id)

    with postgres_engine.connect() as verify:
        membership_row = verify.execute(
            text("""
                SELECT ended_at, ended_by_membership_id, ms.code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE campaign_membership_id = :m
            """),
            {"m": f.member_membership_id},
        ).one()
        assert membership_row.ended_at is not None
        assert membership_row.ended_by_membership_id == f.manager_membership_id
        assert membership_row.code == "revoked"

        role_rows = verify.execute(
            text(
                "SELECT membership_role_id, revoked_at FROM security.membership_roles "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": f.member_membership_id},
        ).all()
        assert len(role_rows) == 2
        assert all(row.revoked_at is not None for row in role_rows)


def test_ending_a_membership_does_not_affect_a_sibling_campaign(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(_end_url(f))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        sibling_ended_at = verify.execute(
            text(
                "SELECT ended_at FROM security.campaign_memberships WHERE campaign_membership_id = :m"
            ),
            {"m": f.sibling_membership_id},
        ).scalar()
        assert sibling_ended_at is None


def test_ending_a_membership_from_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(
            _end_url(f, membership_id=f.sibling_membership_id, campaign_id=f.campaign_id)
        )
    assert response.status_code == 404


def test_ending_an_unknown_membership_is_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(_end_url(f, membership_id=uuid.uuid4()))
    assert response.status_code == 404


def test_a_non_member_cannot_end_a_membership(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.post(_end_url(f))
    assert response.status_code == 404


def test_a_member_without_access_manage_cannot_end_a_membership(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.post(_end_url(f))
    assert response.status_code == 403


def test_ending_an_already_ended_membership_is_a_harmless_no_op(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.manager_user_id) as client:
        first = client.post(_end_url(f))
        second = client.post(_end_url(f))
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("""
                SELECT count(*) FROM audit.change_log
                WHERE table_name = 'campaign_memberships' AND record_id = :m
            """),
            {"m": f.member_membership_id},
        ).scalar()
        assert count == 1


def test_ending_the_last_manager_membership_on_an_active_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    # Remove the second manager's own manager role first, leaving
    # manager_user_id as the campaign's sole access.manage holder.
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() "
                "WHERE membership_role_id = :r"
            ),
            {"r": f.second_manager_membership_role_id},
        )

    with client_factory(f.manager_user_id) as client:
        response = client.post(_end_url(f, membership_id=f.manager_membership_id))
    assert response.status_code == 400, response.text

    with postgres_engine.connect() as verify:
        ended_at = verify.execute(
            text(
                "SELECT ended_at FROM security.campaign_memberships WHERE campaign_membership_id = :m"
            ),
            {"m": f.manager_membership_id},
        ).scalar()
        assert ended_at is None


def test_self_removal_succeeds_when_another_manager_remains(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(_end_url(f, membership_id=f.manager_membership_id))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        ended_at = verify.execute(
            text(
                "SELECT ended_at FROM security.campaign_memberships WHERE campaign_membership_id = :m"
            ),
            {"m": f.manager_membership_id},
        ).scalar()
        assert ended_at is not None


def test_a_removed_member_loses_access_on_the_next_authoritative_request(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.manager_user_id) as manager_client:
        end_response = manager_client.post(_end_url(f))
    assert end_response.status_code == 200, end_response.text

    with client_factory(f.member_user_id) as member_client:
        overview_response = member_client.get(f"/campaigns/{f.campaign_id}/access-overview")
        session_response = member_client.get("/auth/session")
    assert overview_response.status_code == 404
    assert session_response.status_code == 200, session_response.text
    campaign_ids = {campaign["campaign_id"] for campaign in session_response.json()["campaigns"]}
    assert str(f.campaign_id) not in campaign_ids


def test_a_sequential_replay_of_end_membership_returns_the_original_response(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    key = f"end-membership-{uuid.uuid4().hex[:8]}"
    with client_factory(f.manager_user_id) as client:
        first = client.post(_end_url(f), headers={"Idempotency-Key": key})
        second = client.post(_end_url(f), headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("""
                SELECT count(*) FROM audit.change_log
                WHERE table_name = 'campaign_memberships' AND record_id = :m
            """),
            {"m": f.member_membership_id},
        ).scalar()
        assert count == 1


def test_audit_change_log_records_the_removal_without_secrets(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with client_factory(f.manager_user_id) as client:
        response = client.post(_end_url(f))
    assert response.status_code == 200, response.text

    with postgres_engine.connect() as verify:
        row = (
            verify.execute(
                text("""
                    SELECT ca.code AS action_code, cl.previous_status, cl.new_status,
                           cl.changed_fields, cl.actor_user_id
                    FROM audit.change_log cl
                    JOIN audit.change_actions ca ON ca.change_action_id = cl.change_action_id
                    WHERE cl.table_name = 'campaign_memberships' AND cl.record_id = :m
                """),
                {"m": f.member_membership_id},
            )
            .mappings()
            .one()
        )
        assert row["action_code"] == "updated"
        assert row["actor_user_id"] == f.manager_user_id
        assert row["previous_status"] == "active"
        assert row["new_status"] == "revoked"
        assert str(f.member_membership_role_id_1) in str(row["changed_fields"])
        assert str(f.member_membership_role_id_2) in str(row["changed_fields"])
        serialized = str(row)
        assert "password" not in serialized.lower()
        assert "csrf" not in serialized.lower()
        assert "token" not in serialized.lower()
