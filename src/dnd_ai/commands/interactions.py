"""PerformInteraction and ResolveCheck.

PerformInteraction records a structured attempt by an actor — an
interaction, its one action, the action's targets, and any checks the
action requires. ResolveCheck records the outcome of one of those checks
and, when the result is narratively significant (docs/DATABASE_CONVENTIONS.md
§14.5 — here, a successful check that satisfies a conditional route's
requirement), reacts atomically: a narrative.events row is recorded and the
route's typed current state (campaign.area_connection_state) is updated in
the same transaction, per CLAUDE.md rule 6.

Scope: each interaction created by perform_interaction has exactly one
action. interaction.actions supports several ordered actions per
interaction (docs/architecture/DATABASE_MODEL.md §16), but nothing in this
phase's exit criteria needs more than one — a multi-action command can be
added if a caller needs it rather than built ahead of that need.

Both commands are split into a connection-taking `_..._impl` plus a thin
engine-based public wrapper — the same composition
`dnd_ai.commands.encounters`/`.items`/`.quests`/`.relationships` use — so
Phase 10's API layer (`dnd_ai.api.interactions`) can run either on the
request's own transaction instead of opening a second, nested one.
`_perform_interaction_impl` validates a caller-supplied `session_id`
against `campaign_id` (`dnd_ai.commands._shared.validate_session_campaign`)
before writing anything, the same guard every other command in this
package applies. `_resolve_check_impl` has no caller-supplied `campaign_id`
of its own to validate a `session_id` against — the interaction it
resolves against already carries its own authoritative `campaign_id` — so
it instead accepts an optional `expected_campaign_id` an API caller passes
to assert that authoritative value matches the campaign named in the
request, via `_lock_interaction_for_check_resolution` below.

`_resolve_check_impl` reacts to four kinds of narratively significant
check outcomes today, each independently gated on which single target
column the check's own target row carries (docs/PLAN.md §25 steps 8-11):

- `target_area_connection_id` + the connection's own conditional-route
  requirement satisfied → open the route (`_open_area_connection`,
  unchanged from Phase 6).
- `target_area_hazard_id` + `interaction_type_code` of `disarm_trap`/
  `trigger_trap` → `campaign.hazard_state` transitions to `disarmed`/
  `triggered` per `_hazard_outcome_status()`'s own mapping.
- `target_area_interactable_id` + `interaction_type_code` of
  `activate_mechanism`, on success → `campaign.interactable_state`
  transitions to `activated`.
- Any of the four hidden-eligible target kinds (`target_area_connection_id`/
  `target_area_feature_id`/`target_area_hazard_id`/
  `target_area_interactable_id`), when `is_hidden` and a caller-supplied
  `party_id` has not yet discovered it via a matching `knowledge.
  knowledge_items` row — the write-side counterpart to `dnd_ai.queries.
  dungeon`'s own read-side discovery filtering (see `_maybe_discover_
  target()`'s own docstring).

The first three are mutually exclusive by construction (`interaction.
targets`' own "at most one target column set" shape), but discovery is
independent and can co-occur with any of them — a single successful check
can both reveal a hazard's existence and disarm it in the same action.
Every reaction that fires gets its own `narrative.events` row and
`interaction.consequences` row; `interaction.interactions.resulting_
event_id` is set to the mechanically primary one (connection/hazard/
interactable) when one occurred, falling back to the discovery event
otherwise — see `_resolve_interaction()`'s own docstring.
"""

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

from ._shared import lookup_id, validate_session_campaign
from .events import EventParticipant, _insert_event_row


class InteractionNotFoundError(DomainAuthorizationError):
    """Raised by `_lock_interaction_for_check_resolution()` when the
    `check_request_id` it was given does not resolve to an existing
    `interaction.check_requests` row, or — when `expected_campaign_id` was
    supplied — resolves to one whose parent interaction belongs to a
    different campaign than expected. Both cases raise this identical
    error, mirroring `dnd_ai.commands.encounters.EncounterNotFoundError`:
    confirming that an interaction exists but belongs to a different
    campaign would itself disclose cross-campaign information to a caller
    only authorized for the campaign it expected."""


class InteractionNotOpenError(SafeMessageError):
    """Raised by `_lock_interaction_for_check_resolution()` when the
    interaction it just locked has already reached a terminal status
    (resolved/failed/cancelled) — the request was well-formed, but the
    interaction's own state has since moved on (already fully resolved, or
    administratively cancelled), so this maps to HTTP 409, not 400. A
    `ValueError` subclass (via `SafeMessageError`), so existing callers
    matching on `ValueError` with "terminal" in the message continue to
    work unchanged; `safe_message` itself stays fixed and generic."""

    safe_status_code = 409
    safe_error_code = "conflict"
    safe_message = "The interaction is not open for further check resolution."


@dataclass(frozen=True)
class TargetSpec:
    target_entity_id: uuid.UUID | None = None
    target_area_connection_id: uuid.UUID | None = None
    target_area_feature_id: uuid.UUID | None = None
    target_area_hazard_id: uuid.UUID | None = None
    target_area_interactable_id: uuid.UUID | None = None
    target_component: str | None = None
    target_description: str | None = None


