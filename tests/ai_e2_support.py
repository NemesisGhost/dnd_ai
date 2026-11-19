"""R01 E2: shared test support for the two AI provider commands.

`request_npc_conversation_turn` and `request_campaign_synthesis` now run two `authorized_transaction`s on the
engine and judge each with a fresh requirement factory. A direct caller therefore needs a real actor: a
campaign member whose role gives `character.interact` (the NPC turn), `canon.edit` (a `gm_brief`) or
`campaign.view`, and `character.view_knowledge` for the character (the established party perspective, decision
G-2: no `canon.edit` bypass). `make_interactor` builds that member from a campaign-scoped role, so no seed and no
policy changes; `npc_turn` and `synthesis` call the commands with the same requirement builders the routes use.
"""

import uuid
from typing import Any

from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.ai_npc import NpcConversationTurnResult, request_npc_conversation_turn
from dnd_ai.commands.ai_synthesis import CampaignSynthesisResult, request_campaign_synthesis
from tests.factories import (
    lookup_id,
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_user,
)

DEFAULT_CAPABILITIES = (
    "campaign.view",
    "character.interact",
    "character.view_knowledge",
    "canon.edit",
)


def make_interactor(
    connection: Connection,
    campaign_id: uuid.UUID,
    name: str = "Interactor",
    *,
    capabilities: tuple[str, ...] = DEFAULT_CAPABILITIES,
) -> uuid.UUID:
    """A campaign member holding exactly `capabilities` through one campaign-scoped role."""
    user_id = make_user(connection, name)
    membership_id = make_campaign_membership(connection, campaign_id, user_id)
    role_id = make_role(connection, campaign_id=campaign_id, code=f"e2_{uuid.uuid4().hex[:10]}")
    for code in capabilities:
        make_role_capability(
            connection,
            role_id,
            lookup_id(connection, "security", "capabilities", "capability_id", code),
        )
    make_membership_role(connection, membership_id, role_id)
    return user_id


def delete_campaign_security_rows(connection: Connection, campaign_id: uuid.UUID) -> None:
    """Tear down the members, roles and users of a committed fixture campaign (run under
    `session_replication_role = replica`, like `cleanup_committed_ai_world`)."""
    users = [
        row[0]
        for row in connection.execute(
            text("SELECT user_id FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": campaign_id},
        )
    ]
    connection.execute(
        text("""
            DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                SELECT campaign_membership_id FROM security.campaign_memberships
                WHERE campaign_id = :c
            )
        """),
        {"c": campaign_id},
    )
    connection.execute(
        text("""
            DELETE FROM security.membership_character_relationships WHERE campaign_membership_id IN (
                SELECT campaign_membership_id FROM security.campaign_memberships
                WHERE campaign_id = :c
            )
        """),
        {"c": campaign_id},
    )
    connection.execute(
        text("""
            DELETE FROM security.role_capabilities WHERE role_id IN (
                SELECT role_id FROM security.roles WHERE campaign_id = :c
            )
        """),
        {"c": campaign_id},
    )
    connection.execute(
        text("DELETE FROM security.roles WHERE campaign_id = :c"), {"c": campaign_id}
    )
    connection.execute(
        text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"), {"c": campaign_id}
    )
    if users:
        connection.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"), {"users": users}
        )


def npc_turn(engine: Engine, *, user_id: uuid.UUID, **kwargs: Any) -> NpcConversationTurnResult:
    """`request_npc_conversation_turn` as the route calls it: the same requirement builder, a real actor."""
    from dnd_ai.api.ai_npc import (
        npc_turn_requirements,
    )  # lazy: the fail-before run uses the parent's source

    return request_npc_conversation_turn(
        engine,
        requesting_user_id=user_id,
        requirements=npc_turn_requirements(
            actor_user_id=user_id, character_id=kwargs["requesting_character_id"]
        ),
        **kwargs,
    )


def synthesis(engine: Engine, *, user_id: uuid.UUID, **kwargs: Any) -> CampaignSynthesisResult:
    """`request_campaign_synthesis` as the route calls it: the same requirement builder, a real actor."""
    from dnd_ai.api.ai_synthesis import synthesis_requirements  # lazy, as above

    return request_campaign_synthesis(
        engine,
        requesting_user_id=user_id,
        requirements=synthesis_requirements(
            actor_user_id=user_id, audience_tier=kwargs["audience_tier"]
        ),
        **kwargs,
    )
