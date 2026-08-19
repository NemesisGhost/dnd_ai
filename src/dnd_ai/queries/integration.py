"""Read path over `integration.sync_state` — Phase 11 workstream 4,
"restore synchronized state after reopening or reconnecting."

`integration.sync_state` (migration 079) is written only by
`dnd_ai.commands.integration._complete_sync_job`'s atomic upsert; nothing
in this codebase read it back until this module. It is deliberately a
thin, adapter-facing *sync-bookkeeping* view — "was this target ever
synced, and did the last attempt succeed" — never a second copy of the
domain state itself: the actual current HP/encounter/etc. state a
reconnecting Foundry adapter needs is already retrievable through the
ordinary, already-Foundry-reachable domain endpoints (`dnd_ai.api.
encounters.get_encounter_endpoint`, `dnd_ai.queries.character`, ...) per
Phase 11 workstream 2's authentication work — duplicating that data here
would violate CLAUDE.md rule 1 (PostgreSQL's own domain tables are the
only source of truth) by creating a second place the same fact could
drift out of sync with the first.

No row for a given `(external_system_id, target)` means "never
successfully synced" — `_complete_sync_job` only ever inserts on a
*successful* completion (a failed or in-progress `sync_jobs` row leaves no
`sync_state` row at all), so there is no "unsynced" row to read; absence
itself carries that meaning. `get_sync_state_view` returns `None` for this
case, and `sync_state_endpoint` (`dnd_ai.api.integration`) maps that to a
404 — consistent with every other "doesn't exist" case in this codebase,
even though "genuinely never synced" is a legitimate state rather than a
caller error; there is no established convention here for a distinct
"200 with an empty body" shape, and inventing one for this single case
would be exactly the kind of un-asked-for special-casing this codebase
avoids.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text


class InvalidSyncStateTargetError(ValueError):
    """Raised by `get_sync_state_view()` when the caller supplies both or
    neither of `target_entity_id`/`target_encounter_id` — mirroring
    `integration.sync_state`'s own `ck_sync_state_exactly_one_target`
    CHECK constraint (migration 079) as an early, clearer validation
    failure rather than a query that could only ever match zero rows."""


@dataclass(frozen=True)
class SyncStateView:
    sync_state_id: uuid.UUID
    external_system_id: uuid.UUID
    target_entity_id: uuid.UUID | None
    target_encounter_id: uuid.UUID | None
    sync_status: str
    last_synced_at: datetime | None
    last_sync_job_id: uuid.UUID | None
    last_sync_job_status: str | None
    last_sync_job_error_message: str | None


def get_sync_state_view(
    connection: Connection,
    *,
    external_system_id: uuid.UUID,
    target_entity_id: uuid.UUID | None = None,
    target_encounter_id: uuid.UUID | None = None,
) -> SyncStateView | None:
    """The last known sync outcome for one `(external_system_id, target)`
    pair, or `None` if that target has never been successfully synced (see
    this module's own docstring). Exactly one of `target_entity_id`/
    `target_encounter_id` must be supplied — `InvalidSyncStateTargetError`
    otherwise, mirroring `ck_sync_state_exactly_one_target`.

    Caller-side authorization (confirming `external_system_id`/the named
    target actually belong to the authenticated caller's own campaign) is
    the API layer's job, exactly like every other cross-world/cross-
    campaign check in this codebase (`dnd_ai.api.integration.
    sync_state_endpoint`) — this function trusts its arguments the same
    way `dnd_ai.queries.encounter.get_encounter_view` trusts its own
    `campaign_id`."""
    if (target_entity_id is None) == (target_encounter_id is None):
        raise InvalidSyncStateTargetError(
            "exactly one of target_entity_id/target_encounter_id must be supplied "
            f"(entity={target_entity_id!r}, encounter={target_encounter_id!r})"
        )

    row = (
        connection.execute(
            text("""
                SELECT ss.sync_state_id, ss.external_system_id, ss.target_entity_id,
                       ss.target_encounter_id, ss.sync_status, ss.last_synced_at,
                       ss.last_sync_job_id, sj.status AS last_sync_job_status,
                       sj.error_message AS last_sync_job_error_message
                FROM integration.sync_state ss
                LEFT JOIN integration.sync_jobs sj ON sj.sync_job_id = ss.last_sync_job_id
                WHERE ss.external_system_id = :system
                  AND ss.target_entity_id IS NOT DISTINCT FROM :entity
                  AND ss.target_encounter_id IS NOT DISTINCT FROM :encounter
            """),
            {
                "system": external_system_id,
                "entity": target_entity_id,
                "encounter": target_encounter_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None

    return SyncStateView(
        sync_state_id=row["sync_state_id"],
        external_system_id=row["external_system_id"],
        target_entity_id=row["target_entity_id"],
        target_encounter_id=row["target_encounter_id"],
        sync_status=row["sync_status"],
        last_synced_at=row["last_synced_at"],
        last_sync_job_id=row["last_sync_job_id"],
        last_sync_job_status=row["last_sync_job_status"],
        last_sync_job_error_message=row["last_sync_job_error_message"],
    )
