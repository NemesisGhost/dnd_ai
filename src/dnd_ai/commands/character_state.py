"""Non-combat character-state commands: hit-point adjustment, condition
apply/remove, and resource adjustment — Phase 11 workstream 6, closing the
last remaining gap in "synchronize the minimum required character HP,
conditions, resource use" (docs/PLAN.md Phase 11). Combat-turn HP change
and `resulting_condition_id` are already covered by
`dnd_ai.commands.encounters._resolve_combat_turn_impl`; this module
covers everything *outside* a combat turn — a short rest's healing, a
potion, falling/environmental damage, a non-combat status effect, spell-
slot/ki/rage-use tracking. Inventory synchronization is already covered
by `dnd_ai.commands.items` (Phase 9).

Each command mirrors `dnd_ai.commands.movement._enter_location_impl`'s
own shape exactly: lock the exact row about to change via `SELECT ...
FOR UPDATE` on its own primary key (never a heavier "structural parent"
lock — there is no parent row here the way `narrative.encounters` is one
for a combat turn), compute the new value, and — only if the value
actually changes — create a causal event (`dnd_ai.commands.events.
_insert_event_row`) and an `narrative.event_effects` row in the same
transaction before writing the new value, exactly the "state changes
need a causal event, and they commit atomically" contract CLAUDE.md rule
6 states and `_resolve_combat_turn_impl`/`_enter_location_impl` both
already follow. A call that would not actually change anything (e.g.
healing a character already at full HP, applying a condition already
applied, removing a condition not present) is a no-op — no event, no
effect row, no row write — mirroring `enter_location`'s own "re-entering
the current location is a no-op" idempotence rather than treating a
redundant call as an error.

`target_component` literals: `'current_hit_points'` (reused verbatim from
`_resolve_combat_turn_impl` — the same column, the same meaning, whether
the change came from combat or not) for hit-point adjustment;
`'condition_id'` for condition apply/remove (no prior convention existed
for this table, confirmed by grep — this names the column being changed
on `campaign.character_conditions`, following the same "name the actual
column" rule `'current_hit_points'`/`'current_location_id'` already
establish); `'current_amount'` for resource adjustment (same rule,
naming `campaign.character_resources`' own mutated column).

World/timeline ownership: every command below resolves `world_id` from
`timeline_id` and asserts `character_id` belongs to it, identically to
`dnd_ai.commands.movement._enter_location_impl` — see that module's own
docstring for why a bare foreign key is not sufficient (a `BEFORE INSERT/
UPDATE` trigger's own cross-world check raises the unrecognized bare
`ERRCODE = 'integrity_constraint_violation'`, which would otherwise
surface as an unclassified 500 instead of the intended, non-disclosing
404) and why `world_id` is never caller-supplied.

Resource bounds (`campaign.character_resources.current_amount <=
maximum_amount`, `core.nonnegative_integer >= 0`) are deliberately left
to the database's own existing `CHECK`/domain constraints rather than
duplicated here — both SQLSTATEs (`23514`, `23001`) are already mapped
to a clean 400 by the generic `IntegrityError` handler
(`dnd_ai.api.errors._INVALID_REQUEST_INTEGRITY_SQLSTATES`), the same
"let an existing, already-correctly-classified backstop do the work"
reasoning `dnd_ai.commands.memberships`' own docstring applies to its
`ux_membership_roles_active`/`ux_campaign_memberships_open` unique
indexes.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError

from ._shared import validate_session_campaign
from .events import EventParticipant, _insert_event_row


class CharacterNotInWorldError(DomainAuthorizationError):
    """Raised by every command below when `character_id` does not belong
    to `timeline_id`'s own world — including a nonexistent character,
    identically, mirroring `dnd_ai.commands.movement`'s identical error.
    The supplied ids are included only in the constructor's `detail`
    argument (`str(self)`), never in `safe_message`."""


class CharacterResourceNotTrackedError(DomainAuthorizationError):
    """Raised by `adjust_character_resource()` when `character_id` has no
    existing `campaign.character_resources` row for `resource_definition_id`
    on `timeline_id` — there is no "default maximum" this command could
    invent to create one; a resource must already be tracked (by whatever
    future character-build/initialization path populates it) before its
    amount can be adjusted. Mirrors the same "confirming absence vs.
    cross-world mismatch would both be disclosures" reasoning every other
    `DomainAuthorizationError` subclass in this codebase applies, even
    though this specific case has no cross-world ambiguity to hide — the
    fixed, non-disclosing 404 is still the right shape for "nothing here
    to adjust." The supplied ids are included only in the constructor's
    `detail` argument (`str(self)`), never in `safe_message`."""


def _world_id_for_timeline(connection: Connection, *, timeline_id: uuid.UUID) -> uuid.UUID:
    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :timeline"),
        {"timeline": timeline_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)
    return world_id


def _assert_character_in_world(
    connection: Connection, *, character_id: uuid.UUID, world_id: uuid.UUID
) -> None:
    character_world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :character"),
        {"character": character_id},
    ).scalar()
    if character_world_id is None or character_world_id != world_id:
        raise CharacterNotInWorldError(
            f"character {character_id} does not exist in world {world_id} "
            f"(actual world: {character_world_id})"
        )


# ---------------------------------------------------------------------------
# adjust_hit_points
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdjustHitPointsResult:
    event_id: uuid.UUID | None
    previous_hit_points: int
    new_hit_points: int
    changed: bool


def _adjust_hit_points_impl(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    world_time_id: uuid.UUID,
    delta: int,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> AdjustHitPointsResult:
    """The actual work of `adjust_hit_points()`, on a connection the
    caller already has open — see `dnd_ai.commands.encounters._resolve_
    combat_turn_impl`'s docstring for the composable-implementation/
    public-wrapper pattern this mirrors.

    `delta` may be positive (healing) or negative (non-combat damage —
    falling, a trap, the environment); this module deliberately has no
    separate "heal" vs. "damage" command, the same single-code reasoning
    this module's own docstring gives for `hit_points_adjusted`. The
    resulting `current_hit_points` is clamped to `[0, maximum_hit_points]`
    by `LEAST`/`GREATEST` in the same `UPDATE` that applies it — an
    over-heal or lethal delta is silently bounded rather than rejected,
    the same "a heal past maximum simply caps" rule most tabletop rulesets
    already use, not a validation failure a caller needs to pre-compute
    around."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

    world_id = _world_id_for_timeline(connection, timeline_id=timeline_id)
    _assert_character_in_world(connection, character_id=character_id, world_id=world_id)

    row = (
        connection.execute(
            text("""
                SELECT current_hit_points, maximum_hit_points
                FROM campaign.character_state
                WHERE timeline_id = :timeline AND character_id = :character
                FOR UPDATE
            """),
            {"timeline": timeline_id, "character": character_id},
        )
        .mappings()
        .one()
    )
    previous_hit_points = row["current_hit_points"]
    maximum_hit_points = row["maximum_hit_points"]
    new_hit_points = max(0, min(maximum_hit_points, previous_hit_points + delta))

    if new_hit_points == previous_hit_points:
        return AdjustHitPointsResult(
            event_id=None,
            previous_hit_points=previous_hit_points,
            new_hit_points=new_hit_points,
            changed=False,
        )

    event_id = _insert_event_row(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="hit_points_adjusted",
        name="Character hit points adjusted",
        details=details,
        campaign_id=campaign_id,
        session_id=session_id,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )

    connection.execute(
        text("""
            UPDATE campaign.character_state
            SET current_hit_points = :hp, last_event_id = :event, updated_at = now()
            WHERE timeline_id = :timeline AND character_id = :character
        """),
        {
            "hp": new_hit_points,
            "event": event_id,
            "timeline": timeline_id,
            "character": character_id,
        },
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:event, :character, 'current_hit_points', :previous, :new, :world_time)
        """),
        {
            "event": event_id,
            "character": character_id,
            "previous": json.dumps(previous_hit_points),
            "new": json.dumps(new_hit_points),
            "world_time": world_time_id,
        },
    )

    return AdjustHitPointsResult(
        event_id=event_id,
        previous_hit_points=previous_hit_points,
        new_hit_points=new_hit_points,
        changed=True,
    )


def adjust_hit_points(
    engine: Engine,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    world_time_id: uuid.UUID,
    delta: int,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> AdjustHitPointsResult:
    """Applies `delta` (positive for healing, negative for non-combat
    damage) to `character_id`'s current hit points, clamped to
    `[0, maximum_hit_points]`, and records the change as a narrative
    event. Public convenience API: opens and commits its own transaction.
    See `_adjust_hit_points_impl()` for the composable form a caller with
    its own transaction (e.g. an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _adjust_hit_points_impl(
            connection,
            timeline_id=timeline_id,
            character_id=character_id,
            world_time_id=world_time_id,
            delta=delta,
            campaign_id=campaign_id,
            session_id=session_id,
            details=details,
        )


# ---------------------------------------------------------------------------
# apply_character_condition / remove_character_condition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApplyCharacterConditionResult:
    event_id: uuid.UUID | None
    changed: bool


def _apply_character_condition_impl(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    condition_id: uuid.UUID,
    world_time_id: uuid.UUID,
    source_description: str | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> ApplyCharacterConditionResult:
    """The actual work of `apply_character_condition()`, on a connection
    the caller already has open — see `_adjust_hit_points_impl`'s
    docstring for the composable-implementation/public-wrapper pattern
    this mirrors.

    `condition_id` (a real `rules.conditions` row), never a bare code:
    `rules.conditions.code` is unique only *per `ruleset_version_id`*
    (`ux_conditions_ruleset_version_code`), not globally, so a bare-code
    lookup with no ruleset scoping could resolve an arbitrary row from an
    unrelated ruleset — the same reasoning `dnd_ai.api.encounters.
    ResolveCombatTurnRequest.resulting_condition_id`/`.damage_type_id`
    already take a UUID rather than a code for this exact class of
    ruleset-scoped table. A nonexistent `condition_id` is rejected as a
    400 by `campaign.character_conditions.condition_id`'s own foreign
    key; one that exists but is not on the character's ruleset's own
    allow-list is rejected by `campaign.
    tr_character_conditions_enforce_ruleset_allowed` (migration 066) —
    left as a database-level backstop rather than duplicated here, the
    same "let an existing, already-triggered check do the work" reasoning
    this module's own docstring gives for the resource-amount bounds.

    `campaign.character_conditions`' own primary key is `(timeline_id,
    character_id, condition_id)` — at most one row per distinct condition
    (no stacking; exhaustion stacking is represented on `character_state.
    exhaustion_level` instead, a different table this command does not
    touch). Applying a condition already applied is therefore a no-op —
    mirroring `enter_location`'s own "already there" idempotence — rather
    than an upsert that would silently overwrite `source_description`,
    or a hard rejection — neither fits "the caller asked for a state
    that's already true."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

    world_id = _world_id_for_timeline(connection, timeline_id=timeline_id)
    _assert_character_in_world(connection, character_id=character_id, world_id=world_id)

    existing = connection.execute(
        text("""
            SELECT 1 FROM campaign.character_conditions
            WHERE timeline_id = :timeline AND character_id = :character
              AND condition_id = :condition
            FOR UPDATE
        """),
        {"timeline": timeline_id, "character": character_id, "condition": condition_id},
    ).scalar()
    if existing is not None:
        return ApplyCharacterConditionResult(event_id=None, changed=False)

    event_id = _insert_event_row(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="condition_applied",
        name="Condition applied",
        details=details,
        campaign_id=campaign_id,
        session_id=session_id,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )

    connection.execute(
        text("""
            INSERT INTO campaign.character_conditions
                (timeline_id, character_id, condition_id, source_description, last_event_id)
            VALUES (:timeline, :character, :condition, :source, :event)
        """),
        {
            "timeline": timeline_id,
            "character": character_id,
            "condition": condition_id,
            "source": source_description,
            "event": event_id,
        },
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:event, :character, 'condition_id', NULL, :new, :world_time)
        """),
        {
            "event": event_id,
            "character": character_id,
            "new": json.dumps(str(condition_id)),
            "world_time": world_time_id,
        },
    )

    return ApplyCharacterConditionResult(event_id=event_id, changed=True)


