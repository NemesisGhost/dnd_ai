"""Tests for src/dnd_ai/domain/access.py — effective access resolution
(docs/architecture/DATABASE_MODEL.md §19.7). Exercises the resolver against
a real security.* schema (revision 080) rather than mocking the joins it
depends on.
"""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.domain.access import (
    UnauthorizedTimelineError,
    resolve_access_context,
    resolve_user_by_external_identity,
)
from tests.factories import (
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_capability,
    make_character,
    make_character_relationship_type,
    make_event,
    make_external_identity,
    make_knowledge_item,
    make_membership_character_relationship,
    make_membership_role,
    make_quest,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


class Fixture:
    """One campaign with a membership, plus one role, one character
    relationship type, one access group, and one target of each kind —
    enough to exercise every §19.7 resolution step without a dedicated
    scenario per test."""

    def __init__(self, connection: Connection) -> None:
        self.world_id = make_world(connection, slug="access-resolution-world")
        self.timeline_id = make_timeline(connection, self.world_id, "Primary", is_primary=True)
        self.other_timeline_id = make_timeline(
            connection, self.world_id, "Branch", is_primary=False
        )
        self.campaign_id = make_campaign(connection, self.timeline_id)
        self.character_id = make_character(connection, self.world_id, name="PC")

        self.user_id = make_user(connection, "Access Test User")
        self.membership_id = make_campaign_membership(connection, self.campaign_id, self.user_id)

        self.role_id = make_role(connection, campaign_id=self.campaign_id)
        self.role_capability_id = make_capability(connection, "test.role_capability")
        make_role_capability(connection, self.role_id, self.role_capability_id)

        self.relationship_type_id = make_character_relationship_type(connection)
        self.relationship_capability_id = make_capability(
            connection, "test.relationship_capability"
        )
        make_relationship_type_capability(
            connection, self.relationship_type_id, self.relationship_capability_id
        )

        self.access_group_id = make_access_group(connection, self.campaign_id)
        self.quest_id = make_quest(connection, self.world_id)
        self.knowledge_item_id = make_knowledge_item(connection, self.world_id)
        self.session_id = make_session(connection, self.campaign_id, 1)
        world_time = make_world_time(connection, self.world_id, 100)
        self.event_id = make_event(
            connection, self.world_id, self.timeline_id, world_time, campaign_id=self.campaign_id
        )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection)


# ---------------------------------------------------------------------------
# Membership gate (§19.7 step 2)
# ---------------------------------------------------------------------------


def test_returns_none_without_a_membership(db_connection: Connection, f: Fixture) -> None:
    stranger_id = make_user(db_connection, "Stranger")
    assert (
        resolve_access_context(db_connection, user_id=stranger_id, campaign_id=f.campaign_id)
        is None
    )


def test_returns_none_for_ended_membership(db_connection: Connection, f: Fixture) -> None:
    user_id = make_user(db_connection, "Departed")
    make_campaign_membership(
        db_connection, f.campaign_id, user_id, status_code="departed", ended=True
    )
    assert resolve_access_context(db_connection, user_id=user_id, campaign_id=f.campaign_id) is None


def test_returns_none_for_suspended_membership(db_connection: Connection, f: Fixture) -> None:
    user_id = make_user(db_connection, "Suspended")
    make_campaign_membership(db_connection, f.campaign_id, user_id, status_code="suspended")
    assert resolve_access_context(db_connection, user_id=user_id, campaign_id=f.campaign_id) is None


def test_resolves_for_active_membership_with_no_grants(
    db_connection: Connection, f: Fixture
) -> None:
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.campaign_membership_id == f.membership_id
    assert ctx.timeline_id == f.timeline_id
    assert ctx.has_capability("test.role_capability") is False


# ---------------------------------------------------------------------------
# Timeline scope (§19.7 step 3, finding 2) — only a campaign's own pinned
# timeline is a valid resolution scope; see resolve_access_context's
# docstring for the rule and why. A same-world non-branch timeline, a
# branch descended from the campaign's own timeline, and a timeline from a
# different world are all rejected identically: none of them is the
# campaign's own timeline.
# ---------------------------------------------------------------------------


