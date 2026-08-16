"""Tests for `dnd_ai.api.campaigns` — the campaign-creation bootstrap
command endpoint (docs/PLAN.md Phase 10 "Still to come" list).

Covers: any authenticated, positively entitled user may create a campaign
(no pre-existing membership needed, unlike every other command endpoint —
see "the second Critical defect" below for what "positively entitled"
means and why it is not merely "any authenticated user"), the created
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
and that the access-manager retention invariant still blocks revoking a
sole owner's own role
(`test_the_sole_owners_own_role_cannot_be_revoked_from_an_active_campaign`).

Also covers the first Critical timeline-reuse authorization defect
(`dnd_ai.commands.campaigns`'s own module docstring has the full
defect/fix narrative): only a caller already holding `access.manage` in
an existing campaign may attach a second campaign to that campaign's own
timeline (`test_the_existing_access_manager_can_create_a_second_
campaign_on_their_own_timeline`), an unrelated user cannot
(`test_an_unrelated_user_cannot_create_a_second_campaign_on_anothers_
timeline`), a `campaign.view`-only member cannot
(`test_a_member_with_only_campaign_view_cannot_reuse_the_timeline`), and
that the closed exploit (fabricating a campaign to read a victim
timeline's hidden canon) no longer works end to end
(`test_an_unauthorized_caller_cannot_use_campaign_creation_to_read_hidden_
canon`).

Also covers the second Critical defect found immediately after the first
(`dnd_ai.commands.campaigns`'s own module docstring, "First-campaign
entitlement," has the full narrative): "no campaign currently references
this timeline" is not itself an entitlement to be the one who creates the
first one. A positively entitled user (one holding a live `security.
timeline_bootstrap_grants` row, issued by trusted world-authoring
infrastructure — every `Fixture.creator_user_id` in this file has one for
`Fixture.timeline_id`) can
(`test_a_positively_entitled_user_can_create_the_first_campaign_on_their_
granted_timeline`, which also proves the grant is marked consumed
afterward); an unrelated user with no grant of their own cannot claim a
timeline with pre-authored hidden dungeon content and knowledge
(`test_an_unrelated_user_cannot_claim_an_unused_timeline_with_pre_
authored_hidden_content`); a second user cannot replay or reuse someone
else's still-live grant
(`test_a_second_user_cannot_replay_or_reuse_anothers_first_claim_grant`);
an expired or revoked grant cannot be used
(`test_an_expired_or_revoked_bootstrap_grant_cannot_be_used`); concurrent
claims — each backed by their own independently valid grant — on the same
brand-new timeline never both succeed
(`test_concurrent_claims_on_a_brand_new_timeline_only_one_succeeds`); and
a failed campaign-creation attempt leaves the grant it would have consumed
exactly as usable as before
(`test_campaign_creation_is_atomic_and_preserves_grant_usability_when_
ruleset_validation_fails`).

Also covers the High-severity idempotency defect the second Critical fix
exposed (`dnd_ai.api.campaigns`'s and `dnd_ai.api.idempotency`'s own
docstrings have the full narrative): a single-use bootstrap grant stops a
*different* user from claiming the first campaign, but did nothing to stop
the successful creator's own dropped-response retry from reusing the
timeline it just claimed (via the `access.manage` that retry's own creator
now holds) and minting a second campaign/membership/role/audit row for one
logical request. `security.campaign_creation_reservations` (migration 088)
closes it: a sequential replay returns the original campaign with exactly
one row surviving in every table a successful creation touches
(`test_a_sequential_replay_returns_the_original_campaign_with_exactly_one_
of_each_row`); two genuinely concurrent requests sharing a key never create
more than one campaign
(`test_two_concurrent_same_key_requests_create_exactly_one_campaign`); a
retry standing in for a lost response replays the already-committed
campaign without ever having seen the original response
(`test_a_lost_response_retry_replays_the_already_committed_campaign`);
reusing a key with a changed payload is rejected as the established fixed
conflict, not silently replayed or applied
(`test_reusing_the_same_key_with_a_different_payload_is_rejected_as_a_
conflict`); a genuinely different key legitimately creates a second
campaign through the existing `access.manage` timeline-reuse path
(`test_different_idempotency_keys_intentionally_create_a_second_campaign_
via_timeline_reuse`); and a forced mid-request failure leaves the
reservation and the bootstrap grant exactly as usable as before, proven by
an immediate, successful retry on the same key
(`test_a_forced_failure_leaves_the_key_and_grant_unconsumed_for_a_
successful_retry`).
"""