def apply_character_condition(
    engine: Engine,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    condition_id: uuid.UUID,
    world_time_id: uuid.UUID,
    source_description: str | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> ApplyCharacterConditionResult:
    """Applies `condition_id` to `character_id`, recording the change as
    a narrative event. A no-op (see `_apply_character_condition_impl`'s
    docstring) if already applied. Public convenience API: opens and
    commits its own transaction. See `_apply_character_condition_impl()`
    for the composable form a caller with its own transaction uses
    instead."""
    with engine.begin() as connection:
        return _apply_character_condition_impl(
            connection,
            timeline_id=timeline_id,
            character_id=character_id,
            condition_id=condition_id,
            world_time_id=world_time_id,
            source_description=source_description,
            campaign_id=campaign_id,
            session_id=session_id,
            details=details,
        )


@dataclass(frozen=True)
class RemoveCharacterConditionResult:
    event_id: uuid.UUID | None
    changed: bool


def _remove_character_condition_impl(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    condition_id: uuid.UUID,
    world_time_id: uuid.UUID,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> RemoveCharacterConditionResult:
    """The actual work of `remove_character_condition()`, on a connection
    the caller already has open. `condition_id`, not a bare code — see
    `_apply_character_condition_impl`'s own docstring for why. Removing a
    condition not currently applied is a no-op — the same "retry is a
    harmless no-op" idempotence `dnd_ai.commands.memberships.
    revoke_membership_role`'s own docstring establishes for its identical
    shape."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

    world_id = _world_id_for_timeline(connection, timeline_id=timeline_id)
    _assert_character_in_world(connection, character_id=character_id, world_id=world_id)

    existing = connection.execute(
        text("""
            SELECT 1 FROM campaign.character_conditions
            WHERE timeline_id = :timeline AND character_id = :character
              AND condition_id = :condition
            FOR UPDATE
        """),
        {"timeline": timeline_id, "character": character_id, "condition": condition_id},
    ).scalar()
    if existing is None:
        return RemoveCharacterConditionResult(event_id=None, changed=False)

    event_id = _insert_event_row(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="condition_removed",
        name="Condition removed",
        details=details,
        campaign_id=campaign_id,
        session_id=session_id,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )

    connection.execute(
        text("""
            DELETE FROM campaign.character_conditions
            WHERE timeline_id = :timeline AND character_id = :character
              AND condition_id = :condition
        """),
        {"timeline": timeline_id, "character": character_id, "condition": condition_id},
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:event, :character, 'condition_id', :previous, NULL, :world_time)
        """),
        {
            "event": event_id,
            "character": character_id,
            "previous": json.dumps(str(condition_id)),
            "world_time": world_time_id,
        },
    )

    return RemoveCharacterConditionResult(event_id=event_id, changed=True)


