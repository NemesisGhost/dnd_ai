"""Tests for `dnd_ai.api.campaigns` — the campaign-creation bootstrap
command endpoint (docs/PLAN.md Phase 10 "Still to come" list).

Covers: any authenticated user may create a campaign (no pre-existing
membership needed, unlike every other command endpoint), the created
campaign's own retained-access-manager invariant (proven indirectly: a
201 response is only possible once `tr_campaigns_retain_access_manager`'s
deferred check passes at commit), a nonexistent timeline, a nonexistent
ruleset version, and a ruleset version belonging to a different world's
ruleset family.

Also covers the High authorization defect fixed by migration 085 (`dnd_ai.
commands.campaigns`'s own module docstring has the full defect/fix
narrative): the creator's immediate `campaign.view`/`canon.edit` access
with no direct `security.roles`/`.role_capabilities` write of any kind
(`test_the_creator_immediately_passes_campaign_view_and_can_perform_a_
canon_edit_command`), that an ordinary accepted member does not inherit
any of the owner's capabilities
(`test_an_accepted_ordinary_member_does_not_inherit_owner_capabilities`),
that the access-manager retention invariant still blocks revoking a sole
owner's own role
(`test_the_sole_owners_own_role_cannot_be_revoked_from_an_active_campaign`),
that campaign creation is atomic on failure
(`test_campaign_creation_is_atomic_when_membership_creation_fails`), and
that reusing a timeline another campaign already uses is allowed (the
documented "shared, reusable world content" policy) without leaking either
campaign's own security state into the other
(`test_a_second_campaign_on_an_already_used_timeline_succeeds_and_cannot_
see_the_first_campaigns_access`).
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
    make_character,
    make_location,
    make_ruleset_version_for_world,
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
        self.ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)

        other_world_id = make_world(connection, slug=f"{slug}-other")
        self.foreign_ruleset_version_id = make_ruleset_version_for_world(connection, other_world_id)
        self.other_world_id = other_world_id

        self.creator_user_id = make_user(connection, "Campaign API Creator")
        self.second_user_id = make_user(connection, "Campaign API Second User")

        # Content for the representative canon.edit command
        # (dnd_ai.commands.movement.enter_location) — content authoring,
        # not a security write; every Phase 10 test's fixture builds its
        # own world content the same way.
        self.character_id = make_character(connection, self.world_id, name="Owner Test Subject")
        self.location_id = make_location(connection, self.world_id, name="Owner Test Location")
        self.world_time_id = make_world_time(connection, self.world_id, 10)


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"campaign-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM campaign.character_location_history WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
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
                DELETE FROM security.idempotent_requests WHERE campaign_id IN (
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
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {"users": [fixture.creator_user_id, fixture.second_user_id]},
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


# ---------------------------------------------------------------------------
# Migration 085: the creator's functional-owner access, established
# atomically by create_campaign alone — no direct security.roles/.
# role_capabilities write, and no separate role-assignment call.
# ---------------------------------------------------------------------------


def test_the_creator_immediately_passes_campaign_view_and_can_perform_a_canon_edit_command(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """Regression test for the High authorization defect `dnd_ai.commands.
    campaigns`'s own module docstring documents: before migration 085,
    `campaign_owner` carried only `access.manage`, so a campaign's own
    creator could not pass a `campaign.view` gate or perform a `canon.edit`
    command anywhere in this codebase. No direct `security.roles`/`.
    role_capabilities` write happens anywhere in this test — only
    `POST /campaigns` itself, then two ordinary capability-gated calls."""
    with client_factory(f.creator_user_id) as client:
        create_response = client.post("/campaigns", json=_body(f))
        assert create_response.status_code == 201, create_response.text
        campaign_id = uuid.UUID(create_response.json()["campaign_id"])

        # campaign.view: GET /campaigns/{id}/summary requires nothing more
        # than an authorizing membership plus that one capability.
        summary_response = client.get(f"/campaigns/{campaign_id}/summary")
        assert summary_response.status_code == 200, summary_response.text

        # canon.edit: a representative command mutation — recording where a
        # character currently stands (dnd_ai.commands.movement.
        # enter_location), the same capability every other command router
        # in this codebase gates its own canon-mutating routes on.
        move_response = client.post(
            f"/campaigns/{campaign_id}/characters/{f.character_id}/location",
            json={"world_time_id": str(f.world_time_id), "location_id": str(f.location_id)},
        )
    assert move_response.status_code == 200, move_response.text
    assert move_response.json()["moved"] is True


def test_an_accepted_ordinary_member_does_not_inherit_owner_capabilities(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """An invited member who accepts via `dnd_ai.commands.
    campaign_invitations.accept_campaign_invitation` gets an ordinary,
    role-less `security.campaign_memberships` row — never a
    `campaign_owner` grant, which `create_campaign` assigns exactly once,
    to its own creator, with no other code path assigning it to anyone
    else. The accepted member therefore holds none of `campaign_owner`'s
    capabilities and is rejected by both an `access.manage`-gated command
    and a `canon.edit`-gated one."""
    with client_factory(f.creator_user_id) as owner_client:
        create_response = owner_client.post("/campaigns", json=_body(f))
        assert create_response.status_code == 201, create_response.text
        campaign_id = uuid.UUID(create_response.json()["campaign_id"])

        invite_response = owner_client.post(f"/campaigns/{campaign_id}/invitations", json={})
        assert invite_response.status_code == 201, invite_response.text
        token = invite_response.json()["token"]

    with client_factory(f.second_user_id) as member_client:
        accept_response = member_client.post("/campaign-invitations/accept", json={"token": token})
        assert accept_response.status_code == 200, accept_response.text
        assert accept_response.json()["campaign_id"] == str(campaign_id)

        # access.manage: the accepted member cannot invite anyone else.
        second_invite_response = member_client.post(
            f"/campaigns/{campaign_id}/invitations", json={}
        )
        assert second_invite_response.status_code == 403, second_invite_response.text

        # canon.edit: the accepted member cannot move a character either.
        move_response = member_client.post(
            f"/campaigns/{campaign_id}/characters/{f.character_id}/location",
            json={"world_time_id": str(f.world_time_id), "location_id": str(f.location_id)},
        )
    assert move_response.status_code == 403, move_response.text


def test_the_sole_owners_own_role_cannot_be_revoked_from_an_active_campaign(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The §22 rule 19 access-manager retention invariant
    (`security.assert_campaign_retains_access_manager`) still blocks
    removing a campaign's only `access.manage` holder after migration 085 —
    extending `campaign_owner` with two more capabilities changes nothing
    about how `access.manage` itself is granted or revoked."""
    with client_factory(f.creator_user_id) as client:
        create_response = client.post("/campaigns", json=_body(f))
        assert create_response.status_code == 201, create_response.text
        campaign_id = uuid.UUID(create_response.json()["campaign_id"])
        campaign_membership_id = uuid.UUID(create_response.json()["campaign_membership_id"])

        with postgres_engine.connect() as verify:
            membership_role_id = verify.execute(
                text(
                    "SELECT membership_role_id FROM security.membership_roles "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": campaign_membership_id},
            ).scalar_one()

        revoke_response = client.post(
            f"/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/revoke"
        )
    assert revoke_response.status_code == 400, revoke_response.text

    with postgres_engine.connect() as verify:
        revoked_at = verify.execute(
            text("SELECT revoked_at FROM security.membership_roles WHERE membership_role_id = :mr"),
            {"mr": membership_role_id},
        ).scalar_one()
        assert revoked_at is None


def test_campaign_creation_is_atomic_when_membership_creation_fails(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`create_campaign` writes `campaign.campaigns`, `security.
    campaign_memberships`, and `security.membership_roles` in one request
    transaction (`dnd_ai.api.deps.get_connection` commits on return, rolls
    back on any raised exception). A `creator_user_id` with no `security.
    users` row makes the membership INSERT fail its `user_id` foreign key
    after the campaign row has already been written earlier in the same
    transaction — proving the campaign row does not survive on its own
    when a later step in the same transaction fails."""
    nonexistent_user_id = uuid.uuid4()
    campaign_name = f"Atomicity Test {uuid.uuid4().hex[:8]}"
    with client_factory(nonexistent_user_id) as client:
        response = client.post("/campaigns", json=_body(f, name=campaign_name))
    # security.campaign_memberships.user_id's foreign-key violation
    # (SQLSTATE 23503) is already classified by the generic IntegrityError
    # handler to a fixed 400 (dnd_ai.api.errors._INVALID_REQUEST_INTEGRITY_
    # SQLSTATES) — no pre-check needed here, since a nonexistent
    # authenticated caller can only happen in a test, never in production
    # (get_authenticated_user_id always resolves to a real, OIDC-
    # provisioned security.users row).
    assert response.status_code == 400, response.text

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE name = :n"),
            {"n": campaign_name},
        ).scalar_one()
        assert campaign_count == 0


def test_a_second_campaign_on_an_already_used_timeline_succeeds_and_cannot_see_the_first_campaigns_access(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    """`dnd_ai.commands.campaigns`'s own module docstring documents
    timeline reuse across campaigns as intentional, shared-world-content
    semantics (docs/DOMAIN_MODEL.md §2.2), not a gap: `create_campaign`
    only checks that `timeline_id` exists, never who else already uses it.
    This proves both halves of that policy — the second campaign is
    accepted rather than rejected, and neither campaign's own creator
    gains any capability in the other campaign, since `security.
    campaign_memberships`/`.membership_roles` are keyed by `campaign_id`,
    never by the timeline they share."""
    with client_factory(f.creator_user_id) as first_client:
        first_response = first_client.post("/campaigns", json=_body(f, name="First Expedition"))
        assert first_response.status_code == 201, first_response.text
        first_campaign_id = uuid.UUID(first_response.json()["campaign_id"])

    with client_factory(f.second_user_id) as second_client:
        second_response = second_client.post("/campaigns", json=_body(f, name="Second Expedition"))
        assert second_response.status_code == 201, second_response.text
        second_campaign_id = uuid.UUID(second_response.json()["campaign_id"])
        assert second_campaign_id != first_campaign_id

        # The second campaign's own creator has no membership at all in
        # the first campaign — a fixed, non-disclosing 404, matching
        # dnd_ai.api.access.require_campaign_capability's own contract for
        # a non-member.
        cross_campaign_response = second_client.get(f"/campaigns/{first_campaign_id}/summary")
    assert cross_campaign_response.status_code == 404, cross_campaign_response.text

    with client_factory(f.creator_user_id) as first_client:
        # Symmetrically, the first campaign's own creator has no
        # membership in the second.
        reverse_response = first_client.get(f"/campaigns/{second_campaign_id}/summary")
    assert reverse_response.status_code == 404, reverse_response.text