def test_accepts_explicit_campaign_own_timeline(db_connection: Connection, f: Fixture) -> None:
    ctx = resolve_access_context(
        db_connection, user_id=f.user_id, campaign_id=f.campaign_id, timeline_id=f.timeline_id
    )
    assert ctx is not None
    assert ctx.timeline_id == f.timeline_id


def test_rejects_different_same_world_timeline(db_connection: Connection, f: Fixture) -> None:
    # f.other_timeline_id is a second, unrelated root timeline in the same
    # world as the campaign (not a branch of it, not the campaign's own).
    with pytest.raises(UnauthorizedTimelineError):
        resolve_access_context(
            db_connection,
            user_id=f.user_id,
            campaign_id=f.campaign_id,
            timeline_id=f.other_timeline_id,
        )


def test_rejects_branch_of_the_campaign_timeline(db_connection: Connection, f: Fixture) -> None:
    """A branch descended from the campaign's own timeline is still not the
    campaign's own timeline, so it is rejected exactly like any other
    non-matching timeline — see resolve_access_context's docstring: the
    domain model gives a campaign exactly one pinned timeline to resolve
    access against, and does not extend that to descendant branches."""
    branch_world_time_id = make_world_time(db_connection, f.world_id, 50)
    branch_timeline_id = make_timeline(
        db_connection,
        f.world_id,
        "Branch of campaign timeline",
        parent_timeline_id=f.timeline_id,
        branch_world_time_id=branch_world_time_id,
    )
    with pytest.raises(UnauthorizedTimelineError):
        resolve_access_context(
            db_connection,
            user_id=f.user_id,
            campaign_id=f.campaign_id,
            timeline_id=branch_timeline_id,
        )


def test_rejects_different_world_timeline(db_connection: Connection, f: Fixture) -> None:
    other_world_id = make_world(db_connection, slug="access-resolution-other-world")
    other_world_timeline_id = make_timeline(
        db_connection, other_world_id, "Other World Primary", is_primary=True
    )
    with pytest.raises(UnauthorizedTimelineError):
        resolve_access_context(
            db_connection,
            user_id=f.user_id,
            campaign_id=f.campaign_id,
            timeline_id=other_world_timeline_id,
        )


# ---------------------------------------------------------------------------
# Role-derived capabilities (§19.7 step 4)
# ---------------------------------------------------------------------------


def test_active_membership_role_grants_capability(db_connection: Connection, f: Fixture) -> None:
    make_membership_role(db_connection, f.membership_id, f.role_id)
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability") is True
    assert ctx.has_capability("test.relationship_capability") is False