def remove_character_condition(
    engine: Engine,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    condition_id: uuid.UUID,
    world_time_id: uuid.UUID,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> RemoveCharacterConditionResult:
    """Removes `condition_id` from `character_id`, recording the change
    as a narrative event. A no-op if not currently applied. Public
    convenience API: opens and commits its own transaction. See
    `_remove_character_condition_impl()` for the composable form a caller
    with its own transaction uses instead."""
    with engine.begin() as connection:
        return _remove_character_condition_impl(
            connection,
            timeline_id=timeline_id,
            character_id=character_id,
            condition_id=condition_id,
            world_time_id=world_time_id,
            campaign_id=campaign_id,
            session_id=session_id,
            details=details,
        )


# ---------------------------------------------------------------------------
# adjust_character_resource
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdjustCharacterResourceResult:
    event_id: uuid.UUID | None
    previous_amount: int
    new_amount: int
    changed: bool


def _adjust_character_resource_impl(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    resource_definition_id: uuid.UUID,
    delta: int,
    world_time_id: uuid.UUID,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> AdjustCharacterResourceResult:
    """The actual work of `adjust_character_resource()`, on a connection
    the caller already has open.

    `resource_definition_id`, never a bare code: `rules.
    resource_definitions.code` is unique only *per `ruleset_version_id`*
    (`ux_resource_definitions_ruleset_version_code`), not globally, the
    same reasoning `_apply_character_condition_impl`'s own docstring gives
    for `condition_id`.

    Raises `CharacterResourceNotTrackedError` when `character_id` has no
    existing `campaign.character_resources` row for
    `resource_definition_id` — see that error's own docstring for why
    there is no default this command could fall back to creating.

    `delta` may be positive (a resource restored — a long rest, a
    recharge) or negative (a resource spent); this module has no separate
    "use"/"restore" command, the same single-code reasoning as
    `adjust_hit_points`. The resulting `current_amount` is *not* clamped
    here — `campaign.character_resources`' own `ck_character_resources_
    current_within_max` CHECK and `core.nonnegative_integer` domain
    already reject an out-of-range result at the database level, mapped
    to a clean 400 by the existing generic `IntegrityError` handler (see
    this module's own docstring); a silently-clamping command would hide
    a caller's own arithmetic mistake (e.g. spending more of a resource
    than was actually available) instead of surfacing it."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

    world_id = _world_id_for_timeline(connection, timeline_id=timeline_id)
    _assert_character_in_world(connection, character_id=character_id, world_id=world_id)

    row = (
        connection.execute(
            text("""
                SELECT current_amount FROM campaign.character_resources
                WHERE timeline_id = :timeline AND character_id = :character
                  AND resource_definition_id = :resource
                FOR UPDATE
            """),
            {
                "timeline": timeline_id,
                "character": character_id,
                "resource": resource_definition_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CharacterResourceNotTrackedError(
            f"character {character_id} has no tracked resource {resource_definition_id} "
            f"on timeline {timeline_id}"
        )
    previous_amount = row["current_amount"]
    new_amount = previous_amount + delta

    if new_amount == previous_amount:
        return AdjustCharacterResourceResult(
            event_id=None,
            previous_amount=previous_amount,
            new_amount=new_amount,
            changed=False,
        )

    event_id = _insert_event_row(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="resource_adjusted",
        name="Character resource adjusted",
        details=details,
        campaign_id=campaign_id,
        session_id=session_id,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )

    connection.execute(
        text("""
            UPDATE campaign.character_resources
            SET current_amount = :amount, last_event_id = :event, updated_at = now()
            WHERE timeline_id = :timeline AND character_id = :character
              AND resource_definition_id = :resource
        """),
        {
            "amount": new_amount,
            "event": event_id,
            "timeline": timeline_id,
            "character": character_id,
            "resource": resource_definition_id,
        },
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:event, :character, 'current_amount', :previous, :new, :world_time)
        """),
        {
            "event": event_id,
            "character": character_id,
            "previous": json.dumps(previous_amount),
            "new": json.dumps(new_amount),
            "world_time": world_time_id,
        },
    )

    return AdjustCharacterResourceResult(
        event_id=event_id,
        previous_amount=previous_amount,
        new_amount=new_amount,
        changed=True,
    )


def adjust_character_resource(
    engine: Engine,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    resource_definition_id: uuid.UUID,
    delta: int,
    world_time_id: uuid.UUID,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> AdjustCharacterResourceResult:
    """Applies `delta` (positive to restore, negative to spend) to
    `character_id`'s `resource_definition_id` amount, recording the
    change as a narrative event. Public convenience API: opens and
    commits its own transaction. See `_adjust_character_resource_impl()`
    for the composable form a caller with its own transaction uses
    instead."""
    with engine.begin() as connection:
        return _adjust_character_resource_impl(
            connection,
            timeline_id=timeline_id,
            character_id=character_id,
            resource_definition_id=resource_definition_id,
            delta=delta,
            world_time_id=world_time_id,
            campaign_id=campaign_id,
            session_id=session_id,
            details=details,
        )
