"""`dnd_ai.queries.bootstrap.get_session_bootstrap` — the authoritative
`/auth/session` portal-bootstrap query (docs/PLAN.md §23.4, §23.7 — Phase
13B blocker 2).

Every test builds its own campaign/membership/role/character graph with
`tests/factories.py` builders on the function-scoped, always-rolled-back
`db_connection` fixture and calls `get_session_bootstrap` directly — the
same "exercise the query function against a real database, not a mock"
discipline `tests/database/test_query_*` modules already establish for
their own domains. HTTP-layer concerns (the `/auth/session` envelope
shape, CSRF/`browser_session_id` for a cookie vs. OIDC caller,
unauthenticated 401) are covered separately in
`tests/database/test_api_local_auth.py`.
"""

import uuid

import pytest
from sqlalchemy import Connection, text

from dnd_ai.api.access import resolve_party_perspective
from dnd_ai.domain.access import resolve_access_context
from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_campaign_party,
    make_character,
    make_membership_character_relationship,
    make_membership_role,
    make_party,
    make_party_membership,
    make_relationship_type_capability,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database


@pytest.fixture
def world_id(db_connection: Connection) -> uuid.UUID:
    return make_world(db_connection, slug=f"bootstrap-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def timeline_id(db_connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    return make_timeline(db_connection, world_id, is_primary=True)


@pytest.fixture
def user_id(db_connection: Connection) -> uuid.UUID:
    return make_user(db_connection, "Bootstrap Tester")


def _capability_id(db_connection: Connection, code: str) -> uuid.UUID:
    """`security.capabilities` is already seeded with the full closed
    vocabulary (migration 080) — every capability code this test module
    uses is one of those seeded rows, looked up rather than re-inserted
    (its `code` column is `UNIQUE`, so inserting a duplicate would raise)."""
    return lookup_id(db_connection, "security", "capabilities", "capability_id", code)


def _character_relationship_type_id(db_connection: Connection, code: str) -> uuid.UUID:
    """`security.character_relationship_types` is likewise already seeded
    with its full closed vocabulary (migration 080) — same reasoning as
    `_capability_id` above."""
    return lookup_id(
        db_connection,
        "security",
        "character_relationship_types",
        "character_relationship_type_id",
        code,
    )


def _make_role_with_capabilities(
    db_connection: Connection, *, campaign_id: uuid.UUID, code: str, capability_codes: list[str]
) -> uuid.UUID:
    role_id = make_role(db_connection, campaign_id=campaign_id, code=code)
    for capability_code in capability_codes:
        make_role_capability(db_connection, role_id, _capability_id(db_connection, capability_code))
    return role_id


# ---------------------------------------------------------------------------
# No campaigns
# ---------------------------------------------------------------------------


def test_no_campaign_membership_returns_empty_campaigns_and_null_selection(
    db_connection: Connection, user_id: uuid.UUID
) -> None:
    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)
    assert bootstrap.user_id == user_id
    assert bootstrap.campaigns == ()
    assert bootstrap.selected_campaign_id is None


def test_display_name_is_returned(db_connection: Connection) -> None:
    user_id = make_user(db_connection, "Distinctive Display Name")
    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)
    assert bootstrap.display_name == "Distinctive Display Name"


# ---------------------------------------------------------------------------
# GM / player / observer membership, roles, capabilities
# ---------------------------------------------------------------------------


