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

from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_membership_character_relationship,
    make_membership_role,
    make_relationship_type_capability,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
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