@dataclass(frozen=True)
class CheckRequestSpec:
    """target_index indexes the same call's targets list, resolved to that
    target's target_id once it exists. None when the check is about the
    action in the abstract rather than one specific target."""

    check_kind: str
    difficulty: int
    ability_id: uuid.UUID | None = None
    skill_id: uuid.UUID | None = None
    advantage_state: str = "normal"
    stakes: str | None = None
    target_index: int | None = None


@dataclass(frozen=True)
class PerformInteractionResult:
    interaction_id: uuid.UUID
    action_id: uuid.UUID
    world_id: uuid.UUID
    target_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    check_request_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)


def _perform_interaction_impl(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    actor_entity_id: uuid.UUID,
    interaction_type_code: str = "other",
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    action_description: str | None = None,
    targets: tuple[TargetSpec, ...] = (),
    check_requests: tuple[CheckRequestSpec, ...] = (),
) -> PerformInteractionResult:
    """The actual work of perform_interaction(), on a connection the caller
    already has open — see dnd_ai.commands.encounters._resolve_combat_turn_
    impl's docstring for the composable-implementation/public-wrapper
    pattern this mirrors. A caller that owns the surrounding transaction
    itself (e.g. the API layer's per-request connection) calls this
    directly.

    Validates session_id/campaign_id agreement (validate_session_campaign)
    before inserting anything — see that function's own docstring."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": timeline_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)

    interaction_id = connection.execute(
        text("""
            INSERT INTO interaction.interactions
                (timeline_id, campaign_id, session_id, interaction_type_id, world_time_id)
            VALUES (
                :timeline, :campaign, :session,
                (SELECT interaction_type_id FROM interaction.interaction_types WHERE code = :itc),
                :world_time
            )
            RETURNING interaction_id
        """),
        {
            "timeline": timeline_id,
            "campaign": campaign_id,
            "session": session_id,
            "itc": interaction_type_code,
            "world_time": world_time_id,
        },
    ).scalar()
    assert isinstance(interaction_id, uuid.UUID)

    action_id = connection.execute(
        text("""
            INSERT INTO interaction.actions (interaction_id, actor_entity_id, description)
            VALUES (:interaction, :actor, :description)
            RETURNING action_id
        """),
        {
            "interaction": interaction_id,
            "actor": actor_entity_id,
            "description": action_description,
        },
    ).scalar()
    assert isinstance(action_id, uuid.UUID)

    target_ids: list[uuid.UUID] = []
    for target in targets:
        target_id = connection.execute(
            text("""
                INSERT INTO interaction.targets
                    (action_id, target_entity_id, target_area_connection_id,
                     target_area_feature_id, target_area_hazard_id,
                     target_area_interactable_id, target_component, target_description)
                VALUES (:action, :entity, :conn, :feature, :hazard, :interactable, :component,
                        :description)
                RETURNING target_id
            """),
            {
                "action": action_id,
                "entity": target.target_entity_id,
                "conn": target.target_area_connection_id,
                "feature": target.target_area_feature_id,
                "hazard": target.target_area_hazard_id,
                "interactable": target.target_area_interactable_id,
                "component": target.target_component,
                "description": target.target_description,
            },
        ).scalar()
        assert isinstance(target_id, uuid.UUID)
        target_ids.append(target_id)

    check_request_ids: list[uuid.UUID] = []
    for check_request in check_requests:
        resolved_target_id = (
            target_ids[check_request.target_index]
            if check_request.target_index is not None
            else None
        )
        check_request_id = connection.execute(
            text("""
                INSERT INTO interaction.check_requests
                    (action_id, actor_entity_id, check_kind, ability_id, skill_id, difficulty,
                     advantage_state, stakes, target_id)
                VALUES (:action, :actor, :kind, :ability, :skill, :difficulty, :advantage,
                        :stakes, :target)
                RETURNING check_request_id
            """),
            {
                "action": action_id,
                "actor": actor_entity_id,
                "kind": check_request.check_kind,
                "ability": check_request.ability_id,
                "skill": check_request.skill_id,
                "difficulty": check_request.difficulty,
                "advantage": check_request.advantage_state,
                "stakes": check_request.stakes,
                "target": resolved_target_id,
            },
        ).scalar()
        assert isinstance(check_request_id, uuid.UUID)
        check_request_ids.append(check_request_id)

    return PerformInteractionResult(
        interaction_id=interaction_id,
        action_id=action_id,
        world_id=world_id,
        target_ids=tuple(target_ids),
        check_request_ids=tuple(check_request_ids),
    )


def perform_interaction(
    engine: Engine,
    *,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    actor_entity_id: uuid.UUID,
    interaction_type_code: str = "other",
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    action_description: str | None = None,
    targets: tuple[TargetSpec, ...] = (),
    check_requests: tuple[CheckRequestSpec, ...] = (),
) -> PerformInteractionResult:
    """Record a structured attempt by an actor. Public convenience API:
    opens and commits its own transaction. See _perform_interaction_impl()
    for the composable form a caller with its own transaction (e.g. an API
    command endpoint) uses instead."""
    with engine.begin() as connection:
        return _perform_interaction_impl(
            connection,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            actor_entity_id=actor_entity_id,
            interaction_type_code=interaction_type_code,
            campaign_id=campaign_id,
            session_id=session_id,
            action_description=action_description,
            targets=targets,
            check_requests=check_requests,
        )


@dataclass(frozen=True)
class ResolveCheckResult:
    check_result_id: uuid.UUID
    world_id: uuid.UUID
    actor_entity_id: uuid.UUID
    event_id: uuid.UUID | None = None
    area_connection_opened: bool = False
    hazard_status_code: str | None = None
    interactable_activated: bool = False
    discovery_event_id: uuid.UUID | None = None
    discovered_knowledge_item_id: uuid.UUID | None = None


@dataclass(frozen=True)
class _CheckContext:
    actor_entity_id: uuid.UUID
    interaction_id: uuid.UUID
    interaction_type_code: str
    timeline_id: uuid.UUID
    world_time_id: uuid.UUID
    world_id: uuid.UUID
    campaign_id: uuid.UUID | None
    session_id: uuid.UUID | None
    target_area_connection_id: uuid.UUID | None
    target_area_feature_id: uuid.UUID | None
    target_area_hazard_id: uuid.UUID | None
    target_area_interactable_id: uuid.UUID | None


def _check_context(connection: Connection, check_request_id: uuid.UUID) -> _CheckContext:
    row = (
        connection.execute(
            text("""
            SELECT cr.actor_entity_id, i.interaction_id, it.code AS interaction_type_code,
                   i.timeline_id, i.world_time_id, i.campaign_id, i.session_id, t.world_id,
                   tgt.target_area_connection_id, tgt.target_area_feature_id,
                   tgt.target_area_hazard_id, tgt.target_area_interactable_id
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
            JOIN interaction.interaction_types it ON it.interaction_type_id = i.interaction_type_id
            JOIN campaign.timelines t ON t.timeline_id = i.timeline_id
            LEFT JOIN interaction.targets tgt ON tgt.target_id = cr.target_id
            WHERE cr.check_request_id = :check_request_id
        """),
            {"check_request_id": check_request_id},
        )
        .mappings()
        .one()
    )
    return _CheckContext(
        actor_entity_id=row["actor_entity_id"],
        interaction_id=row["interaction_id"],
        interaction_type_code=row["interaction_type_code"],
        timeline_id=row["timeline_id"],
        world_time_id=row["world_time_id"],
        world_id=row["world_id"],
        campaign_id=row["campaign_id"],
        session_id=row["session_id"],
        target_area_connection_id=row["target_area_connection_id"],
        target_area_feature_id=row["target_area_feature_id"],
        target_area_hazard_id=row["target_area_hazard_id"],
        target_area_interactable_id=row["target_area_interactable_id"],
    )


_TERMINAL_INTERACTION_STATUSES = frozenset({"resolved", "failed", "cancelled"})


@dataclass(frozen=True)
class LockedInteraction:
    """What `_lock_interaction_for_check_resolution()` actually found and
    locked — `interaction_id`/`campaign_id` are the interaction's own,
    authoritative, just-locked values, never the caller's
    `expected_campaign_id` argument (which the two are only guaranteed to
    agree with when it was supplied — a mismatch raises
    `InteractionNotFoundError` before this is ever constructed)."""

    interaction_id: uuid.UUID
    campaign_id: uuid.UUID | None


def _lock_interaction_for_check_resolution(
    connection: Connection,
    check_request_id: uuid.UUID,
    *,
    expected_campaign_id: uuid.UUID | None = None,
) -> LockedInteraction:
    """Resolve check_request_id's parent interaction and acquire an
    exclusive row lock on it before any check result is recorded against
    it, so two resolve_check() calls against the same interaction (e.g. two
    of its check_requests resolving concurrently) serialize rather than
    both reading the same "not yet finished" state, and so a concurrent
    campaign reparenting can't race a caller's own ownership check the way
    a separate, unlocked read would (mirrors
    dnd_ai.commands.encounters._lock_encounter's identical reasoning).

    Raises InteractionNotFoundError for a nonexistent check_request_id, or
    — when expected_campaign_id is supplied — one whose parent interaction
    belongs to a different campaign than expected: both map to a fixed,
    non-disclosing 404 rather than distinguishing "doesn't exist" from
    "exists but isn't yours". Raises InteractionNotOpenError (HTTP 409) if
    the interaction has already reached a terminal status — a check cannot
    be resolved against an interaction that has already finished
    (interaction.enforce_check_result_interaction_open(), revision 070,
    enforces the same rule at the database level as a second, independent
    guard).
    """
    row = connection.execute(
        text("""
            SELECT i.interaction_id, i.campaign_id, i.status
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
            WHERE cr.check_request_id = :check_request_id
            FOR UPDATE OF i
        """),
        {"check_request_id": check_request_id},
    ).one_or_none()
    if row is None:
        raise InteractionNotFoundError(f"check request {check_request_id} does not exist")
    if expected_campaign_id is not None and row.campaign_id != expected_campaign_id:
        raise InteractionNotFoundError(
            f"interaction {row.interaction_id} belongs to campaign {row.campaign_id!r}, "
            f"not {expected_campaign_id!r}"
        )
    if row.status in _TERMINAL_INTERACTION_STATUSES:
        raise InteractionNotOpenError(
            f"interaction {row.interaction_id} has status {row.status!r} and cannot accept "
            "another check resolution — resolved, failed, and cancelled interactions are terminal"
        )
    return LockedInteraction(interaction_id=row.interaction_id, campaign_id=row.campaign_id)


def _lock_area_connection(connection: Connection, area_connection_id: uuid.UUID) -> None:
    """Acquire an exclusive row lock on the connection itself (a structural
    row that always exists, unlike its possibly-absent campaign.
    area_connection_state row) so concurrent resolve_check() calls
    targeting the same connection serialize instead of racing to both
    decide "not yet open" and both write a conflicting opening effect."""
    connection.execute(
        text(
            "SELECT area_connection_id FROM world.area_connections WHERE area_connection_id = :ac FOR UPDATE"
        ),
        {"ac": area_connection_id},
    )


def _area_connection_status(
    connection: Connection, timeline_id: uuid.UUID, area_connection_id: uuid.UUID
) -> str | None:
    value = connection.execute(
        text("""
            SELECT cs.code FROM campaign.area_connection_state acs
            JOIN campaign.connection_statuses cs ON cs.connection_status_id = acs.connection_status_id
            WHERE acs.timeline_id = :timeline AND acs.area_connection_id = :connection
        """),
        {"timeline": timeline_id, "connection": area_connection_id},
    ).scalar()
    assert value is None or isinstance(value, str)
    return value


def _open_area_connection(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    area_connection_id: uuid.UUID,
    event_id: uuid.UUID,
    world_time_id: uuid.UUID,
    previous_status_code: str | None,
) -> None:
    """Update the typed current state and record the narrative.event_effects
    row for it, together — event_effects' own comment (revision 057)
    requires "common effects should also update the corresponding typed
    state table in the same transaction"; this is that pairing for the one
    reaction resolve_check knows how to produce today. previous_status_code
    is read by the caller under _lock_area_connection's row lock, not
    re-read here, so the recorded previous_value reflects the actual state
    at the moment of the transition rather than a second, potentially
    stale read.
    """
    open_status_id = lookup_id(
        connection, "campaign", "connection_statuses", "connection_status_id", "open"
    )
    connection.execute(
        text("""
            INSERT INTO campaign.area_connection_state
                (timeline_id, area_connection_id, connection_status_id, last_event_id)
            VALUES (:timeline, :connection, :status, :event)
            ON CONFLICT (timeline_id, area_connection_id) DO UPDATE
            SET connection_status_id = EXCLUDED.connection_status_id,
                last_event_id = EXCLUDED.last_event_id,
                updated_at = now()
        """),
        {
            "timeline": timeline_id,
            "connection": area_connection_id,
            "status": open_status_id,
            "event": event_id,
        },
    )

    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_area_connection_id, target_component, previous_value,
                 new_value, effective_world_time_id)
            VALUES (:event, :connection, 'connection_status_id', :previous, :new, :world_time)
        """),
        {
            "event": event_id,
            "connection": area_connection_id,
            "previous": json.dumps(previous_status_code),
            "new": json.dumps("open"),
            "world_time": world_time_id,
        },
    )