def test_revoked_membership_role_does_not_grant_capability(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_role(db_connection, f.membership_id, f.role_id, revoked=True)
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability") is False


def test_expired_membership_role_does_not_grant_capability(
    db_connection: Connection, f: Fixture
) -> None:
    role_id = make_membership_role(db_connection, f.membership_id, f.role_id)
    # now() is frozen for the whole test transaction (transaction_timestamp semantics), so an
    # already-expired row can only be built with explicit past literals, not now()-relative
    # arithmetic — otherwise granted_at (defaulted from now()) and the resolver's own now()
    # comparison would always agree.
    db_connection.execute(
        text(
            "UPDATE security.membership_roles "
            "SET granted_at = '2020-01-01T00:00:00Z', expires_at = '2020-06-01T00:00:00Z' "
            "WHERE membership_role_id = :r"
        ),
        {"r": role_id},
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability") is False


def test_inactive_role_does_not_grant_capability(db_connection: Connection, f: Fixture) -> None:
    make_membership_role(db_connection, f.membership_id, f.role_id)
    db_connection.execute(
        text("UPDATE security.roles SET is_active = false WHERE role_id = :r"), {"r": f.role_id}
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability") is False


# ---------------------------------------------------------------------------
# Character relationship-derived capabilities (§19.7 step 5)
# ---------------------------------------------------------------------------


def test_character_relationship_grants_capability_for_that_character_only(
    db_connection: Connection, f: Fixture
) -> None:
    other_character_id = make_character(db_connection, f.world_id, name="Other PC")
    make_membership_character_relationship(
        db_connection, f.membership_id, f.character_id, f.relationship_type_id
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.relationship_capability", character_id=f.character_id) is True
    assert (
        ctx.has_capability("test.relationship_capability", character_id=other_character_id) is False
    )
    assert ctx.has_capability("test.relationship_capability") is False


def test_revoked_character_relationship_does_not_grant_capability(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_character_relationship(
        db_connection, f.membership_id, f.character_id, f.relationship_type_id, revoked=True
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.relationship_capability", character_id=f.character_id) is False


def test_character_relationship_scoped_to_a_different_timeline_does_not_apply(
    db_connection: Connection, f: Fixture
) -> None:
    """A relationship row scoped to a timeline other than the campaign's own
    is excluded from resolution against the campaign's own timeline — it is
    not reachable at all otherwise, since resolve_access_context now only
    ever resolves against the campaign's own timeline (see the timeline
    scope tests above)."""
    make_membership_character_relationship(
        db_connection,
        f.membership_id,
        f.character_id,
        f.relationship_type_id,
        timeline_id=f.other_timeline_id,
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.relationship_capability", character_id=f.character_id) is False


# ---------------------------------------------------------------------------
# Resource grants (§19.7 step 7)
# ---------------------------------------------------------------------------


def test_allow_grant_extends_capability_beyond_role_defaults(
    db_connection: Connection, f: Fixture
) -> None:
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_campaign_membership_id=f.membership_id,
        quest_id=f.quest_id,
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability", quest_id=f.quest_id) is True
    # Unscoped and other-target checks are unaffected by a grant tied to one quest.
    assert ctx.has_capability("test.role_capability") is False


def test_deny_grant_overrides_role_capability_for_its_target(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_role(db_connection, f.membership_id, f.role_id)
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_campaign_membership_id=f.membership_id,
        entity_id=f.character_id,
        effect="deny",
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability") is True
    assert ctx.has_capability("test.role_capability", entity_id=f.character_id) is False


def test_grant_via_access_group_membership_applies(db_connection: Connection, f: Fixture) -> None:
    make_access_group_membership(db_connection, f.access_group_id, f.membership_id)
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_access_group_id=f.access_group_id,
        session_id=f.session_id,
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability", session_id=f.session_id) is True


def test_removed_access_group_membership_grant_does_not_apply(
    db_connection: Connection, f: Fixture
) -> None:
    make_access_group_membership(db_connection, f.access_group_id, f.membership_id, removed=True)
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_access_group_id=f.access_group_id,
        session_id=f.session_id,
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability", session_id=f.session_id) is False


def test_revoked_grant_does_not_apply(db_connection: Connection, f: Fixture) -> None:
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_campaign_membership_id=f.membership_id,
        event_id=f.event_id,
        revoked=True,
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert ctx.has_capability("test.role_capability", event_id=f.event_id) is False


def test_expired_grant_does_not_apply(db_connection: Connection, f: Fixture) -> None:
    grant_id = make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_campaign_membership_id=f.membership_id,
        knowledge_item_id=f.knowledge_item_id,
    )
    db_connection.execute(
        text(
            "UPDATE security.resource_grants "
            "SET granted_at = '2020-01-01T00:00:00Z', expires_at = '2020-06-01T00:00:00Z' "
            "WHERE resource_grant_id = :g"
        ),
        {"g": grant_id},
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    assert (
        ctx.has_capability("test.role_capability", knowledge_item_id=f.knowledge_item_id) is False
    )


def test_has_capability_rejects_more_than_one_target(db_connection: Connection, f: Fixture) -> None:
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    with pytest.raises(ValueError, match="at most one resource target"):
        ctx.has_capability("test.role_capability", character_id=f.character_id, quest_id=f.quest_id)


# ---------------------------------------------------------------------------
# resource_grant_targets — per-row authorization for list endpoints
# (dnd_ai.api.summary's campaign-summary correction pass)
# ---------------------------------------------------------------------------


def test_resource_grant_targets_returns_denied_and_allowed_ids_separately(
    db_connection: Connection, f: Fixture
) -> None:
    other_event_world_time_id = make_world_time(db_connection, f.world_id, 200)
    other_event_id = make_event(
        db_connection,
        f.world_id,
        f.timeline_id,
        other_event_world_time_id,
        campaign_id=f.campaign_id,
    )
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_campaign_membership_id=f.membership_id,
        event_id=f.event_id,
        effect="deny",
    )
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_campaign_membership_id=f.membership_id,
        event_id=other_event_id,
        effect="allow",
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    denied, allowed = ctx.resource_grant_targets("test.role_capability", field_name="event_id")
    assert denied == frozenset({f.event_id})
    assert allowed == frozenset({other_event_id})


def test_resource_grant_targets_ignores_other_capabilities_and_target_fields(
    db_connection: Connection, f: Fixture
) -> None:
    """A grant for a different capability, and a grant targeting a
    different field (quest_id rather than event_id), must not leak into
    either returned set — resource_grant_targets is scoped to exactly the
    (capability_code, field_name) pair it was asked about."""
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.role_capability_id,
        grantee_campaign_membership_id=f.membership_id,
        quest_id=f.quest_id,
        effect="deny",
    )
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.relationship_capability_id,
        grantee_campaign_membership_id=f.membership_id,
        event_id=f.event_id,
        effect="deny",
    )
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    denied, allowed = ctx.resource_grant_targets("test.role_capability", field_name="event_id")
    assert denied == frozenset()
    assert allowed == frozenset()


def test_resource_grant_targets_rejects_an_unknown_field_name(
    db_connection: Connection, f: Fixture
) -> None:
    ctx = resolve_access_context(db_connection, user_id=f.user_id, campaign_id=f.campaign_id)
    assert ctx is not None
    with pytest.raises(ValueError, match="not a resource-grant target column"):
        ctx.resource_grant_targets("test.role_capability", field_name="not_a_real_column")


# ---------------------------------------------------------------------------
# External identity resolution (§19.7 step 1)
# ---------------------------------------------------------------------------


def test_resolve_user_by_external_identity_finds_linked_user(
    db_connection: Connection, f: Fixture
) -> None:
    make_external_identity(
        db_connection, f.user_id, issuer="https://idp.example", subject="sub-123"
    )
    resolved = resolve_user_by_external_identity(
        db_connection, issuer="https://idp.example", subject="sub-123"
    )
    assert resolved == f.user_id


def test_resolve_user_by_external_identity_ignores_revoked_link(
    db_connection: Connection, f: Fixture
) -> None:
    make_external_identity(
        db_connection, f.user_id, issuer="https://idp.example", subject="sub-456", revoked=True
    )
    resolved = resolve_user_by_external_identity(
        db_connection, issuer="https://idp.example", subject="sub-456"
    )
    assert resolved is None


def test_resolve_user_by_external_identity_unknown_pair_returns_none(
    db_connection: Connection,
) -> None:
    resolved = resolve_user_by_external_identity(
        db_connection, issuer="https://idp.example", subject=str(uuid.uuid4())
    )
    assert resolved is None


def test_resolve_user_by_external_identity_rejects_inactive_linked_user(
    db_connection: Connection,
) -> None:
    """A revoked *identity* is already covered above; this proves the
    other half — a still-active, non-revoked identity linked to a user
    whose own lifecycle status is no longer 'active' must not
    authenticate either (finding: inactive users could still
    authenticate)."""
    archived_user_id = make_user(db_connection, "Archived User", status_code="archived")
    make_external_identity(
        db_connection, archived_user_id, issuer="https://idp.example", subject="sub-archived"
    )
    resolved = resolve_user_by_external_identity(
        db_connection, issuer="https://idp.example", subject="sub-archived"
    )
    assert resolved is None


def test_resolve_user_by_external_identity_ignores_lookup_row_availability(
    db_connection: Connection,
) -> None:
    """`core.lifecycle_statuses.is_active` means whether that *value* is
    currently offered for *new* assignment (docs/architecture/
    DATABASE_MODEL.md §19, revision 080's "Deliberate scoping decisions")
    — it must not retroactively affect a user already assigned 'active'.
    This mutates the shared seeded 'active' row, but only inside
    `db_connection`'s own transaction, which always rolls back at
    teardown (tests/conftest.py) — never visible to any other test or
    connection, and never committed."""
    active_user_id = make_user(db_connection, "Already Active User", status_code="active")
    make_external_identity(
        db_connection, active_user_id, issuer="https://idp.example", subject="sub-already-active"
    )

    db_connection.execute(
        text("UPDATE core.lifecycle_statuses SET is_active = false WHERE code = 'active'")
    )

    resolved = resolve_user_by_external_identity(
        db_connection, issuer="https://idp.example", subject="sub-already-active"
    )
    assert resolved == active_user_id
