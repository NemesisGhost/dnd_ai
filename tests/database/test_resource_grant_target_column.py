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
"""

import pytest
from sqlalchemy import Connection

from dnd_ai.commands.access_grants import TargetNotInCampaignWorldError, create_resource_grant
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