def test_gm_membership_includes_canon_edit_capability(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "GM Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    gm_role_id = _make_role_with_capabilities(
        db_connection, campaign_id=campaign_id, code="gm", capability_codes=["canon.edit"]
    )
    make_membership_role(db_connection, membership_id, gm_role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert len(bootstrap.campaigns) == 1
    campaign = bootstrap.campaigns[0]
    assert campaign.campaign_id == campaign_id
    assert campaign.roles == ("gm",)
    assert "canon.edit" in campaign.capabilities


def test_player_membership_has_no_canon_edit_capability(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Player Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    player_role_id = _make_role_with_capabilities(
        db_connection,
        campaign_id=campaign_id,
        code="player",
        capability_codes=["campaign.view"],
    )
    make_membership_role(db_connection, membership_id, player_role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    campaign = bootstrap.campaigns[0]
    assert campaign.roles == ("player",)
    assert "canon.edit" not in campaign.capabilities
    assert "campaign.view" in campaign.capabilities


def test_observer_membership_has_only_observer_role(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Observer Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    observer_role_id = _make_role_with_capabilities(
        db_connection, campaign_id=campaign_id, code="observer", capability_codes=[]
    )
    make_membership_role(db_connection, membership_id, observer_role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    campaign = bootstrap.campaigns[0]
    assert campaign.roles == ("observer",)
    assert campaign.capabilities == ()


def test_multiple_roles_are_all_returned(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Multi-Role Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    gm_role_id = _make_role_with_capabilities(
        db_connection, campaign_id=campaign_id, code="gm", capability_codes=["canon.edit"]
    )
    assistant_role_id = _make_role_with_capabilities(
        db_connection,
        campaign_id=campaign_id,
        code="assistant_gm",
        capability_codes=["character.interact"],
    )
    make_membership_role(db_connection, membership_id, gm_role_id)
    make_membership_role(db_connection, membership_id, assistant_role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    campaign = bootstrap.campaigns[0]
    assert set(campaign.roles) == {"gm", "assistant_gm"}
    assert "canon.edit" in campaign.capabilities
    assert "character.interact" in campaign.capabilities


def test_revoked_role_is_excluded(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Revoked Role Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    role_id = _make_role_with_capabilities(
        db_connection, campaign_id=campaign_id, code="gm", capability_codes=["canon.edit"]
    )
    make_membership_role(db_connection, membership_id, role_id, revoked=True)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    campaign = bootstrap.campaigns[0]
    assert campaign.roles == ()
    assert campaign.capabilities == ()


# ---------------------------------------------------------------------------
# Multiple campaigns, deterministic selection
# ---------------------------------------------------------------------------


def test_multiple_campaigns_are_returned_in_deterministic_order(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_b = make_campaign(db_connection, timeline_id, "B Campaign")
    campaign_a = make_campaign(db_connection, timeline_id, "A Campaign")
    make_campaign_membership(db_connection, campaign_b, user_id)
    make_campaign_membership(db_connection, campaign_a, user_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert [c.campaign_name for c in bootstrap.campaigns] == ["A Campaign", "B Campaign"]
    assert bootstrap.selected_campaign_id == campaign_a


def test_ended_membership_is_excluded(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Departed Campaign")
    make_campaign_membership(db_connection, campaign_id, user_id, ended=True)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.campaigns == ()


def test_suspended_membership_status_is_excluded(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Suspended Campaign")
    make_campaign_membership(db_connection, campaign_id, user_id, status_code="suspended")

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.campaigns == ()


def test_non_active_campaign_lifecycle_status_is_excluded(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(
        db_connection, timeline_id, "Archived Campaign", lifecycle_status_code="archived"
    )
    make_campaign_membership(db_connection, campaign_id, user_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.campaigns == ()


def test_membership_revocation_is_reflected_on_the_next_call(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Soon Revoked Campaign")
    make_campaign_membership(db_connection, campaign_id, user_id)
    assert len(get_session_bootstrap(db_connection, user_id=user_id).campaigns) == 1

    db_connection.execute(
        text("""
            UPDATE security.campaign_memberships
            SET ended_at = now() + interval '1 microsecond'
            WHERE campaign_id = :campaign AND user_id = :user
        """),
        {"campaign": campaign_id, "user": user_id},
    )

    assert get_session_bootstrap(db_connection, user_id=user_id).campaigns == ()


# ---------------------------------------------------------------------------
# Character perspectives
# ---------------------------------------------------------------------------


def test_character_relationship_with_capability_is_a_selectable_perspective(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Perspective Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Aldric")
    relationship_type_id = _character_relationship_type_id(db_connection, "owner")
    capability_id = _capability_id(db_connection, "character.control")
    make_relationship_type_capability(db_connection, relationship_type_id, capability_id)
    make_membership_character_relationship(
        db_connection, membership_id, character_id, relationship_type_id
    )

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    campaign = bootstrap.campaigns[0]
    assert len(campaign.character_perspectives) == 1
    perspective = campaign.character_perspectives[0]
    assert perspective.character_id == character_id
    assert perspective.character_name == "Aldric"
    assert campaign.selected_character_id == character_id


def test_character_perspective_exposes_only_its_authorized_current_parties(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Phase 13D §4: the portal must be handed the exact `party_id`s
    `resolve_party_perspective` will accept for a character — current
    membership on the campaign's timeline, party associated with the
    campaign — never guess one."""
    campaign_id = make_campaign(db_connection, timeline_id, "Party Perspective Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Kestrel")
    relationship_type_id = _character_relationship_type_id(db_connection, "owner")
    make_relationship_type_capability(
        db_connection,
        relationship_type_id,
        _capability_id(db_connection, "character.view_knowledge"),
    )
    make_membership_character_relationship(
        db_connection, membership_id, character_id, relationship_type_id
    )

    wt = make_world_time(db_connection, world_id, 100)
    joined_party = make_party(db_connection, world_id, name="Current Crew")
    make_campaign_party(db_connection, campaign_id, joined_party)
    make_party_membership(db_connection, timeline_id, joined_party, character_id, wt)

    # A party the character left — must NOT be offered.
    left_party = make_party(db_connection, world_id, name="Old Crew")
    make_campaign_party(db_connection, campaign_id, left_party)
    later = make_world_time(db_connection, world_id, 200)
    make_party_membership(
        db_connection, timeline_id, left_party, character_id, wt, effective_to_world_time_id=later
    )

    # A campaign party the character was never in — must NOT be offered.
    unrelated_party = make_party(db_connection, world_id, name="Strangers")
    make_campaign_party(db_connection, campaign_id, unrelated_party)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    (perspective,) = bootstrap.campaigns[0].character_perspectives
    assert [p.party_id for p in perspective.authorized_parties] == [joined_party]
    assert perspective.authorized_parties[0].party_name == "Current Crew"


def test_character_relationship_with_no_mapped_capability_is_not_selectable(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "No Capability Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Ghostly")
    relationship_type_id = _character_relationship_type_id(db_connection, "former_controller")
    # Deliberately no make_relationship_type_capability call — this
    # relationship type grants no capability at all.
    make_membership_character_relationship(
        db_connection, membership_id, character_id, relationship_type_id
    )

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    campaign = bootstrap.campaigns[0]
    assert campaign.character_perspectives == ()
    assert campaign.selected_character_id is None


def test_revoked_character_relationship_is_not_selectable(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Revoked Relationship Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Revoked")
    relationship_type_id = _character_relationship_type_id(db_connection, "viewer")
    capability_id = _capability_id(db_connection, "character.view_summary")
    make_relationship_type_capability(db_connection, relationship_type_id, capability_id)
    make_membership_character_relationship(
        db_connection, membership_id, character_id, relationship_type_id, revoked=True
    )

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.campaigns[0].character_perspectives == ()


def test_multiple_perspectives_leave_selected_character_null(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Two Character Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    relationship_type_id = _character_relationship_type_id(db_connection, "co_controller")
    capability_id = _capability_id(db_connection, "character.control")
    make_relationship_type_capability(db_connection, relationship_type_id, capability_id)
    for name in ("First", "Second"):
        character_id = make_character(db_connection, world_id, name=name)
        make_membership_character_relationship(
            db_connection, membership_id, character_id, relationship_type_id
        )

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    campaign = bootstrap.campaigns[0]
    assert len(campaign.character_perspectives) == 2
    assert campaign.selected_character_id is None


def test_relationship_revocation_is_reflected_on_the_next_call(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Soon Revoked Character Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Soon Gone")
    relationship_type_id = _character_relationship_type_id(db_connection, "owner")
    capability_id = _capability_id(db_connection, "character.control")
    make_relationship_type_capability(db_connection, relationship_type_id, capability_id)
    relationship_id = make_membership_character_relationship(
        db_connection, membership_id, character_id, relationship_type_id
    )
    assert (
        len(
            get_session_bootstrap(db_connection, user_id=user_id)
            .campaigns[0]
            .character_perspectives
        )
        == 1
    )

    db_connection.execute(
        text(
            "UPDATE security.membership_character_relationships "
            "SET revoked_at = now() WHERE membership_character_relationship_id = :r"
        ),
        {"r": relationship_id},
    )

    assert (
        get_session_bootstrap(db_connection, user_id=user_id).campaigns[0].character_perspectives
        == ()
    )


# ---------------------------------------------------------------------------
# Issue 2: authorized_parties only for characters the perspective resolver
# can actually use (character.view_knowledge held)
# ---------------------------------------------------------------------------


def _view_knowledge_perspective(
    db_connection: Connection,
    *,
    membership_id: uuid.UUID,
    character_id: uuid.UUID,
    relationship_type_code: str,
) -> uuid.UUID:
    relationship_type_id = _character_relationship_type_id(db_connection, relationship_type_code)
    make_relationship_type_capability(
        db_connection,
        relationship_type_id,
        _capability_id(db_connection, "character.view_knowledge"),
    )
    return make_membership_character_relationship(
        db_connection, membership_id, character_id, relationship_type_id
    )


def test_a_discover_only_character_advertises_no_party_perspectives(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """A character the user can only *discover* (a relationship mapped to
    `character.discover`, not `character.view_knowledge`) still appears in
    the perspective list — but `authorized_parties` is empty, because
    `resolve_party_perspective` would reject any party for it."""
    campaign_id = make_campaign(db_connection, timeline_id, "Discover Only Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Barely Known")
    relationship_type_id = _character_relationship_type_id(db_connection, "viewer")
    make_relationship_type_capability(
        db_connection,
        relationship_type_id,
        _capability_id(db_connection, "character.discover"),
    )
    make_membership_character_relationship(
        db_connection, membership_id, character_id, relationship_type_id
    )
    wt = make_world_time(db_connection, world_id, 100)
    party = make_party(db_connection, world_id, name="A Party It Is In")
    make_campaign_party(db_connection, campaign_id, party)
    make_party_membership(db_connection, timeline_id, party, character_id, wt)

    (perspective,) = (
        get_session_bootstrap(db_connection, user_id=user_id).campaigns[0].character_perspectives
    )
    assert perspective.character_id == character_id
    assert perspective.authorized_parties == ()


def test_revoking_character_view_knowledge_stops_advertising_parties_next_call(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Revoke View Knowledge Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Was Trusted")
    relationship_id = _view_knowledge_perspective(
        db_connection,
        membership_id=membership_id,
        character_id=character_id,
        relationship_type_code="owner",
    )
    wt = make_world_time(db_connection, world_id, 100)
    party = make_party(db_connection, world_id, name="The Trusted Circle")
    make_campaign_party(db_connection, campaign_id, party)
    make_party_membership(db_connection, timeline_id, party, character_id, wt)

    before = get_session_bootstrap(db_connection, user_id=user_id).campaigns[0]
    assert [p.party_id for p in before.character_perspectives[0].authorized_parties] == [party]

    db_connection.execute(
        text(
            "UPDATE security.membership_character_relationships "
            "SET revoked_at = now() WHERE membership_character_relationship_id = :r"
        ),
        {"r": relationship_id},
    )

    after = get_session_bootstrap(db_connection, user_id=user_id).campaigns[0]
    # The relationship carried the only capability, so the whole perspective
    # is gone; either way, no party is advertised.
    assert all(p.authorized_parties == () for p in after.character_perspectives)


def test_a_party_not_associated_with_the_campaign_is_not_advertised(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Unassociated Party Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Kestrel")
    _view_knowledge_perspective(
        db_connection,
        membership_id=membership_id,
        character_id=character_id,
        relationship_type_code="owner",
    )
    wt = make_world_time(db_connection, world_id, 100)
    # A party the character is a current member of, but which is NOT a
    # `campaign.campaign_parties` party — `resolve_party_perspective`'s
    # `validate_campaign_party` would reject it.
    orphan_party = make_party(db_connection, world_id, name="Not In This Campaign")
    make_party_membership(db_connection, timeline_id, orphan_party, character_id, wt)

    (perspective,) = (
        get_session_bootstrap(db_connection, user_id=user_id).campaigns[0].character_perspectives
    )
    assert perspective.authorized_parties == ()


def test_every_advertised_party_resolves_through_the_real_perspective_resolver(
    db_connection: Connection, world_id: uuid.UUID, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """The contract: whatever `authorized_parties` the bootstrap hands the
    portal, `resolve_party_perspective` accepts every one for that
    character."""
    campaign_id = make_campaign(db_connection, timeline_id, "Round Trip Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    character_id = make_character(db_connection, world_id, name="Roundtrip")
    _view_knowledge_perspective(
        db_connection,
        membership_id=membership_id,
        character_id=character_id,
        relationship_type_code="owner",
    )
    wt = make_world_time(db_connection, world_id, 100)
    for name in ("Crew One", "Crew Two"):
        party = make_party(db_connection, world_id, name=name)
        make_campaign_party(db_connection, campaign_id, party)
        make_party_membership(db_connection, timeline_id, party, character_id, wt)

    (perspective,) = (
        get_session_bootstrap(db_connection, user_id=user_id).campaigns[0].character_perspectives
    )
    assert len(perspective.authorized_parties) == 2

    access = resolve_access_context(db_connection, user_id=user_id, campaign_id=campaign_id)
    assert access is not None
    for advertised in perspective.authorized_parties:
        resolved = resolve_party_perspective(
            db_connection,
            access=access,
            campaign_id=campaign_id,
            character_id=character_id,
            party_id=advertised.party_id,
        )
        assert resolved == advertised.party_id


# ---------------------------------------------------------------------------
# Effective capability differences between two memberships of the same
# campaign, and no disclosure of inaccessible campaigns
# ---------------------------------------------------------------------------


def test_two_users_in_the_same_campaign_see_different_capabilities(
    db_connection: Connection, timeline_id: uuid.UUID
) -> None:
    campaign_id = make_campaign(db_connection, timeline_id, "Shared Campaign")
    gm_user_id = make_user(db_connection, "GM User")
    player_user_id = make_user(db_connection, "Player User")
    gm_membership_id = make_campaign_membership(db_connection, campaign_id, gm_user_id)
    player_membership_id = make_campaign_membership(db_connection, campaign_id, player_user_id)
    gm_role_id = _make_role_with_capabilities(
        db_connection, campaign_id=campaign_id, code="gm", capability_codes=["canon.edit"]
    )
    player_role_id = _make_role_with_capabilities(
        db_connection,
        campaign_id=campaign_id,
        code="player",
        capability_codes=["campaign.view"],
    )
    make_membership_role(db_connection, gm_membership_id, gm_role_id)
    make_membership_role(db_connection, player_membership_id, player_role_id)

    gm_bootstrap = get_session_bootstrap(db_connection, user_id=gm_user_id)
    player_bootstrap = get_session_bootstrap(db_connection, user_id=player_user_id)

    assert "canon.edit" in gm_bootstrap.campaigns[0].capabilities
    assert "canon.edit" not in player_bootstrap.campaigns[0].capabilities


def test_no_disclosure_of_a_campaign_the_user_is_not_a_member_of(
    db_connection: Connection, timeline_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    accessible_campaign_id = make_campaign(db_connection, timeline_id, "Accessible")
    make_campaign_membership(db_connection, accessible_campaign_id, user_id)
    inaccessible_campaign_id = make_campaign(db_connection, timeline_id, "Secret Campaign")
    other_user_id = make_user(db_connection, "Someone Else")
    make_campaign_membership(db_connection, inaccessible_campaign_id, other_user_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    campaign_ids = {c.campaign_id for c in bootstrap.campaigns}
    assert accessible_campaign_id in campaign_ids
    assert inaccessible_campaign_id not in campaign_ids
    serialized = repr(bootstrap)
    assert "Secret Campaign" not in serialized


# ---------------------------------------------------------------------------
# World and timeline identity (Phase 13D — the additive world_id/world_name/
# timeline_id/timeline_name fields the portal's World -> Timeline -> Campaign
# hierarchy needs, docs/UI_DESIGN.md §4.1/§5.2)
# ---------------------------------------------------------------------------


def test_world_and_timeline_identity_is_returned_for_an_authorized_campaign(
    db_connection: Connection, user_id: uuid.UUID
) -> None:
    world_id = make_world(db_connection, slug=f"bw-{uuid.uuid4().hex[:8]}", name="Aeldrin Prime")
    timeline_id = make_timeline(db_connection, world_id, name="Prime Line", is_primary=True)
    campaign_id = make_campaign(db_connection, timeline_id, "Hierarchy Campaign")
    membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
    role_id = _make_role_with_capabilities(
        db_connection, campaign_id=campaign_id, code="player", capability_codes=["campaign.view"]
    )
    make_membership_role(db_connection, membership_id, role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    (campaign,) = bootstrap.campaigns
    assert campaign.world_id == world_id
    assert campaign.world_name == "Aeldrin Prime"
    assert campaign.timeline_id == timeline_id
    assert campaign.timeline_name == "Prime Line"


def test_two_campaigns_in_one_world_report_the_same_world(
    db_connection: Connection, user_id: uuid.UUID
) -> None:
    world_id = make_world(db_connection, slug=f"bw-{uuid.uuid4().hex[:8]}", name="Shared World")
    timeline_id = make_timeline(db_connection, world_id, is_primary=True)
    for name in ("Campaign One", "Campaign Two"):
        campaign_id = make_campaign(db_connection, timeline_id, name)
        membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
        role_id = _make_role_with_capabilities(
            db_connection,
            campaign_id=campaign_id,
            code=f"player_{uuid.uuid4().hex[:6]}",
            capability_codes=["campaign.view"],
        )
        make_membership_role(db_connection, membership_id, role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert len(bootstrap.campaigns) == 2
    assert {c.world_id for c in bootstrap.campaigns} == {world_id}
    assert {c.world_name for c in bootstrap.campaigns} == {"Shared World"}


def test_campaigns_in_different_worlds_report_their_own_world_each(
    db_connection: Connection, user_id: uuid.UUID
) -> None:
    worlds: dict[str, uuid.UUID] = {}
    for world_name in ("World Alpha", "World Beta"):
        world_id = make_world(db_connection, slug=f"bw-{uuid.uuid4().hex[:8]}", name=world_name)
        worlds[world_name] = world_id
        timeline_id = make_timeline(db_connection, world_id, is_primary=True)
        campaign_id = make_campaign(db_connection, timeline_id, f"{world_name} Campaign")
        membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
        role_id = _make_role_with_capabilities(
            db_connection,
            campaign_id=campaign_id,
            code=f"player_{uuid.uuid4().hex[:6]}",
            capability_codes=["campaign.view"],
        )
        make_membership_role(db_connection, membership_id, role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    by_world_name = {c.world_name: c.world_id for c in bootstrap.campaigns}
    assert by_world_name == worlds


def test_multiple_timelines_in_one_world_report_each_campaigns_own_timeline(
    db_connection: Connection, user_id: uuid.UUID
) -> None:
    world_id = make_world(db_connection, slug=f"bw-{uuid.uuid4().hex[:8]}", name="Branchy World")
    primary_timeline_id = make_timeline(db_connection, world_id, name="Trunk", is_primary=True)
    branch_world_time_id = make_world_time(db_connection, world_id, 100)
    branch_timeline_id = make_timeline(
        db_connection,
        world_id,
        name="Branch",
        parent_timeline_id=primary_timeline_id,
        branch_world_time_id=branch_world_time_id,
    )

    trunk_campaign_id = make_campaign(db_connection, primary_timeline_id, "Trunk Campaign")
    branch_campaign_id = make_campaign(db_connection, branch_timeline_id, "Branch Campaign")
    for campaign_id in (trunk_campaign_id, branch_campaign_id):
        membership_id = make_campaign_membership(db_connection, campaign_id, user_id)
        role_id = _make_role_with_capabilities(
            db_connection,
            campaign_id=campaign_id,
            code=f"player_{uuid.uuid4().hex[:6]}",
            capability_codes=["campaign.view"],
        )
        make_membership_role(db_connection, membership_id, role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    by_campaign = {c.campaign_id: c for c in bootstrap.campaigns}
    assert by_campaign[trunk_campaign_id].timeline_id == primary_timeline_id
    assert by_campaign[trunk_campaign_id].timeline_name == "Trunk"
    assert by_campaign[branch_campaign_id].timeline_id == branch_timeline_id
    assert by_campaign[branch_campaign_id].timeline_name == "Branch"
    # Both campaigns are in the same world regardless of timeline.
    assert {c.world_id for c in bootstrap.campaigns} == {world_id}


def test_an_inactive_membership_hides_its_world_and_timeline_entirely(
    db_connection: Connection, user_id: uuid.UUID
) -> None:
    world_id = make_world(db_connection, slug=f"bw-{uuid.uuid4().hex[:8]}", name="Suspended World")
    timeline_id = make_timeline(db_connection, world_id, name="Suspended Line", is_primary=True)
    campaign_id = make_campaign(db_connection, timeline_id, "Suspended Campaign")
    membership_id = make_campaign_membership(
        db_connection, campaign_id, user_id, status_code="suspended"
    )
    role_id = _make_role_with_capabilities(
        db_connection, campaign_id=campaign_id, code="player", capability_codes=["campaign.view"]
    )
    make_membership_role(db_connection, membership_id, role_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    assert bootstrap.campaigns == ()
    serialized = repr(bootstrap)
    assert "Suspended World" not in serialized
    assert "Suspended Line" not in serialized


def test_an_inaccessible_worlds_name_never_appears(
    db_connection: Connection, user_id: uuid.UUID
) -> None:
    my_world_id = make_world(db_connection, slug=f"bw-{uuid.uuid4().hex[:8]}", name="My World")
    my_timeline_id = make_timeline(db_connection, my_world_id, is_primary=True)
    my_campaign_id = make_campaign(db_connection, my_timeline_id, "Mine")
    my_membership_id = make_campaign_membership(db_connection, my_campaign_id, user_id)
    my_role_id = _make_role_with_capabilities(
        db_connection, campaign_id=my_campaign_id, code="p", capability_codes=["campaign.view"]
    )
    make_membership_role(db_connection, my_membership_id, my_role_id)

    other_world_id = make_world(
        db_connection, slug=f"bw-{uuid.uuid4().hex[:8]}", name="Forbidden World"
    )
    other_timeline_id = make_timeline(
        db_connection, other_world_id, name="Forbidden Line", is_primary=True
    )
    other_campaign_id = make_campaign(db_connection, other_timeline_id, "Not Mine")
    other_user_id = make_user(db_connection, "Other Player")
    make_campaign_membership(db_connection, other_campaign_id, other_user_id)

    bootstrap = get_session_bootstrap(db_connection, user_id=user_id)

    (campaign,) = bootstrap.campaigns
    assert campaign.world_id == my_world_id
    serialized = repr(bootstrap)
    assert "Forbidden World" not in serialized
    assert "Forbidden Line" not in serialized
