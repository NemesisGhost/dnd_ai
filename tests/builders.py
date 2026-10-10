"""Command-backed builders for Phase 14 tests.

`tests/factories.py` keeps its raw INSERT factories (390+ call sites, and
constraint tests need raw control). New Phase 14 tests that need an *authored*
world, timeline, or campaign build it through the production commands instead,
so a test exercises the same write path the portal does
(docs/PLAN.md Phase 14, D19).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.commands.campaigns import create_campaign
from dnd_ai.commands.worlds import CreateWorldResult, create_world
from dnd_ai.queries.world_authority import may_create_worlds


@dataclass(frozen=True)
class AuthoredWorld:
    world_id: uuid.UUID
    primary_timeline_id: uuid.UUID
    ruleset_id: uuid.UUID
    ruleset_version_id: uuid.UUID
    owner_user_id: uuid.UUID
    row_version: int


def dnd5e_ids(connection: Connection) -> tuple[uuid.UUID, uuid.UUID]:
    """`(ruleset_id, current ruleset_version_id)` of the seeded dnd5e ruleset."""
    row = connection.execute(
        text("""
            SELECT rs.ruleset_id, rv.ruleset_version_id
            FROM rules.rulesets rs
            JOIN rules.ruleset_versions rv ON rv.ruleset_id = rs.ruleset_id AND rv.is_current
            WHERE rs.code = 'dnd5e'
        """)
    ).one()
    return row.ruleset_id, row.ruleset_version_id


def make_world_creator(connection: Connection, user_id: uuid.UUID) -> uuid.UUID:
    """Make `user_id` a legitimate world creator (docs/adr/0018-world-
    creation-eligibility.md) by giving the account platform administration —
    the creation path with no campaign prerequisite. A no-op for a user who
    already qualifies (an administrator, or an effective built-in `gm`).

    Administration grants no authority over any existing world or campaign, so
    promoting the actor that authors a test world changes nothing else the
    test observes about that actor's world or campaign access. Tests of the
    policy itself build their actors explicitly instead."""
    if not may_create_worlds(connection, user_id=user_id):
        connection.execute(
            text("UPDATE security.users SET is_platform_administrator = true WHERE user_id = :u"),
            {"u": user_id},
        )
    return user_id


def make_authored_world(
    connection: Connection,
    *,
    owner_user_id: uuid.UUID,
    name: str = "Authored World",
    timeline_name: str = "Primary Timeline",
) -> AuthoredWorld:
    """A world created through `create_world` (owner membership, allow-list,
    and primary timeline included) using the seeded dnd5e ruleset. The owner
    is first made a legitimate world creator (`make_world_creator`)."""
    make_world_creator(connection, owner_user_id)
    ruleset_id, ruleset_version_id = dnd5e_ids(connection)
    result: CreateWorldResult = create_world(
        connection,
        creator_user_id=owner_user_id,
        name=name,
        description=None,
        ruleset_ids=[ruleset_id],
        default_ruleset_id=ruleset_id,
        primary_timeline_name=timeline_name,
    )
    return AuthoredWorld(
        world_id=result.world_id,
        primary_timeline_id=result.primary_timeline_id,
        ruleset_id=ruleset_id,
        ruleset_version_id=ruleset_version_id,
        owner_user_id=owner_user_id,
        row_version=result.row_version,
    )


def make_authored_campaign(
    connection: Connection,
    world: AuthoredWorld,
    *,
    creator_user_id: uuid.UUID | None = None,
    timeline_id: uuid.UUID | None = None,
    name: str = "Authored Campaign",
) -> uuid.UUID:
    """A campaign created through `create_campaign` on the world's primary
    timeline (or `timeline_id`), authorized by world ownership."""
    result = create_campaign(
        connection,
        timeline_id=timeline_id or world.primary_timeline_id,
        ruleset_version_id=world.ruleset_version_id,
        name=name,
        creator_user_id=creator_user_id or world.owner_user_id,
    )
    return result.campaign_id
