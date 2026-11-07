"""Tests for the P-8 CTI-column guard in `dnd_ai.commands.access_grants.
create_resource_grant` (Phase 13E checkpoint 12).

`character.characters`/`narrative.quests`/`narrative.events`/`knowledge.
knowledge_items` all key off `core.entities(entity_id)` via class-table
inheritance, so one UUID can satisfy several of the six mutually
exclusive resource-grant target columns at once. Writing such a UUID to
`entity_id` instead of its own dedicated column is a silent authorization
no-op: the read side always keys off a specific column, so the grant
never matches any real reader while still displaying as active on the
access overview. This file proves `create_resource_grant` now rejects an
`entity_id` target whose underlying entity type belongs to one of the
four kinds with their own column, and that each of those four kinds still
grants correctly through its own column.

The one exception is a character (P03-A A2a-R, DEF-018): `campaign.view` and `canon.edit` on a
character are read by every reader under `entity_id` (the whole-character deny and the
per-character `canon.edit` deny, ADR 0021 section 2.9 and decision D8), and `character_id`'s
catalog cannot carry them. So a `character`, `npc` or `player_character` entity is accepted as an
`entity_id` target for a **deny** of those two codes, and refused for an allow, for any
`character.*` code, and for every other own-column kind.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.access_grants import (
    ResourceGrantCapabilityNotGrantableError,
    TargetNotInCampaignWorldError,
    create_resource_grant,
    revoke_resource_grant,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_entity,
    make_event,
    make_knowledge_item,
    make_quest,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

_CAMPAIGN_VIEW_CAPABILITY_CODE = "campaign.view"


class _Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "CTI Guard Campaign", lifecycle_status_code="active"
        )
        self.grantor_membership_id = make_campaign_membership(
            connection, self.campaign_id, make_user(connection, "CTI Guard Grantor")
        )
        self.grantee_membership_id = make_campaign_membership(
            connection, self.campaign_id, make_user(connection, "CTI Guard Grantee")
        )


def test_entity_id_rejects_a_quest_target(db_connection: Connection) -> None:
    f = _Fixture(db_connection, "cti-guard-quest")
    quest_id = make_quest(db_connection, f.world_id)

    with pytest.raises(TargetNotInCampaignWorldError):
        create_resource_grant(
            db_connection,
            campaign_id=f.campaign_id,
            grantee_campaign_membership_id=f.grantee_membership_id,
            grantee_access_group_id=None,
            capability_code=_CAMPAIGN_VIEW_CAPABILITY_CODE,
            effect="allow",
            expected_world_id=f.world_id,
            granted_by_membership_id=f.grantor_membership_id,
            entity_id=quest_id,
        )


def test_entity_id_rejects_an_event_target(db_connection: Connection) -> None:
    f = _Fixture(db_connection, "cti-guard-event")
    world_time_id = make_world_time(db_connection, f.world_id, 0)
    event_id = make_event(db_connection, f.world_id, f.timeline_id, world_time_id)

    with pytest.raises(TargetNotInCampaignWorldError):
        create_resource_grant(
            db_connection,
            campaign_id=f.campaign_id,
            grantee_campaign_membership_id=f.grantee_membership_id,
            grantee_access_group_id=None,
            capability_code=_CAMPAIGN_VIEW_CAPABILITY_CODE,
            effect="allow",
            expected_world_id=f.world_id,
            granted_by_membership_id=f.grantor_membership_id,
            entity_id=event_id,
        )


def test_entity_id_rejects_a_knowledge_item_target(db_connection: Connection) -> None:
    f = _Fixture(db_connection, "cti-guard-knowledge")
    knowledge_item_id = make_knowledge_item(db_connection, f.world_id)

    with pytest.raises(TargetNotInCampaignWorldError):
        create_resource_grant(
            db_connection,
            campaign_id=f.campaign_id,
            grantee_campaign_membership_id=f.grantee_membership_id,
            grantee_access_group_id=None,
            capability_code=_CAMPAIGN_VIEW_CAPABILITY_CODE,
            effect="allow",
            expected_world_id=f.world_id,
            granted_by_membership_id=f.grantor_membership_id,
            entity_id=knowledge_item_id,
        )


def test_entity_id_rejects_a_character_target(db_connection: Connection) -> None:
    f = _Fixture(db_connection, "cti-guard-character")
    character_id = make_character(db_connection, f.world_id, name="CTI Guard Character")

    with pytest.raises(TargetNotInCampaignWorldError):
        create_resource_grant(
            db_connection,
            campaign_id=f.campaign_id,
            grantee_campaign_membership_id=f.grantee_membership_id,
            grantee_access_group_id=None,
            capability_code=_CAMPAIGN_VIEW_CAPABILITY_CODE,
            effect="allow",
            expected_world_id=f.world_id,
            granted_by_membership_id=f.grantor_membership_id,
            entity_id=character_id,
        )


def test_entity_id_still_accepts_a_genuine_location_entity(db_connection: Connection) -> None:
    """The guard must not overreach: a real location (no dedicated column
    of its own) still grants correctly through entity_id."""
    f = _Fixture(db_connection, "cti-guard-location")
    location_type_id = lookup_id(
        db_connection, "core", "entity_types", "entity_type_id", "location"
    )
    location_id = make_entity(
        db_connection, f.world_id, location_type_id, name="CTI Guard Location"
    )

    result = create_resource_grant(
        db_connection,
        campaign_id=f.campaign_id,
        grantee_campaign_membership_id=f.grantee_membership_id,
        grantee_access_group_id=None,
        capability_code=_CAMPAIGN_VIEW_CAPABILITY_CODE,
        effect="allow",
        expected_world_id=f.world_id,
        granted_by_membership_id=f.grantor_membership_id,
        entity_id=location_id,
    )
    assert result.resource_grant_id is not None


# --- a character's campaign.view / canon.edit deny under entity_id (A2a-R, DEF-018) ------------------


def _character_entity(connection: Connection, f: _Fixture, type_code: str, name: str) -> object:
    return make_character(connection, f.world_id, name=name, entity_type_code=type_code)


def _grant(
    connection: Connection,
    f: _Fixture,
    *,
    capability: str,
    effect: str,
    entity_id: object,
) -> object:
    return create_resource_grant(
        connection,
        campaign_id=f.campaign_id,
        grantee_campaign_membership_id=f.grantee_membership_id,
        grantee_access_group_id=None,
        capability_code=capability,
        effect=effect,
        expected_world_id=f.world_id,
        granted_by_membership_id=f.grantor_membership_id,
        entity_id=entity_id,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("type_code", ["character", "npc", "player_character"])
@pytest.mark.parametrize("capability", ["campaign.view", "canon.edit"])
def test_a_character_entity_accepts_a_campaign_view_or_canon_edit_deny(
    db_connection: Connection, type_code: str, capability: str
) -> None:
    f = _Fixture(
        db_connection, f"cti-deny-{type_code.replace('_', '-')}-{capability.replace('.', '-')}"
    )
    character = _character_entity(db_connection, f, type_code, "Denied Character")
    result = _grant(db_connection, f, capability=capability, effect="deny", entity_id=character)
    row = db_connection.execute(
        text(
            "SELECT entity_id, character_id, timeline_id, effect, revoked_at "
            "FROM security.resource_grants WHERE resource_grant_id = :g"
        ),
        {"g": result.resource_grant_id},  # type: ignore[attr-defined]
    ).one()
    assert row.entity_id == character and row.character_id is None
    assert row.timeline_id is None and row.effect == "deny" and row.revoked_at is None


@pytest.mark.parametrize("type_code", ["character", "npc", "player_character"])
@pytest.mark.parametrize("capability", ["campaign.view", "canon.edit"])
def test_a_character_entity_still_refuses_an_allow(
    db_connection: Connection, type_code: str, capability: str
) -> None:
    f = _Fixture(
        db_connection, f"cti-allow-{type_code.replace('_', '-')}-{capability.replace('.', '-')}"
    )
    character = _character_entity(db_connection, f, type_code, "Allowed Character")
    with pytest.raises(TargetNotInCampaignWorldError):
        _grant(db_connection, f, capability=capability, effect="allow", entity_id=character)
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM security.resource_grants WHERE campaign_id = :c"),
            {"c": f.campaign_id},
        ).scalar_one()
        == 0
    )


def test_a_character_deny_of_a_character_capability_under_entity_id_is_refused(
    db_connection: Connection,
) -> None:
    """The target step passes (a deny); the capability catalog refuses `character.*`."""
    f = _Fixture(db_connection, "cti-deny-character-code")
    character = _character_entity(db_connection, f, "character", "Code Character")
    with pytest.raises(ResourceGrantCapabilityNotGrantableError):
        _grant(
            db_connection, f, capability="character.view_full", effect="deny", entity_id=character
        )


def test_the_other_own_column_kinds_are_still_refused_for_a_deny(db_connection: Connection) -> None:
    f = _Fixture(db_connection, "cti-deny-others")
    world_time_id = make_world_time(db_connection, f.world_id, 0)
    targets = (
        make_quest(db_connection, f.world_id),
        make_event(db_connection, f.world_id, f.timeline_id, world_time_id),
        make_knowledge_item(db_connection, f.world_id),
    )
    for target in targets:
        with pytest.raises(TargetNotInCampaignWorldError, match="own resource-grant target"):
            _grant(db_connection, f, capability="campaign.view", effect="deny", entity_id=target)


def test_an_archived_character_and_a_foreign_world_character_are_refused(
    db_connection: Connection,
) -> None:
    f = _Fixture(db_connection, "cti-deny-scope")
    archived = _character_entity(db_connection, f, "character", "Archived Character")
    db_connection.execute(
        text(
            "UPDATE core.entities SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
            "WHERE entity_id = :e"
        ),
        {"e": archived},
    )
    other_world = make_world(db_connection, slug="cti-deny-scope-other")
    foreign = make_character(db_connection, other_world, name="Foreign Character")
    for target in (archived, foreign):
        with pytest.raises(TargetNotInCampaignWorldError):
            _grant(db_connection, f, capability="campaign.view", effect="deny", entity_id=target)


def test_a_duplicate_character_deny_is_a_unique_violation_until_the_first_is_revoked(
    db_connection: Connection,
) -> None:
    f = _Fixture(db_connection, "cti-deny-duplicate")
    character = _character_entity(db_connection, f, "character", "Duplicate Character")
    first = _grant(db_connection, f, capability="canon.edit", effect="deny", entity_id=character)
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        _grant(db_connection, f, capability="canon.edit", effect="deny", entity_id=character)
    # A different capability on the same character is a different deny.
    _grant(db_connection, f, capability="campaign.view", effect="deny", entity_id=character)
    revoked = revoke_resource_grant(
        db_connection,
        resource_grant_id=first.resource_grant_id,  # type: ignore[attr-defined]
        campaign_id=f.campaign_id,
    )
    assert revoked.revoked is True
    _grant(db_connection, f, capability="canon.edit", effect="deny", entity_id=character)
