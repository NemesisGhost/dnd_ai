"""Create the persistent portal-development campaign.

This is trusted development authoring infrastructure, not production seed data.
It deliberately reuses the repository's raw authoring factories because the API
does not yet expose world/timeline/character authoring commands. Dynamic access
state is created through the command layer.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import Connection, create_engine, text
from tests.factories import (
    make_character,
    make_external_identity,
    make_knowledge_item,
    make_party,
    make_party_membership,
    make_quest,
    make_quest_objective,
    make_quest_stage,
    make_ruleset_version_for_world,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

from dnd_ai.commands.access_grants import grant_character_relationship
from dnd_ai.commands.campaigns import create_campaign, grant_timeline_bootstrap
from dnd_ai.commands.memberships import assign_membership_role, create_campaign_membership

DEMO_SLUG = "portal-demo"
DEMO_ISSUER = "https://portal-dev.invalid"


def _uuid(value: Any) -> uuid.UUID:
    assert isinstance(value, uuid.UUID)
    return value


def _existing_manifest(connection: Connection) -> dict[str, Any] | None:
    row = (
        connection.execute(
            text("""
                SELECT w.world_id, t.timeline_id, c.campaign_id, c.name
                FROM core.worlds w
                JOIN campaign.timelines t ON t.world_id = w.world_id AND t.is_primary
                JOIN campaign.campaigns c ON c.timeline_id = t.timeline_id
                WHERE w.slug = :slug
                ORDER BY c.started_at
                LIMIT 1
            """),
            {"slug": DEMO_SLUG},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    users = connection.execute(
        text("""
            SELECT u.display_name, ei.subject
            FROM security.users u
            JOIN security.external_identities ei ON ei.user_id = u.user_id
            WHERE ei.issuer = :issuer AND ei.subject LIKE 'portal-demo-%'
            ORDER BY ei.subject
        """),
        {"issuer": DEMO_ISSUER},
    ).mappings()
    return {
        "created": False,
        "world_id": str(row["world_id"]),
        "timeline_id": str(row["timeline_id"]),
        "campaign_id": str(row["campaign_id"]),
        "campaign_name": row["name"],
        "identities": [dict(user) for user in users],
    }


def _role_id(connection: Connection, code: str) -> uuid.UUID:
    return _uuid(
        connection.execute(
            text("SELECT role_id FROM security.roles WHERE campaign_id IS NULL AND code = :code"),
            {"code": code},
        ).scalar_one()
    )


def create_demo(connection: Connection) -> dict[str, Any]:
    existing = _existing_manifest(connection)
    if existing is not None:
        return existing

    world_id = make_world(connection, slug=DEMO_SLUG)
    connection.execute(
        text("UPDATE core.worlds SET name = 'The Lantern Coast' WHERE world_id = :world"),
        {"world": world_id},
    )
    timeline_id = make_timeline(connection, world_id, is_primary=True)
    ruleset_version_id = make_ruleset_version_for_world(connection, world_id)
    before = make_world_time(connection, world_id, 10)
    current = make_world_time(connection, world_id, 20)

    aria_id = make_character(connection, world_id, name="Aria Vale")
    borin_id = make_character(connection, world_id, name="Borin Stonehand")
    caretaker_id = make_character(connection, world_id, name="Old Caretaker")
    party_id = make_party(connection, world_id)
    make_party_membership(connection, timeline_id, party_id, aria_id, before)
    make_party_membership(connection, timeline_id, party_id, borin_id, before)

    quest_id = make_quest(connection, world_id, name="The Lamps Beneath the Keep")
    quest_stage_id = make_quest_stage(connection, quest_id)
    make_quest_objective(connection, quest_stage_id, name="Find the sealed stair")
    make_knowledge_item(
        connection,
        world_id,
        statement="The caretaker knows why the lower beacon went dark.",
        subject_entity_id=caretaker_id,
    )

    user_specs = (
        ("gm", "Demo Game Master"),
        ("assistant-gm", "Demo Assistant GM"),
        ("player-one", "Demo Player One"),
        ("player-two", "Demo Player Two"),
        ("observer", "Demo Observer"),
    )
    users: dict[str, uuid.UUID] = {}
    for subject_suffix, display_name in user_specs:
        user_id = make_user(connection, display_name)
        make_external_identity(
            connection,
            user_id,
            issuer=DEMO_ISSUER,
            subject=f"portal-demo-{subject_suffix}",
        )
        users[subject_suffix] = user_id

    grant_timeline_bootstrap(
        connection, timeline_id=timeline_id, granted_to_user_id=users["gm"]
    )
    campaign = create_campaign(
        connection,
        timeline_id=timeline_id,
        ruleset_version_id=ruleset_version_id,
        name="The Sunken Keep",
        description="A persistent demonstration campaign for portal development.",
        creator_user_id=users["gm"],
    )
    connection.execute(
        text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
        {"c": campaign.campaign_id, "p": party_id},
    )

    memberships: dict[str, uuid.UUID] = {"gm": campaign.campaign_membership_id}
    role_codes = {
        "assistant-gm": "assistant_gm",
        "player-one": "player",
        "player-two": "player",
        "observer": "observer",
    }
    for subject_suffix, role_code in role_codes.items():
        membership = create_campaign_membership(
            connection, campaign_id=campaign.campaign_id, user_id=users[subject_suffix]
        )
        memberships[subject_suffix] = membership.campaign_membership_id
        assign_membership_role(
            connection,
            campaign_membership_id=membership.campaign_membership_id,
            role_id=_role_id(connection, role_code),
            campaign_id=campaign.campaign_id,
            granted_by_membership_id=campaign.campaign_membership_id,
        )

    for subject_suffix, character_id, relationship in (
        ("player-one", aria_id, "primary_controller"),
        ("player-two", aria_id, "co_controller"),
        ("player-two", borin_id, "primary_controller"),
    ):
        grant_character_relationship(
            connection,
            campaign_membership_id=memberships[subject_suffix],
            character_id=character_id,
            relationship_type_code=relationship,
            campaign_id=campaign.campaign_id,
            expected_world_id=world_id,
            granted_by_membership_id=campaign.campaign_membership_id,
        )

    first_session_start = datetime.now(UTC) - timedelta(days=14, hours=4)
    make_session(
        connection,
        campaign.campaign_id,
        session_number=1,
        lifecycle_status_code="completed",
        title="The Drowned Gate",
        summary="The party reached the keep and learned that its beacon failed from below.",
        started_at=first_session_start,
        ended_at=first_session_start + timedelta(hours=4),
    )
    make_session(
        connection,
        campaign.campaign_id,
        session_number=2,
        lifecycle_status_code="active",
        title="Lamps in the Deep",
        started_at=datetime.now(UTC),
    )

    return {
        "created": True,
        "world_id": str(world_id),
        "timeline_id": str(timeline_id),
        "campaign_id": str(campaign.campaign_id),
        "campaign_name": "The Sunken Keep",
        "current_world_time_id": str(current),
        "characters": {"aria": str(aria_id), "borin": str(borin_id)},
        "identities": [
            {"display_name": display_name, "subject": f"portal-demo-{subject_suffix}"}
            for subject_suffix, display_name in user_specs
        ],
    }


def main() -> None:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required; migrate the database before creating demo data.")
    engine = create_engine(database_url, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as connection:
            manifest = create_demo(connection)
    finally:
        engine.dispose()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