import concurrent.futures
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.campaigns import grant_timeline_bootstrap
from tests.factories import (
    make_area_hazard,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
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

        # The positive, server-verifiable first-campaign entitlement —
        # issued here by this fixture acting as trusted world-authoring
        # infrastructure, the same trust boundary every other piece of
        # pre-campaign content below already has. Without this,
        # f.creator_user_id could not create the first campaign on
        # f.timeline_id at all — see dnd_ai.commands.campaigns's own
        # module docstring ("First-campaign entitlement").
        grant_timeline_bootstrap(
            connection, timeline_id=self.timeline_id, granted_to_user_id=self.creator_user_id
        )

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
        # security.campaign_creation_reservations carries no timeline/world
        # column of its own (dnd_ai.api.idempotency's own "Pre-campaign
        # idempotency" docstring section — it exists before any campaign
        # does) — scoped by actor_user_id instead, the same two users every
        # other cleanup step below also targets directly.
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_creation_reservations
                WHERE actor_user_id = ANY(:users)
            """),
            {"users": [fixture.creator_user_id, fixture.second_user_id]},
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
            text("""
                DELETE FROM security.timeline_bootstrap_grants WHERE timeline_id IN (
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


def test_a_positively_entitled_user_can_create_the_first_campaign_on_their_granted_timeline(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`f.timeline_id` has no `campaign.campaigns` row yet at this point,
    so what authorizes this call is exactly the `security.
    timeline_bootstrap_grants` row `Fixture.__init__` issued to
    `f.creator_user_id` — never the mere absence of a prior campaign
    (`dnd_ai.commands.campaigns`'s own module docstring, "First-campaign
    entitlement," documents why that alone was a second Critical defect).
    Also proves the grant is marked consumed, attributed to the new
    campaign, once it succeeds — never reusable again."""
    with client_factory(f.creator_user_id) as client:
        response = client.post("/campaigns", json=_body(f))
    assert response.status_code == 201, response.text
    payload = response.json()
    campaign_id = uuid.UUID(payload["campaign_id"])
    campaign_membership_id = uuid.UUID(payload["campaign_membership_id"])

    with postgres_engine.connect() as verify:
        grant_row = verify.execute(
            text("""
                SELECT consumed_at, consumed_by_campaign_id
                FROM security.timeline_bootstrap_grants
                WHERE timeline_id = :t AND granted_to_user_id = :u
            """),
            {"t": f.timeline_id, "u": f.creator_user_id},
        ).one()
        assert grant_row.consumed_at is not None
        assert grant_row.consumed_by_campaign_id == campaign_id

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


def test_campaign_creation_is_atomic_and_preserves_grant_usability_when_ruleset_validation_fails(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`create_campaign` authorizes the timeline (locking, and — on the
    first-campaign path — matching but not yet consuming, the caller's
    bootstrap grant), then checks the ruleset, then writes `campaign.
    campaigns`/`security.campaign_memberships`/`.membership_roles`, and
    only *then* marks the grant consumed — all in one request transaction
    (`dnd_ai.api.deps.get_connection` commits on return, rolls back on any
    raised exception). A disallowed `ruleset_version_id` fails after
    authorization succeeds but before anything is written, proving two
    things at once: no campaign/membership/role/audit row survives the
    failure, and — the property a nonexistent-`creator_user_id` trick
    could no longer exercise once authorization itself requires a real,
    already-resolvable user — the grant `f.creator_user_id` holds for
    `f.timeline_id` is exactly as usable after this failed attempt as it
    was before, immediately proven by a following, valid request
    succeeding on the very same grant."""
    campaign_name = f"Atomicity Test {uuid.uuid4().hex[:8]}"
    with client_factory(f.creator_user_id) as client:
        failed_response = client.post(
            "/campaigns",
            json=_body(f, name=campaign_name, ruleset_version_id=str(f.foreign_ruleset_version_id)),
        )
        assert failed_response.status_code == 400, failed_response.text

        with postgres_engine.connect() as verify:
            campaign_count = verify.execute(
                text("SELECT count(*) FROM campaign.campaigns WHERE name = :n"),
                {"n": campaign_name},
            ).scalar_one()
            assert campaign_count == 0

            grant_row = verify.execute(
                text("""
                    SELECT consumed_at, consumed_by_campaign_id
                    FROM security.timeline_bootstrap_grants
                    WHERE timeline_id = :t AND granted_to_user_id = :u
                """),
                {"t": f.timeline_id, "u": f.creator_user_id},
            ).one()
            assert grant_row.consumed_at is None
            assert grant_row.consumed_by_campaign_id is None

        retry_response = client.post("/campaigns", json=_body(f, name="Retry Succeeds"))
    assert retry_response.status_code == 201, retry_response.text


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
    not a blanket "no campaign may ever reuse a timeline" regression, and
    that it needs no bootstrap grant of its own: `f.creator_user_id`'s own
    grant was already consumed by the first campaign (proven elsewhere),
    yet the second campaign — reached through the access.manage branch,
    which never looks at `security.timeline_bootstrap_grants` at all —
    still succeeds. The second campaign still starts with its own
    independent membership/role, never inheriting the first campaign's
    row — `security.campaign_memberships`/`.membership_roles` are keyed by
    `campaign_id`, never by the timeline they share."""
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
        # No second grant was ever issued for this timeline — the fixture
        # only grants f.creator_user_id once — so a live grant count of
        # zero here confirms the second campaign truly went through the
        # access.manage reuse branch, not a second (nonexistent) grant.
        live_grant_count = verify.execute(
            text("""
                SELECT count(*) FROM security.timeline_bootstrap_grants
                WHERE timeline_id = :t AND consumed_at IS NULL AND revoked_at IS NULL
            """),
            {"t": f.timeline_id},
        ).scalar_one()
        assert live_grant_count == 0

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
    docstring makes: two *independently entitled* users — each holding
    their own valid, unconsumed bootstrap grant for the same brand-new,
    previously-unused timeline — racing to be the first campaign there
    cannot both win. Whichever transaction's `SELECT ... FOR UPDATE`
    commits first becomes the legitimate first claimant (consuming its own
    grant); the other serializes behind that lock and, once unblocked,
    finds a campaign it holds no `access.manage` in and is rejected — its
    own still-valid grant notwithstanding, since a bootstrap grant only
    ever authorizes being *first* — never both succeeding, and never
    leaving more than one `campaign.campaigns` row on the timeline."""
    with postgres_engine.begin() as connection:
        fresh_timeline_id = make_timeline(connection, f.world_id, "Race Timeline")
        for user_id in (f.creator_user_id, f.second_user_id):
            grant_timeline_bootstrap(
                connection, timeline_id=fresh_timeline_id, granted_to_user_id=user_id
            )

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


# ---------------------------------------------------------------------------
# Second Critical fix: the first-campaign entitlement
# (`security.timeline_bootstrap_grants`, migration 087) —
# `dnd_ai.commands.campaigns.grant_timeline_bootstrap()`/
# `_authorize_timeline_reuse()`'s "First-campaign entitlement" section has
# the full defect/fix narrative.
# ---------------------------------------------------------------------------


def test_an_unrelated_user_cannot_claim_an_unused_timeline_with_pre_authored_hidden_content(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The second Critical defect itself, proven end to end: a brand-new
    timeline with real, pre-authored hidden dungeon content and a
    knowledge item — exactly the ordering the vertical-slice scenario
    depends on, world content before any campaign — but with *no*
    `security.timeline_bootstrap_grants` row for anyone. An unrelated user
    who merely knows this `timeline_id` cannot claim it: absence of a
    prior campaign was never itself authorization. No campaign,
    membership, role assignment, or audit row survives the attempt."""
    with postgres_engine.begin() as connection:
        fresh_timeline_id = make_timeline(connection, f.world_id, "Ungranted Timeline")
        dungeon_id = make_dungeon(connection, f.world_id)
        area_id = make_dungeon_area(connection, dungeon_id)
        hazard_id = make_area_hazard(connection, area_id, is_hidden=True)
        make_knowledge_item(
            connection,
            f.world_id,
            statement="A hidden trap guards the vault.",
            subject_area_hazard_id=hazard_id,
        )

    campaign_name = f"Unentitled Claim {uuid.uuid4().hex[:8]}"
    with client_factory(f.second_user_id) as attacker_client:
        response = attacker_client.post(
            "/campaigns",
            json=_body(f, timeline_id=str(fresh_timeline_id), name=campaign_name),
        )
    assert response.status_code == 404, response.text

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fresh_timeline_id},
        ).scalar_one()
        assert campaign_count == 0

        membership_count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships WHERE user_id = :u "
                "AND campaign_id IN (SELECT campaign_id FROM campaign.campaigns "
                "WHERE timeline_id = :t)"
            ),
            {"u": f.second_user_id, "t": fresh_timeline_id},
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


def test_a_second_user_cannot_replay_or_reuse_anothers_first_claim_grant(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """`f.timeline_id` already has a live bootstrap grant — but it names
    `f.creator_user_id`, not `f.second_user_id`. Binding a grant to a
    specific `granted_to_user_id` (never a bearer token) means a second
    user has no way to redeem someone else's still-unconsumed grant: the
    attempt is rejected, and the real owner's grant remains untouched,
    provably still usable by them afterward."""
    with client_factory(f.second_user_id) as attacker_client:
        replay_response = attacker_client.post(
            "/campaigns", json=_body(f, name="Stolen Grant Attempt")
        )
    assert replay_response.status_code == 404, replay_response.text

    with postgres_engine.connect() as verify:
        grant_row = verify.execute(
            text("""
                SELECT consumed_at, revoked_at
                FROM security.timeline_bootstrap_grants
                WHERE timeline_id = :t AND granted_to_user_id = :u
            """),
            {"t": f.timeline_id, "u": f.creator_user_id},
        ).one()
        assert grant_row.consumed_at is None
        assert grant_row.revoked_at is None

    with client_factory(f.creator_user_id) as owner_client:
        legitimate_response = owner_client.post(
            "/campaigns", json=_body(f, name="Legitimate Claim")
        )
    assert legitimate_response.status_code == 201, legitimate_response.text


def test_an_expired_or_revoked_bootstrap_grant_cannot_be_used(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Both `expires_at`/`revoked_at` are checked by the same authorization
    query (`dnd_ai.commands.campaigns`'s own "First-campaign entitlement"
    docstring section) — proven directly against two separate, otherwise-
    valid grants issued by this fixture acting as trusted world-authoring
    infrastructure, exactly as it does to grant one in the first place."""
    with postgres_engine.begin() as connection:
        expired_timeline_id = make_timeline(connection, f.world_id, "Expired Grant Timeline")
        grant_timeline_bootstrap(
            connection,
            timeline_id=expired_timeline_id,
            granted_to_user_id=f.second_user_id,
            ttl=timedelta(days=-1),
        )

        revoked_timeline_id = make_timeline(connection, f.world_id, "Revoked Grant Timeline")
        revoked_grant = grant_timeline_bootstrap(
            connection, timeline_id=revoked_timeline_id, granted_to_user_id=f.second_user_id
        )
        connection.execute(
            text(
                "UPDATE security.timeline_bootstrap_grants SET revoked_at = now() "
                "WHERE timeline_bootstrap_grant_id = :g"
            ),
            {"g": revoked_grant.timeline_bootstrap_grant_id},
        )

    with client_factory(f.second_user_id) as client:
        expired_response = client.post(
            "/campaigns",
            json=_body(f, timeline_id=str(expired_timeline_id), name="Expired Attempt"),
        )
        revoked_response = client.post(
            "/campaigns",
            json=_body(f, timeline_id=str(revoked_timeline_id), name="Revoked Attempt"),
        )
    assert expired_response.status_code == 404, expired_response.text
    assert revoked_response.status_code == 404, revoked_response.text


# ---------------------------------------------------------------------------
# High-severity fix: pre-campaign idempotency
# (`security.campaign_creation_reservations`, migration 088) —
# `dnd_ai.api.idempotency`'s "Pre-campaign idempotency" docstring section
# and `dnd_ai.api.campaigns`'s own docstring have the full defect/fix
# narrative.
# ---------------------------------------------------------------------------


def test_a_sequential_replay_returns_the_original_campaign_with_exactly_one_of_each_row(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A second request with the identical `Idempotency-Key` and payload
    replays the first response verbatim rather than falling through to the
    now-available `access.manage` timeline-reuse path and minting a second
    campaign — proven both by the two response bodies matching exactly and
    by exactly one row surviving in every table a successful creation
    touches: the campaign itself, its membership, the owner role
    assignment, the consumed bootstrap grant, the audit record, and the
    reservation row itself."""
    key = f"replay-{uuid.uuid4().hex[:8]}"
    body = _body(f, name="Replayed Campaign")
    with client_factory(f.creator_user_id) as client:
        first = client.post("/campaigns", json=body, headers={"Idempotency-Key": key})
        second = client.post("/campaigns", json=body, headers={"Idempotency-Key": key})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()
    campaign_id = uuid.UUID(first.json()["campaign_id"])
    campaign_membership_id = uuid.UUID(first.json()["campaign_membership_id"])

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": campaign_id},
        ).scalar_one()
        assert campaign_count == 1

        membership_count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_memberships "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": campaign_membership_id},
        ).scalar_one()
        assert membership_count == 1

        role_count = verify.execute(
            text(
                "SELECT count(*) FROM security.membership_roles WHERE campaign_membership_id = :m"
            ),
            {"m": campaign_membership_id},
        ).scalar_one()
        assert role_count == 1

        grant_row = verify.execute(
            text("""
                SELECT consumed_at, consumed_by_campaign_id
                FROM security.timeline_bootstrap_grants
                WHERE timeline_id = :t AND granted_to_user_id = :u
            """),
            {"t": f.timeline_id, "u": f.creator_user_id},
        ).one()
        assert grant_row.consumed_at is not None
        assert grant_row.consumed_by_campaign_id == campaign_id

        audit_count = verify.execute(
            text(
                "SELECT count(*) FROM audit.change_log "
                "WHERE schema_name = 'campaign' AND table_name = 'campaigns' AND record_id = :c"
            ),
            {"c": campaign_id},
        ).scalar_one()
        assert audit_count == 1

        reservation_row = verify.execute(
            text("""
                SELECT created_campaign_id, response_status_code
                FROM security.campaign_creation_reservations
                WHERE actor_user_id = :u AND idempotency_key = :k
            """),
            {"u": f.creator_user_id, "k": key},
        ).one()
        assert reservation_row.created_campaign_id == campaign_id
        assert reservation_row.response_status_code == 201


def test_two_concurrent_same_key_requests_create_exactly_one_campaign(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Two genuinely concurrent requests from the same creator, same
    `Idempotency-Key`, same payload — the same real-thread race
    `test_concurrent_claims_on_a_brand_new_timeline_only_one_succeeds`
    already proves reliable against this database, applied here to
    `begin_campaign_creation_request`'s own atomic reservation `INSERT ...
    ON CONFLICT DO NOTHING` rather than the bootstrap grant's row lock.
    Whichever request's reservation commits first creates the campaign;
    the other blocks on the unique index until that commit, then replays
    its response — both succeed, both return the identical campaign, and
    only one `campaign.campaigns` row is ever created."""
    key = f"concurrent-{uuid.uuid4().hex[:8]}"
    body = _body(f, name="Concurrent Claim")

    def _attempt() -> tuple[int, dict[str, object]]:
        with client_factory(f.creator_user_id) as client:
            response = client.post("/campaigns", json=body, headers={"Idempotency-Key": key})
        return response.status_code, response.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_attempt)
        future_b = pool.submit(_attempt)
        status_a, body_a = future_a.result()
        status_b, body_b = future_b.result()

    assert status_a == 201, body_a
    assert status_b == 201, body_b
    assert body_a == body_b

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar_one()
        assert campaign_count == 1

        reservation_count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_creation_reservations "
                "WHERE actor_user_id = :u AND idempotency_key = :k"
            ),
            {"u": f.creator_user_id, "k": key},
        ).scalar_one()
        assert reservation_count == 1


def test_a_lost_response_retry_replays_the_already_committed_campaign(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """Stands in for a client whose first request's underlying transaction
    fully committed, but whose HTTP response never arrived (a dropped
    connection, a proxy timeout): the retry below never inspects the first
    response at all, only the database's own already-committed state
    beforehand — and still gets back exactly the campaign that first
    request produced, never a second one."""
    key = f"lost-response-{uuid.uuid4().hex[:8]}"
    body = _body(f, name="Lost Response Campaign")

    with client_factory(f.creator_user_id) as client:
        client.post("/campaigns", json=body, headers={"Idempotency-Key": key})
        # The response above is deliberately never read — simulating a
        # dropped connection after the server-side transaction committed.

    with postgres_engine.connect() as verify:
        committed = verify.execute(
            text("""
                SELECT c.campaign_id, cm.campaign_membership_id
                FROM campaign.campaigns c
                JOIN security.campaign_memberships cm ON cm.campaign_id = c.campaign_id
                WHERE c.timeline_id = :t AND cm.user_id = :u
            """),
            {"t": f.timeline_id, "u": f.creator_user_id},
        ).one()

    with client_factory(f.creator_user_id) as client:
        retried = client.post("/campaigns", json=body, headers={"Idempotency-Key": key})
    assert retried.status_code == 201, retried.text
    assert uuid.UUID(retried.json()["campaign_id"]) == committed.campaign_id
    assert uuid.UUID(retried.json()["campaign_membership_id"]) == committed.campaign_membership_id

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar_one()
        assert campaign_count == 1


def test_reusing_the_same_key_with_a_different_payload_is_rejected_as_a_conflict(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """The established idempotency conflict contract
    (`dnd_ai.api.idempotency.begin_campaign_creation_request`, mirroring
    `begin_idempotent_request` exactly) — a fixed, non-disclosing 409, not
    a silent replay and not a second campaign."""
    key = f"conflict-{uuid.uuid4().hex[:8]}"
    with client_factory(f.creator_user_id) as client:
        first = client.post(
            "/campaigns", json=_body(f, name="Conflict Original"), headers={"Idempotency-Key": key}
        )
        second = client.post(
            "/campaigns", json=_body(f, name="Conflict Mutated"), headers={"Idempotency-Key": key}
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar_one()
        assert campaign_count == 1


def test_different_idempotency_keys_intentionally_create_a_second_campaign_via_timeline_reuse(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A different `Idempotency-Key` is a genuinely different logical
    request, not a retry of the first one — the creator, now holding
    `access.manage` in the first campaign, may deliberately reuse the
    timeline for a second one (the existing, unaffected timeline-reuse
    policy), and each key gets its own reservation row pointing at its own
    resulting campaign."""
    first_key = f"first-{uuid.uuid4().hex[:8]}"
    second_key = f"second-{uuid.uuid4().hex[:8]}"
    with client_factory(f.creator_user_id) as client:
        first = client.post(
            "/campaigns",
            json=_body(f, name="First Via Key"),
            headers={"Idempotency-Key": first_key},
        )
        second = client.post(
            "/campaigns",
            json=_body(f, name="Second Via Key"),
            headers={"Idempotency-Key": second_key},
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_campaign_id = uuid.UUID(first.json()["campaign_id"])
    second_campaign_id = uuid.UUID(second.json()["campaign_id"])
    assert first_campaign_id != second_campaign_id

    with postgres_engine.connect() as verify:
        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar_one()
        assert campaign_count == 2

        rows = verify.execute(
            text("""
                SELECT idempotency_key, created_campaign_id
                FROM security.campaign_creation_reservations
                WHERE actor_user_id = :u AND idempotency_key IN (:k1, :k2)
            """),
            {"u": f.creator_user_id, "k1": first_key, "k2": second_key},
        ).all()
        by_key = {row.idempotency_key: row.created_campaign_id for row in rows}
        assert by_key[first_key] == first_campaign_id
        assert by_key[second_key] == second_campaign_id


def test_a_forced_failure_leaves_the_key_and_grant_unconsumed_for_a_successful_retry(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    """A disallowed ruleset fails `create_campaign` after `begin_campaign_
    creation_request`'s own reservation `INSERT` but before anything
    commits — the whole request transaction rolls back together
    (`dnd_ai.api.deps.get_connection`), so the reservation row is never
    durably written at all, mirroring `dnd_ai.api.idempotency`'s own "a
    failed command never permanently consumes a key" guarantee. The
    bootstrap grant this same attempt would have consumed is equally
    untouched, and an immediate retry with the identical key succeeds."""
    key = f"forced-failure-{uuid.uuid4().hex[:8]}"
    with client_factory(f.creator_user_id) as client:
        failed = client.post(
            "/campaigns",
            json=_body(
                f, name="Forced Failure", ruleset_version_id=str(f.foreign_ruleset_version_id)
            ),
            headers={"Idempotency-Key": key},
        )
    assert failed.status_code == 400, failed.text

    with postgres_engine.connect() as verify:
        reservation_count = verify.execute(
            text(
                "SELECT count(*) FROM security.campaign_creation_reservations "
                "WHERE actor_user_id = :u AND idempotency_key = :k"
            ),
            {"u": f.creator_user_id, "k": key},
        ).scalar_one()
        assert reservation_count == 0

        campaign_count = verify.execute(
            text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": f.timeline_id},
        ).scalar_one()
        assert campaign_count == 0

        grant_row = verify.execute(
            text("""
                SELECT consumed_at, consumed_by_campaign_id
                FROM security.timeline_bootstrap_grants
                WHERE timeline_id = :t AND granted_to_user_id = :u
            """),
            {"t": f.timeline_id, "u": f.creator_user_id},
        ).one()
        assert grant_row.consumed_at is None
        assert grant_row.consumed_by_campaign_id is None

    with client_factory(f.creator_user_id) as client:
        retried = client.post(
            "/campaigns",
            json=_body(f, name="Forced Failure Retry"),
            headers={"Idempotency-Key": key},
        )
    assert retried.status_code == 201, retried.text