_SUCCESS_DEGREES = frozenset({"success", "critical_success"})


def _hazard_status(
    connection: Connection, timeline_id: uuid.UUID, area_hazard_id: uuid.UUID
) -> str | None:
    value = connection.execute(
        text("""
            SELECT hs.code FROM campaign.hazard_state hst
            JOIN campaign.hazard_statuses hs ON hs.hazard_status_id = hst.hazard_status_id
            WHERE hst.timeline_id = :timeline AND hst.area_hazard_id = :hazard
        """),
        {"timeline": timeline_id, "hazard": area_hazard_id},
    ).scalar()
    assert value is None or isinstance(value, str)
    return value


def _lock_hazard(connection: Connection, area_hazard_id: uuid.UUID) -> None:
    """Mirrors `_lock_area_connection`'s identical reasoning: locks the
    structural row itself (always present) so two concurrent `resolve_
    check()` calls targeting the same hazard serialize rather than racing
    to both decide the same prior status and both write a conflicting
    effect."""
    connection.execute(
        text("SELECT area_hazard_id FROM world.area_hazards WHERE area_hazard_id = :h FOR UPDATE"),
        {"h": area_hazard_id},
    )


def _hazard_outcome_status(interaction_type_code: str, degree_of_success: str) -> str | None:
    """The `campaign.hazard_statuses` code a check against a hazard should
    transition to, or `None` if this interaction type/outcome combination
    has no hazard reaction at all. A failed `disarm_trap` attempt sets the
    trap off (`triggered`) rather than leaving it `armed` — the dramatic
    and mechanically standard D&D outcome; a failed `trigger_trap` attempt
    (a deliberate attempt to set it off that didn't land) produces no
    reaction, mirroring `_open_area_connection`'s own "a failed check
    simply has nothing further to react to" precedent."""
    succeeded = degree_of_success in _SUCCESS_DEGREES
    if interaction_type_code == "disarm_trap":
        return "disarmed" if succeeded else "triggered"
    if interaction_type_code == "trigger_trap":
        return "triggered" if succeeded else None
    return None


