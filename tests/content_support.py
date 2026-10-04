"""Shared fixtures for the Phase 15.1 typed content-authoring API tests.

Builds, through the production routes, a GM who owns a world and campaign, a
second member with only the `player` role (so no `canon.edit`), and a stranger
GM with a separate world and campaign (cross-world attacks). Everything runs on
the harness's one rolled-back connection.
"""

import uuid
from typing import Any

from sqlalchemy import Connection, text

from tests.authoring_support import Actor, AuthoringHarness
from tests.builders import dnd5e_ids


def _make_world_and_campaign(
    gm: Actor, name: str, ruleset: tuple[uuid.UUID, uuid.UUID]
) -> tuple[uuid.UUID, str]:
    ruleset_id, ruleset_version_id = ruleset
    created = gm.post(
        "/worlds",
        {
            "name": name,
            "description": None,
            "ruleset_ids": [str(ruleset_id)],
            "default_ruleset_id": str(ruleset_id),
            "primary_timeline": {"name": "Main", "description": None},
        },
        key=gm.fresh_key(),
    ).json()
    campaign = gm.post(
        "/campaigns",
        {
            "timeline_id": created["primary_timeline_id"],
            "ruleset_version_id": str(ruleset_version_id),
            "name": f"{name} Campaign",
            "description": None,
        },
        key=gm.fresh_key(),
    ).json()
    return uuid.UUID(created["world_id"]), campaign["campaign_id"]


def add_member(connection: Connection, campaign_id: str, user_id: uuid.UUID, role: str) -> None:
    connection.execute(
        text("""
            INSERT INTO security.campaign_memberships
                (campaign_id, user_id, membership_status_id, joined_at)
            VALUES (:c, :u, (SELECT membership_status_id FROM security.membership_statuses
                             WHERE code = 'active'), now())
        """),
        {"c": campaign_id, "u": user_id},
    )
    connection.execute(
        text("""
            INSERT INTO security.membership_roles (campaign_membership_id, role_id)
            SELECT cm.campaign_membership_id, r.role_id
            FROM security.campaign_memberships cm, security.roles r
            WHERE cm.campaign_id = :c AND cm.user_id = :u
              AND r.code = :role AND r.campaign_id IS NULL
        """),
        {"c": campaign_id, "u": user_id, "role": role},
    )


class ContentSetup:
    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.harness = harness
        self.connection = connection
        ruleset = dnd5e_ids(connection)
        self.gm: Actor = harness.new_actor("GM")
        self.world_id, self.cid = _make_world_and_campaign(self.gm, "World", ruleset)
        self.player: Actor = harness.new_actor("Player")
        add_member(connection, self.cid, self.player.user_id, "player")
        self.stranger: Actor = harness.new_actor("Stranger GM")
        self.other_world_id, self.other_cid = _make_world_and_campaign(
            self.stranger, "Other World", ruleset
        )

    # --- URLs ------------------------------------------------------------
    def url(self, path: str, cid: str | None = None) -> str:
        return f"/campaigns/{cid or self.cid}/authoring/{path}"

    def lifecycle(self, entity_id: str, suffix: str = "", cid: str | None = None) -> str:
        return f"/campaigns/{cid or self.cid}/entities/{entity_id}/lifecycle{suffix}"

    # --- lifecycle helpers ---------------------------------------------------
    def transition(self, entity_id: str, action: str, version: int, **extra: Any) -> dict:
        response = self.gm.post(
            self.lifecycle(entity_id, f"/{action}"),
            {"expected_row_version": version, **extra},
            key=self.gm.fresh_key(),
        )
        assert response.status_code == 200, response.text
        return response.json()

    def publish(self, entity_id: str, version: int) -> int:
        """draft -> proposed -> approved -> canon; returns the final version."""
        for action in ("submit-for-review", "approve", "publish"):
            version = self.transition(entity_id, action, version)["row_version"]
        return version

    # --- inspection ----------------------------------------------------------
    def audit(self, command: str) -> list:
        return list(
            self.connection.execute(
                text(
                    "SELECT action.code AS action, cl.entity_id, cl.world_id, cl.actor_user_id, "
                    "cl.changed_fields, cl.reason, cl.correlation_id, cl.source_id, cl.command_name "
                    "FROM audit.change_log cl JOIN audit.change_actions action "
                    "ON action.change_action_id = cl.change_action_id "
                    "WHERE cl.command_name = :c ORDER BY cl.change_log_id"
                ),
                {"c": command},
            ).all()
        )

    def count(self, table: str) -> int:
        value = self.connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        assert isinstance(value, int)
        return value

    def quest_stage_count(self) -> int:
        """Quest stages in this setup's world only: the database may hold other
        committed worlds' quests, so a table-wide count is not a stable assertion."""
        value = self.connection.execute(
            text(
                "SELECT count(*) FROM narrative.quest_stages qs "
                "JOIN core.entities e ON e.entity_id = qs.quest_id WHERE e.world_id = :w"
            ),
            {"w": self.world_id},
        ).scalar()
        assert isinstance(value, int)
        return value

    def quest_objective_count(self) -> int:
        value = self.connection.execute(
            text(
                "SELECT count(*) FROM narrative.quest_objectives qo "
                "JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id "
                "JOIN core.entities e ON e.entity_id = qs.quest_id WHERE e.world_id = :w"
            ),
            {"w": self.world_id},
        ).scalar()
        assert isinstance(value, int)
        return value

    def set_status(
        self, entity_id: str, canon: str | None = None, lifecycle: str | None = None
    ) -> None:
        if canon is not None:
            self.connection.execute(
                text(
                    "UPDATE core.entities SET canon_status_id = "
                    "(SELECT canon_status_id FROM core.canon_statuses WHERE code = :c) "
                    "WHERE entity_id = :e"
                ),
                {"c": canon, "e": entity_id},
            )
        if lifecycle is not None:
            self.connection.execute(
                text(
                    "UPDATE core.entities SET lifecycle_status_id = "
                    "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :c) "
                    "WHERE entity_id = :e"
                ),
                {"c": lifecycle, "e": entity_id},
            )
