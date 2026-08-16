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
and that campaign creation is atomic on failure
(`test_campaign_creation_is_atomic_when_membership_creation_fails`).

Also covers the Critical timeline-reuse authorization defect (`dnd_ai.
commands.campaigns`'s own module docstring has the full defect/fix
narrative): only a caller already holding `access.manage` in an existing
campaign may attach a second campaign to that campaign's own timeline
(`test_the_existing_access_manager_can_create_a_second_campaign_on_their_
own_timeline`), an unrelated user cannot
(`test_an_unrelated_user_cannot_create_a_second_campaign_on_anothers_
timeline`), a `campaign.view`-only member cannot
(`test_a_member_with_only_campaign_view_cannot_reuse_the_timeline`),
concurrent claims on a brand-new timeline never both succeed
(`test_concurrent_claims_on_a_brand_new_timeline_only_one_succeeds`), and
that the closed exploit (fabricating a campaign to read a victim
timeline's hidden canon) no longer works end to end
(`test_an_unauthorized_caller_cannot_use_campaign_creation_to_read_hidden_
canon`).
"""

import concurrent.futures
import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    make_area_hazard,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_location,
    make_organization,
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
        # Scoped by world_id, not fixture.timeline_id alone — several tests
        # (timeline-reuse, concurrent-claim) create additional timelines and
        # campaigns under the same fixture world, and this sweeps all of
        # them regardless of which specific timeline_id they used.
        cleanup.execute(
            text("""
                DELETE FROM campaign.character_location_history WHERE timeline_id IN (
                    SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_invitations WHERE campaign_id IN (
                    SELECT c.campaign_id FROM campaign.campaigns c
                    JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                    WHERE t.world_id = :w
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.idempotent_requests WHERE campaign_id IN (
                    SELECT c.campaign_id FROM campaign.campaigns c
                    JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                    WHERE t.world_id = :w
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT cm.campaign_membership_id FROM security.campaign_memberships cm
                    JOIN campaign.campaigns c ON c.campaign_id = cm.campaign_id
                    JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                    WHERE t.world_id = :w
                )
            """),
            {"w": fixture.world_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT c.campaign_id FROM campaign.campaigns c
                    JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                    WHERE t.world_id = :w
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
            text("DELETE FROM campaign.timelines WHERE world_id = :w"),
            {"w": fixture.world_id},
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


def test_any_authenticated_user_can_create_the_first_campaign_on_an_unused_timeline(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Doubles as the explicit "unclaimed timeline" policy proof `dnd_ai.
    commands.campaigns`'s own module docstring documents: `f.timeline_id`
    has no `campaign.campaigns` row yet at this point, so `_authorize_
    timeline_reuse()`'s step 2 (any authenticated caller may claim an
    unused timeline unconditionally) is exactly what authorizes this
    call — not an absence of a check."""
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
    """A fixed, non-disclosing 404 — `TimelineNotAuthorizedError` — not a
    400: a nonexistent `timeline_id` and one the caller isn't entitled to
    reuse are folded into the identical response (`dnd_ai.commands.
    campaigns`'s own module docstring), so a caller probing random UUIDs
    can't distinguish the two cases."""
    with client_factory(f.creator_user_id) as client:
        response = client.post("/campaigns", json=_body(f, timeline_id=str(uuid.uuid4())))
    assert response.status_code == 404, response.text


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


# ---------------------------------------------------------------------------
# Critical fix: the timeline-reuse authorization policy
# `dnd_ai.commands.campaigns._authorize_timeline_reuse()` implements —
# application-layer only, no schema change — see that module's own
# docstring for the full defect/fix narrative.
# ---------------------------------------------------------------------------


def test_the_existing_access_manager_can_create_a_second_campaign_on_their_own_timeline(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The one authorized reuse case: the same user who already holds
    `access.manage` in an existing campaign on `timeline_id` may attach a
    second campaign to it — proving the check is a real entitlement gate,
    not a blanket "no campaign may ever reuse a timeline" regression. The
    second campaign still starts with its own independent membership/role,
    never inheriting the first campaign's row — `security.
    campaign_memberships`/`.membership_roles` are keyed by `campaign_id`,
    never by the timeline they share."""
    with client_factory(f.creator_user_id) as client:
        first_response = client.post("/campaigns", json=_body(f, name="First Expedition"))
        assert first_response.status_code == 201, first_response.text
        first_campaign_id = uuid.UUID(first_response.json()["campaign_id"])

        second_response = client.post("/campaigns", json=_body(f, name="Second Expedition"))
    assert second_response.status_code == 201, second_response.text
    second_campaign_id = uuid.UUID(second_response.json()["campaign_id"])
    second_membership_id = uuid.UUID(second_response.json()["campaign_membership_id"])
    assert second_campaign_id != first_campaign_id

    with postgres_engine.connect() as verify:
        role_rows = verify.execute(
            text("SELECT role_id FROM security.membership_roles WHERE campaign_membership_id = :m"),
            {"m": second_membership_id},
        ).all()
        assert len(role_rows) == 1


def test_an_unrelated_user_cannot_create_a_second_campaign_on_anothers_timeline(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The Critical defect this policy closes: before it existed, any
    authenticated user could attach a new campaign to `f.timeline_id` once
    `f.creator_user_id` had already claimed it, gaining `campaign_owner`'s
    own `campaign.view`/`canon.edit` there by construction. The rejection
    is a fixed, non-disclosing 404 — indistinguishable from a nonexistent
    timeline — and leaves no campaign, membership, role assignment, or
    audit row behind for the attempt."""
    with client_factory(f.creator_user_id) as owner_client:
        first_response = owner_client.post("/campaigns", json=_body(f, name="Owner's Campaign"))
        assert first_response.status_code == 201, first_response.text

    campaign_name = f"Attacker Campaign {uuid.uuid4().hex[:8]}"
    with client_factory(f.second_user_id) as attacker_client:
        attack_response = attacker_client.post("/campaigns", json=_body(f, name=campaign_name))
    assert attack_response.status_code == 404, attack_response.text

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE name = :n"),
            {"n": campaign_name},
        ).scalar_one()
        assert campaign_count == 0

        membership_count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE user_id = :u AND campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"u": f.second_user_id, "t": f.timeline_id},
        ).scalar_one()
        assert membership_count == 0

        audit_count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log "
                "WHERE schema_name = 'campaign' AND table_name = 'campaigns' "
                "AND actor_user_id = :u"
            ),
            {"u": f.second_user_id},
        ).scalar_one()
        assert audit_count == 0


def test_a_member_with_only_campaign_view_cannot_reuse_the_timeline(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`access.manage` specifically is the required capability — an
    ordinary member of the existing campaign holding only `campaign.view`
    (the seeded system-template `player` role, assigned through the
    existing membership-role API) still cannot create a second campaign on
    that timeline."""
    with client_factory(f.creator_user_id) as owner_client:
        first_response = owner_client.post("/campaigns", json=_body(f, name="Owner's Campaign"))
        assert first_response.status_code == 201, first_response.text
        first_campaign_id = uuid.UUID(first_response.json()["campaign_id"])

        add_member_response = owner_client.post(
            f"/campaigns/{first_campaign_id}/memberships",
            json={"user_id": str(f.second_user_id)},
        )
        assert add_member_response.status_code == 201, add_member_response.text
        member_membership_id = uuid.UUID(add_member_response.json()["campaign_membership_id"])

        with postgres_engine.connect() as verify:
            player_role_id = verify.execute(
                text(
                    "SELECT role_id FROM security.roles WHERE code = 'player' "
                    "AND campaign_id IS NULL"
                )
            ).scalar_one()

        assign_role_response = owner_client.post(
            f"/campaigns/{first_campaign_id}/memberships/{member_membership_id}/roles",
            json={"role_id": str(player_role_id)},
        )
        assert assign_role_response.status_code == 201, assign_role_response.text

    with client_factory(f.second_user_id) as member_client:
        # campaign.view: confirms the role really is active before proving
        # it is insufficient for timeline reuse below.
        summary_response = member_client.get(f"/campaigns/{first_campaign_id}/summary")
        assert summary_response.status_code == 200, summary_response.text

        reuse_response = member_client.post("/campaigns", json=_body(f, name="Reuse Attempt"))
    assert reuse_response.status_code == 404, reuse_response.text


def test_concurrent_claims_on_a_brand_new_timeline_only_one_succeeds(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The row-lock argument `dnd_ai.commands.campaigns`'s own module
    docstring makes: two unrelated users racing to be the first campaign
    on a brand-new, previously-unused timeline cannot both win. Whichever
    transaction's `SELECT ... FOR UPDATE` commits first becomes the
    legitimate first claimant; the other serializes behind that lock and,
    once unblocked, finds a campaign it holds no `access.manage` in and is
    rejected — never both succeeding, and never leaving more than one
    `campaign.campaigns` row on the timeline."""
    with postgres_engine.begin() as connection:
        fresh_timeline_id = make_timeline(connection, f.world_id, "Race Timeline")

    def _attempt(user_id: uuid.UUID) -> int:
        with client_factory(user_id) as client:
            response = client.post(
                "/campaigns",
                json=_body(f, timeline_id=str(fresh_timeline_id), name=f"Claim by {user_id}"),
            )
        return response.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_attempt, f.creator_user_id)
        future_b = pool.submit(_attempt, f.second_user_id)
        status_a = future_a.result()
        status_b = future_b.result()

    assert sorted([status_a, status_b]) == [201, 404], (status_a, status_b)

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fresh_timeline_id},
        ).scalar_one()
        assert campaign_count == 1


def test_an_unauthorized_caller_cannot_use_campaign_creation_to_read_hidden_canon(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Proves the actual exploit this policy closes end to end: before it
    existed, an attacker could manufacture a campaign on a victim's
    timeline and use the resulting `campaign_owner`/`canon.edit` to read
    GM-only canon — hidden dungeon content and an organization's internal
    (canon.edit-only) description — that a non-member could never
    otherwise reach. With the fix, campaign creation itself is rejected,
    so the attacker never obtains a `campaign_id` to read either through."""
    with postgres_engine.begin() as connection:
        dungeon_id = make_dungeon(connection, f.world_id)
        area_id = make_dungeon_area(connection, dungeon_id)
        make_area_hazard(connection, area_id, is_hidden=True)
        organization_id = make_organization(
            connection,
            f.world_id,
            internal_description="The guild secretly answers to the lich queen.",
        )

    with client_factory(f.creator_user_id) as owner_client:
        victim_response = owner_client.post("/campaigns", json=_body(f, name="Victim Campaign"))
        assert victim_response.status_code == 201, victim_response.text
        victim_campaign_id = uuid.UUID(victim_response.json()["campaign_id"])

    with client_factory(f.second_user_id) as attacker_client:
        create_attempt = attacker_client.post(
            "/campaigns", json=_body(f, name="Attacker's Shadow Campaign")
        )
        assert create_attempt.status_code == 404, create_attempt.text
        assert "campaign_id" not in create_attempt.json()

        dungeon_response = attacker_client.get(
            f"/campaigns/{victim_campaign_id}/dungeon-areas/{area_id}"
        )
        assert dungeon_response.status_code == 404, dungeon_response.text

        organization_response = attacker_client.get(
            f"/campaigns/{victim_campaign_id}/organizations/{organization_id}"
        )
    assert organization_response.status_code == 404, organization_response.text
