"""Atomic authenticated-user auditing for command endpoints
(docs/architecture/DATABASE_MODEL.md §19.1's `audit.change_log`, already
delivered by revision 007 — this module is the first API-layer writer for
it, first used by `dnd_ai.api.items`).

`record_change_log()` inserts exactly one `audit.change_log` row, on the
caller's own connection, so it commits atomically with the command and
event it describes — never a separate post-commit write, which could
observe a committed state change with no corresponding audit row if the
process died in between.

`actor_user_id` always comes from the resolved, authenticated
`dnd_ai.domain.access.AccessContext.user_id` — never a command's own
`actor_entity_id` argument. The two are unrelated: `actor_entity_id` (see
`dnd_ai.commands.items`/`.encounters`) is an in-world entity a narrative
event attributes an action to, may be absent even when a real person
issued the HTTP request (an unattended/administrative transfer), and may
be present even when no single authenticated user maps to it cleanly (a
service account, a future unattended automation). Conflating the two would
let an API caller attribute a change to an arbitrary in-world entity in
the audit trail instead of the credential that actually authorized it.

`command_name` and `change_action_code` are always literal strings a call
site supplies — never derived from request data — matching every other
lookup-code usage in this codebase (`dnd_ai.commands._shared.lookup_id`).
Nothing here logs or stores unrestricted request text: the columns this
module writes are `command_name` (a fixed literal), the affected record's
own IDs, the resolved `event_id`, and `correlation_id` (already validated
to a canonical UUID shape by `dnd_ai.api.correlation` before it ever
reaches a route handler)."""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.commands._shared import lookup_id


def record_change_log(
    connection: Connection,
    *,
    change_action_code: str,
    schema_name: str,
    table_name: str,
    record_id: uuid.UUID | None,
    entity_id: uuid.UUID | None,
    world_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
    command_name: str,
    event_id: uuid.UUID | None,
) -> None:
    """Insert one `audit.change_log` row. Call once, after the command's
    own writes and before the route returns, on the same connection/
    transaction the command ran on."""
    change_action_id = lookup_id(
        connection, "audit", "change_actions", "change_action_id", change_action_code
    )
    connection.execute(
        text("""
            INSERT INTO audit.change_log
                (change_action_id, schema_name, table_name, record_id, entity_id, world_id,
                 actor_user_id, correlation_id, command_name, event_id)
            VALUES
                (:action, :schema, :table, :record, :entity, :world,
                 :actor, :correlation, :command, :event)
        """),
        {
            "action": change_action_id,
            "schema": schema_name,
            "table": table_name,
            "record": record_id,
            "entity": entity_id,
            "world": world_id,
            "actor": actor_user_id,
            "correlation": uuid.UUID(correlation_id) if correlation_id is not None else None,
            "command": command_name,
            "event": event_id,
        },
    )
