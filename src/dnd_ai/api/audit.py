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
reaches a route handler).

`acting_external_system_id` (Phase 11 workstream 2 correction, migration
091): pass `access.principal.foundry_external_system_id` from an
`AccessContext` `dnd_ai.api.access.require_campaign_capability` resolved
— `None` for every OIDC-authenticated call (the default, and every call
site before this parameter existed), the authenticating `integration.
external_systems` row for a call made through a delegated `FoundrySystem`
credential. `actor_user_id` is unaffected either way — this parameter
records *which integration vouched for the request*, not who it is
attributed to; conventions §24.3 requires audit records to identify
"user, service, AI agent, integration ... where applicable," which for an
adapter-delegated change means recording both, never one instead of the
other (contrast `actor_service`, documented as set *instead of*
`actor_user_id` for an actor with no linked user at all).

`acting_foundry_actor_id` (second Phase 11 workstream 2 correction,
migration 092): pass `access.principal.foundry_claimed_actor_id` alongside
`acting_external_system_id` for the same delegated-credential calls.
Deliberately *not* used to decide `actor_user_id` — that is, and remains,
resolved entirely from the credential's own bound `system_key_principal_
user_id` (`dnd_ai.domain.access.resolve_foundry_system_principal`) — this
column exists only so an operator reviewing audit history can see what the
Foundry client *claimed* about who triggered the action, clearly
distinguished from who the platform actually authenticated. See `dnd_ai.
domain.access.AuthenticatedPrincipal.foundry_claimed_actor_id`'s own
docstring for why this is untrusted metadata, never an authorization
input.

`acting_foundry_connection_id`/`acting_foundry_device_id` (Phase 11R
workstream G, migration 101): pass `access.principal.
foundry_connection_id`/`.foundry_device_id` for a call authenticated via
the paired `FoundryAccess` credential — `None` for every other auth
method, including the legacy `FoundrySystem` one, which has no connection/
device of its own. `acting_external_system_id` is still populated for
this credential type too (`AuthenticatedPrincipal.
foundry_external_system_id` is set for both Foundry auth methods since
workstream C); these two columns add the finer-grained "which paired
connection, which specific device" identity the legacy credential could
never carry. No `acting_foundry_actor_id` equivalent exists for this
credential type — see that column's own comment (`src/dnd_ai/persistence/
tables/audit.py`) for why."""

import json
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
    actor_user_id: uuid.UUID | None = None,
    actor_service: str | None = None,
    correlation_id: str | None,
    command_name: str,
    event_id: uuid.UUID | None,
    previous_status: str | None = None,
    new_status: str | None = None,
    changed_fields: dict[str, object] | None = None,
    acting_external_system_id: uuid.UUID | None = None,
    acting_foundry_actor_id: str | None = None,
    acting_foundry_connection_id: uuid.UUID | None = None,
    acting_foundry_device_id: uuid.UUID | None = None,
    ai_proposal_id: uuid.UUID | None = None,
) -> None:
    """Insert one `audit.change_log` row. Call once, after the command's
    own writes and before the route returns, on the same connection/
    transaction the command ran on.

    `ai_proposal_id` (Phase 12) is the `ai.proposed_changes.
    ai_proposed_change_id` an applied change resulted from — set only by
    `dnd_ai.api.ai_npc`/`.ai_proposals` for a route that actually applied
    an AI proposal, `None` for every other (human-authored) call site.
    `audit.change_log.ai_proposal_id` has carried no foreign key since its
    original migration ("the things these point at may not exist yet, or
    ever" — revision 007); it is not added retroactively here either,
    matching that same reasoning now that a real target table exists but
    this column's own contract was always informational, not referential
    integrity.

    `actor_user_id`/`actor_service` (Phase 13B blocker 3): exactly one is
    required — mirroring `audit.change_log`'s own `ck_change_log_actor_
    present` CHECK constraint, enforced here too so a caller gets an
    immediate, specific `ValueError` rather than an opaque database
    constraint violation. `actor_service` is for an actor with no linked
    `security.users` row at all (the identical "actor is a service,
    integration, or AI agent rather than a person" case that column's own
    migration comment already documents) — `dnd_ai.api.local_auth`'s
    failed-login audit write is this module's first caller with no
    authenticated `user_id` to attribute the attempt to (an unknown login
    name resolves to no user at all); every other call site in this
    codebase still passes `actor_user_id` exactly as before.

    `previous_status`/`new_status` and `changed_fields` (Phase 13B blocker
    3): the first two are `audit.change_log`'s own pre-existing lifecycle-
    transition columns (revision 007, "previous_status/new_status ... when
    the change was one") — present in the schema since this table's
    original migration but never previously wired through this writer
    function, since no prior caller recorded a lifecycle transition.
    `dnd_ai.commands.local_auth`'s administrative account disable/
    reactivate commands are the first to (`core.lifecycle_statuses.code`
    values — `'active'`/`'inactive'` — never a raw column value or
    anything else caller-supplied). `changed_fields` is that same
    pre-existing JSONB column, serialized with `json.dumps` exactly like
    every other JSONB write in this codebase (e.g. `dnd_ai.commands.
    character_state`) — used here only for small, bounded, non-secret
    context (e.g. `{"revoked_session_count": 3}` for an administrator's
    revoke-all action), never request bodies or anything from the
    forbidden-content list this module's own docstring's "Never store"
    section (in `dnd_ai.api.local_auth`) enumerates."""
    if actor_user_id is None and actor_service is None:
        raise ValueError("record_change_log requires actor_user_id or actor_service")
    change_action_id = lookup_id(
        connection, "audit", "change_actions", "change_action_id", change_action_code
    )
    connection.execute(
        text("""
            INSERT INTO audit.change_log
                (change_action_id, schema_name, table_name, record_id, entity_id, world_id,
                 actor_user_id, actor_service, correlation_id, command_name, event_id,
                 previous_status, new_status, changed_fields,
                 acting_external_system_id, acting_foundry_actor_id,
                 acting_foundry_connection_id, acting_foundry_device_id, ai_proposal_id)
            VALUES
                (:action, :schema, :table, :record, :entity, :world,
                 :actor, :actor_service, :correlation, :command, :event,
                 :previous_status, :new_status, :changed_fields, :acting_external_system,
                 :acting_foundry_actor, :acting_foundry_connection, :acting_foundry_device,
                 :ai_proposal)
        """),
        {
            "action": change_action_id,
            "schema": schema_name,
            "table": table_name,
            "record": record_id,
            "entity": entity_id,
            "world": world_id,
            "actor": actor_user_id,
            "actor_service": actor_service,
            "correlation": uuid.UUID(correlation_id) if correlation_id is not None else None,
            "command": command_name,
            "event": event_id,
            "previous_status": previous_status,
            "new_status": new_status,
            "changed_fields": json.dumps(changed_fields) if changed_fields is not None else None,
            "acting_external_system": acting_external_system_id,
            "acting_foundry_actor": acting_foundry_actor_id,
            "acting_foundry_connection": acting_foundry_connection_id,
            "acting_foundry_device": acting_foundry_device_id,
            "ai_proposal": ai_proposal_id,
        },
    )