def _change_hazard_status(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    area_hazard_id: uuid.UUID,
    event_id: uuid.UUID,
    new_status_code: str,
    previous_status_code: str | None,
) -> None:
    """Update the typed current state and record the narrative.event_effects
    row for it, together — mirrors `_open_area_connection`'s identical
    pairing for `campaign.area_connection_state`. Unlike that table,
    `campaign.hazard_state` carries no `last_event_id` column of its own
    (migration 040 predates that convention, added by migration 060 to
    the tables that existed by then) — nothing here regresses that; the
    event linkage still exists via `narrative.event_effects.event_id`."""
    new_status_id = lookup_id(
        connection, "campaign", "hazard_statuses", "hazard_status_id", new_status_code
    )
    connection.execute(
        text("""
            INSERT INTO campaign.hazard_state (timeline_id, area_hazard_id, hazard_status_id)
            VALUES (:timeline, :hazard, :status)
            ON CONFLICT (timeline_id, area_hazard_id) DO UPDATE
            SET hazard_status_id = EXCLUDED.hazard_status_id, updated_at = now()
        """),
        {"timeline": timeline_id, "hazard": area_hazard_id, "status": new_status_id},
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_area_hazard_id, target_component, previous_value, new_value)
            VALUES (:event, :hazard, 'hazard_status_id', :previous, :new)
        """),
        {
            "event": event_id,
            "hazard": area_hazard_id,
            "previous": json.dumps(previous_status_code),
            "new": json.dumps(new_status_code),
        },
    )


def _interactable_status(
    connection: Connection, timeline_id: uuid.UUID, area_interactable_id: uuid.UUID
) -> str | None:
    value = connection.execute(
        text("""
            SELECT ist.code FROM campaign.interactable_state ins
            JOIN campaign.interactable_statuses ist
                ON ist.interactable_status_id = ins.interactable_status_id
            WHERE ins.timeline_id = :timeline AND ins.area_interactable_id = :interactable
        """),
        {"timeline": timeline_id, "interactable": area_interactable_id},
    ).scalar()
    assert value is None or isinstance(value, str)
    return value


def _lock_interactable(connection: Connection, area_interactable_id: uuid.UUID) -> None:
    connection.execute(
        text(
            "SELECT area_interactable_id FROM world.area_interactables "
            "WHERE area_interactable_id = :i FOR UPDATE"
        ),
        {"i": area_interactable_id},
    )


def _activate_interactable(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    area_interactable_id: uuid.UUID,
    event_id: uuid.UUID,
    previous_status_code: str | None,
) -> None:
    """Mirrors `_change_hazard_status()`'s identical pairing for `campaign.
    interactable_state`."""
    activated_status_id = lookup_id(
        connection, "campaign", "interactable_statuses", "interactable_status_id", "activated"
    )
    connection.execute(
        text("""
            INSERT INTO campaign.interactable_state
                (timeline_id, area_interactable_id, interactable_status_id)
            VALUES (:timeline, :interactable, :status)
            ON CONFLICT (timeline_id, area_interactable_id) DO UPDATE
            SET interactable_status_id = EXCLUDED.interactable_status_id, updated_at = now()
        """),
        {
            "timeline": timeline_id,
            "interactable": area_interactable_id,
            "status": activated_status_id,
        },
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_area_interactable_id, target_component, previous_value,
                 new_value)
            VALUES (:event, :interactable, 'interactable_status_id', :previous, :new)
        """),
        {
            "event": event_id,
            "interactable": area_interactable_id,
            "previous": json.dumps(previous_status_code),
            "new": json.dumps("activated"),
        },
    )


# Maps each hidden-eligible target column to the structural table/PK column
# that carries its own is_hidden flag, and to the knowledge.knowledge_items
# column that names it as a discovery subject — the write-side counterpart
# to dnd_ai.queries.dungeon's identical _DISCOVERY_EXISTS join (see that
# module's docstring). Every value here is an internal literal, never
# user-controlled, so interpolating them into SQL below is safe.
_HIDDEN_TARGET_TABLES: dict[str, tuple[str, str, str]] = {
    "target_area_connection_id": (
        "world.area_connections",
        "area_connection_id",
        "subject_area_connection_id",
    ),
    "target_area_feature_id": (
        "world.area_features",
        "area_feature_id",
        "subject_area_feature_id",
    ),
    "target_area_hazard_id": (
        "world.area_hazards",
        "area_hazard_id",
        "subject_area_hazard_id",
    ),
    "target_area_interactable_id": (
        "world.area_interactables",
        "area_interactable_id",
        "subject_area_interactable_id",
    ),
}


def _resolve_hidden_target(context: _CheckContext) -> tuple[str, uuid.UUID] | None:
    """Whichever one of the four hidden-eligible target kinds this check's
    target hit, or `None` if it targeted a bare entity or nothing at all
    (`interaction.targets`' own "at most one target column set" shape
    means at most one of these is ever non-`None`)."""
    for column in _HIDDEN_TARGET_TABLES:
        value = getattr(context, column)
        if value is not None:
            return column, value
    return None


def _maybe_discover_target(
    connection: Connection, *, context: _CheckContext, party_id: uuid.UUID | None
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Reveals the check's own target to `party_id`, when it is hidden, a
    `knowledge.knowledge_items` row names it as `subject_area_*_id`, and
    `party_id` has not already discovered it — the write-side counterpart
    to `dnd_ai.queries.dungeon.get_dungeon_area_view`'s identical
    discovery-eligibility join (see that module's own docstring for why a
    hidden, undiscovered child must be indistinguishable from one that
    doesn't exist). Returns `(event_id, knowledge_item_id)` when a
    discovery was recorded, else `None` — no target, no `party_id`, not
    hidden, no matching knowledge item, or already discovered."""
    if party_id is None:
        return None
    resolved = _resolve_hidden_target(context)
    if resolved is None:
        return None
    target_column, target_id = resolved
    table, pk_column, subject_column = _HIDDEN_TARGET_TABLES[target_column]

    is_hidden = connection.execute(
        text(f"SELECT is_hidden FROM {table} WHERE {pk_column} = :target"),  # noqa: S608
        {"target": target_id},
    ).scalar()
    if not is_hidden:
        return None

    knowledge_item_id = connection.execute(
        text(
            f"SELECT knowledge_item_id FROM knowledge.knowledge_items "  # noqa: S608
            f"WHERE {subject_column} = :target"
        ),
        {"target": target_id},
    ).scalar()
    if knowledge_item_id is None:
        return None

    already_discovered = connection.execute(
        text("""
            SELECT 1 FROM knowledge.party_discoveries
            WHERE timeline_id = :timeline AND party_id = :party AND knowledge_item_id = :item
        """),
        {"timeline": context.timeline_id, "party": party_id, "item": knowledge_item_id},
    ).scalar()
    if already_discovered:
        return None

    event_id = _insert_event_row(
        connection,
        world_id=context.world_id,
        timeline_id=context.timeline_id,
        world_time_id=context.world_time_id,
        event_type_code="knowledge_revealed",
        name="Hidden feature discovered",
        campaign_id=context.campaign_id,
        session_id=context.session_id,
        participants=(EventParticipant(entity_id=context.actor_entity_id, role_code="actor"),),
        cause_interaction_id=context.interaction_id,
    )

    connection.execute(
        text("""
            INSERT INTO knowledge.party_discoveries
                (timeline_id, knowledge_item_id, party_id, discovered_at_world_time_id,
                 discovered_via_interaction_id)
            VALUES (:timeline, :item, :party, :world_time, :interaction)
        """),
        {
            "timeline": context.timeline_id,
            "item": knowledge_item_id,
            "party": party_id,
            "world_time": context.world_time_id,
            "interaction": context.interaction_id,
        },
    )

    connection.execute(
        text(f"""
            INSERT INTO narrative.event_effects
                (event_id, {target_column}, target_component, previous_value, new_value)
            VALUES (:event, :target, 'discovered', :previous, :new)
        """),  # noqa: S608
        {
            "event": event_id,
            "target": target_id,
            "previous": json.dumps(False),
            "new": json.dumps(True),
        },
    )

    return event_id, knowledge_item_id


def _resolve_interaction(
    connection: Connection,
    *,
    interaction_id: uuid.UUID,
    outcomes: tuple[tuple[uuid.UUID, str | None], ...],
) -> None:
    """Links this call's event(s), if any, to the interaction — one
    `interaction.consequences` row per event produced. `interaction.
    interactions.resulting_event_id` (a single column) is set to
    `outcomes[0]`'s event: callers list the mechanically primary state
    change (connection/hazard/interactable) first when one occurred,
    falling back to a discovery-only event otherwise — see this module's
    own docstring for the full priority. The status transition itself
    (initiated -> resolving -> resolved) is no longer set here —
    interaction.advance_interaction_status_on_check_result() (revision
    072) now owns it, firing atomically with the check_results INSERT
    resolve_check() already performs, so it applies to any caller that
    records a check result, not only this command.

    A failed or non-matching check with no discovery either still
    contributes no event — it simply has nothing to link and no
    consequence to record (SYSTEM_ARCHITECTURE.md §6).
    """
    if not outcomes:
        return
    primary_event_id = outcomes[0][0]
    connection.execute(
        text("""
            UPDATE interaction.interactions SET resulting_event_id = :event
            WHERE interaction_id = :interaction
        """),
        {"event": primary_event_id, "interaction": interaction_id},
    )
    for event_id, description in outcomes:
        connection.execute(
            text("""
                INSERT INTO interaction.consequences
                    (interaction_id, consequence_type, status, resulting_event_id, description)
                VALUES (:interaction, 'state_change', 'resolved', :event, :description)
            """),
            {"interaction": interaction_id, "event": event_id, "description": description},
        )


def _resolve_check_impl(
    connection: Connection,
    *,
    check_request_id: uuid.UUID,
    degree_of_success: str,
    roll: int | None = None,
    total_modifier: int | None = None,
    total: int | None = None,
    is_visible_to_players: bool = True,
    external_system_source: str | None = None,
    event_details: str | None = None,
    expected_campaign_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> ResolveCheckResult:
    """The actual work of resolve_check(), on a connection the caller
    already has open — see dnd_ai.commands.encounters._resolve_combat_turn_
    impl's docstring for the composable-implementation/public-wrapper
    pattern this mirrors. A caller that owns the surrounding transaction
    itself (e.g. the API layer's per-request connection) calls this
    directly.

    Record a check's outcome and, when it satisfies a conditional route's
    requirement (world.conditional_route_requirement_satisfied), record the
    resulting event and open the route atomically. A check with no
    conditional-route target, or one that doesn't satisfy the requirement,
    still records its result — it simply has no further reaction, per
    docs/architecture/SYSTEM_ARCHITECTURE.md §6 step 5 ("create events when
    the mutation is narratively significant"). The parent interaction's
    status moves initiated -> resolving -> resolved as a side effect of the
    check_results INSERT itself
    (interaction.advance_interaction_status_on_check_result(), revision
    072) — never before the last outstanding check_request has a result,
    and never more than once.

    The parent interaction is resolved and locked
    (_lock_interaction_for_check_resolution) before anything else happens:
    this both rejects resolving a check whose interaction has already
    reached a terminal status or belongs to a different campaign than
    expected_campaign_id, and — since the lock is held until commit —
    serializes concurrent resolve_check() calls against the same
    interaction, so two of its check_requests resolving at once can't both
    miscount how many are still outstanding. expected_campaign_id=None
    skips only the ownership assertion, mirroring
    dnd_ai.commands.encounters._lock_encounter's identical parameter — a
    direct/administrative caller with no campaign context of its own to
    assert.

    Concurrent resolve_check() calls targeting the same conditional route
    are additionally serialized by _lock_area_connection: the second caller
    blocks until the first commits, then re-reads campaign.
    area_connection_state under that lock before deciding whether the route
    still needs opening — so a route two competing successful checks both
    satisfy is opened, and its event/effect recorded, exactly once. This
    matters even when both checks belong to the same interaction (locked
    above) and, unchanged, when they belong to two different interactions
    entirely (not covered by the interaction-level lock at all).

    party_id is caller-supplied and used only for discovery
    (_maybe_discover_target). Unlike dnd_ai.queries.dungeon.
    get_dungeon_area_view (which serves both a GM and a specific party's
    own perspective and so must authorize party_id via dnd_ai.api.access.
    resolve_party_perspective before trusting it), this function's one
    caller today (dnd_ai.api.interactions.resolve_check_endpoint) requires
    canon.edit — a GM/adapter-level caller, not a specific party's own
    player — so party_id here is trusted the same way every other GM-gated
    Phase 10 endpoint bypasses a party-perspective check entirely. Omitting
    it (None) simply disables discovery for this call, never an error.
    """
    locked = _lock_interaction_for_check_resolution(
        connection, check_request_id, expected_campaign_id=expected_campaign_id
    )
    interaction_id = locked.interaction_id

    check_result_id = connection.execute(
        text("""
            INSERT INTO interaction.check_results
                (check_request_id, roll, total_modifier, total, degree_of_success,
                 is_visible_to_players, external_system_source)
            VALUES (:request, :roll, :total_modifier, :total, :degree, :visible, :source)
            RETURNING check_result_id
        """),
        {
            "request": check_request_id,
            "roll": roll,
            "total_modifier": total_modifier,
            "total": total,
            "degree": degree_of_success,
            "visible": is_visible_to_players,
            "source": external_system_source,
        },
    ).scalar()
    assert isinstance(check_result_id, uuid.UUID)

    context = _check_context(connection, check_request_id)
    target_area_connection_id = context.target_area_connection_id

    event_id: uuid.UUID | None = None
    area_connection_opened = False
    hazard_status_code: str | None = None
    interactable_activated = False

    # --- Primary, mutually exclusive reactions (interaction.targets' own
    # "at most one target column set" shape guarantees only one of these
    # three blocks can ever apply to a given check). ---
    if target_area_connection_id is not None:
        _lock_area_connection(connection, target_area_connection_id)

        satisfied = connection.execute(
            text("SELECT world.conditional_route_requirement_satisfied(:ac, :cr)"),
            {"ac": target_area_connection_id, "cr": check_result_id},
        ).scalar()

        if satisfied:
            previous_status_code = _area_connection_status(
                connection, context.timeline_id, target_area_connection_id
            )
            if previous_status_code != "open":
                event_id = _insert_event_row(
                    connection,
                    world_id=context.world_id,
                    timeline_id=context.timeline_id,
                    world_time_id=context.world_time_id,
                    event_type_code="mechanism_activated",
                    name="Conditional route requirement satisfied",
                    details=event_details,
                    campaign_id=context.campaign_id,
                    session_id=context.session_id,
                    participants=(
                        EventParticipant(entity_id=context.actor_entity_id, role_code="actor"),
                    ),
                    cause_interaction_id=context.interaction_id,
                )
                _open_area_connection(
                    connection,
                    timeline_id=context.timeline_id,
                    area_connection_id=target_area_connection_id,
                    event_id=event_id,
                    world_time_id=context.world_time_id,
                    previous_status_code=previous_status_code,
                )
                area_connection_opened = True
    elif context.target_area_hazard_id is not None:
        outcome_status = _hazard_outcome_status(context.interaction_type_code, degree_of_success)
        if outcome_status is not None:
            _lock_hazard(connection, context.target_area_hazard_id)
            previous_status_code = _hazard_status(
                connection, context.timeline_id, context.target_area_hazard_id
            )
            if previous_status_code != outcome_status:
                event_type_code = (
                    "hazard_disarmed" if outcome_status == "disarmed" else "hazard_triggered"
                )
                event_id = _insert_event_row(
                    connection,
                    world_id=context.world_id,
                    timeline_id=context.timeline_id,
                    world_time_id=context.world_time_id,
                    event_type_code=event_type_code,
                    name=f"Hazard {outcome_status}",
                    details=event_details,
                    campaign_id=context.campaign_id,
                    session_id=context.session_id,
                    participants=(
                        EventParticipant(entity_id=context.actor_entity_id, role_code="actor"),
                    ),
                    cause_interaction_id=context.interaction_id,
                )
                _change_hazard_status(
                    connection,
                    timeline_id=context.timeline_id,
                    area_hazard_id=context.target_area_hazard_id,
                    event_id=event_id,
                    new_status_code=outcome_status,
                    previous_status_code=previous_status_code,
                )
                hazard_status_code = outcome_status
    elif context.target_area_interactable_id is not None:
        if context.interaction_type_code == "activate_mechanism" and (
            degree_of_success in _SUCCESS_DEGREES
        ):
            _lock_interactable(connection, context.target_area_interactable_id)
            previous_status_code = _interactable_status(
                connection, context.timeline_id, context.target_area_interactable_id
            )
            if previous_status_code != "activated":
                event_id = _insert_event_row(
                    connection,
                    world_id=context.world_id,
                    timeline_id=context.timeline_id,
                    world_time_id=context.world_time_id,
                    event_type_code="mechanism_activated",
                    name="Mechanism activated",
                    details=event_details,
                    campaign_id=context.campaign_id,
                    session_id=context.session_id,
                    participants=(
                        EventParticipant(entity_id=context.actor_entity_id, role_code="actor"),
                    ),
                    cause_interaction_id=context.interaction_id,
                )
                _activate_interactable(
                    connection,
                    timeline_id=context.timeline_id,
                    area_interactable_id=context.target_area_interactable_id,
                    event_id=event_id,
                    previous_status_code=previous_status_code,
                )
                interactable_activated = True

    # --- Discovery: independent of the above, only when the check itself
    # succeeded (an unsuccessful search reveals nothing). ---
    discovery: tuple[uuid.UUID, uuid.UUID] | None = None
    if degree_of_success in _SUCCESS_DEGREES:
        discovery = _maybe_discover_target(connection, context=context, party_id=party_id)

    outcomes: list[tuple[uuid.UUID, str | None]] = []
    if event_id is not None:
        if area_connection_opened:
            description = (
                f"Check satisfied area connection {target_area_connection_id}'s requirement; "
                "route opened."
            )
        elif hazard_status_code is not None:
            description = f"Check {hazard_status_code} hazard {context.target_area_hazard_id}."
        elif interactable_activated:
            description = f"Check activated interactable {context.target_area_interactable_id}."
        else:  # pragma: no cover - defensive; event_id is only ever set alongside one of the above
            description = None
        outcomes.append((event_id, description))
    if discovery is not None:
        discovery_event_id, knowledge_item_id = discovery
        outcomes.append((discovery_event_id, f"Discovered knowledge item {knowledge_item_id}."))

    _resolve_interaction(
        connection,
        interaction_id=interaction_id,
        outcomes=tuple(outcomes),
    )

    return ResolveCheckResult(
        check_result_id=check_result_id,
        world_id=context.world_id,
        actor_entity_id=context.actor_entity_id,
        event_id=event_id,
        area_connection_opened=area_connection_opened,
        hazard_status_code=hazard_status_code,
        interactable_activated=interactable_activated,
        discovery_event_id=discovery[0] if discovery is not None else None,
        discovered_knowledge_item_id=discovery[1] if discovery is not None else None,
    )


def resolve_check(
    engine: Engine,
    *,
    check_request_id: uuid.UUID,
    degree_of_success: str,
    roll: int | None = None,
    total_modifier: int | None = None,
    total: int | None = None,
    is_visible_to_players: bool = True,
    external_system_source: str | None = None,
    event_details: str | None = None,
    expected_campaign_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> ResolveCheckResult:
    """Record a check's outcome, atomically reacting to it when narratively
    significant. Public convenience API: opens and commits its own
    transaction. See _resolve_check_impl() for the composable form a caller
    with its own transaction (e.g. an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _resolve_check_impl(
            connection,
            check_request_id=check_request_id,
            degree_of_success=degree_of_success,
            roll=roll,
            total_modifier=total_modifier,
            total=total,
            is_visible_to_players=is_visible_to_players,
            external_system_source=external_system_source,
            event_details=event_details,
            expected_campaign_id=expected_campaign_id,
            party_id=party_id,
        )
