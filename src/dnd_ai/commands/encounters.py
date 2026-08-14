"""StartEncounter, ResolveCombatTurn, and EndEncounter — the commands that
let a dungeon (or Foundry) combat session update persistent character and
world state (docs/PLAN.md Phase 9 exit criterion: "Foundry combat can update
persistent character and world state").

resolve_combat_turn mirrors dnd_ai.commands.relationships.
evolve_relationship_reaction's shape: lock a structural row that always
exists (narrative.encounters) before touching the round/turn rows, then
record the causing narrative.events row (citing the encounter via
narrative.event_causes.cause_encounter_id — revision 078), update
campaign.character_state to match, and link the two through a
narrative.event_effects row — all in one transaction. It builds its own
interaction.interactions/interaction.actions pair for the combat_action to
attach to, left at the default 'initiated' status: no check_requests are
created here, so the interaction-lifecycle locking revisions 067/070-072
added never engages, and there is no exit criterion requiring this
command to also close out the interaction's own lifecycle.

start_encounter validates session_id/campaign_id agreement in application
code (_validate_session_campaign) before inserting anything, closing out
with a fixed 404 (SessionNotInCampaignError) — see that function's own
docstring. Revision 081 adds the equivalent database-level guard as
defense in depth, extending narrative.enforce_encounter_world() the same
way narrative.events (revision 057) and interaction.interactions
(revision 061) already validate their own campaign_id/session_id chain.

resolve_combat_turn and end_encounter both require the encounter they
operate on to belong to the caller-supplied campaign_id, checked
atomically under _lock_encounter's own FOR UPDATE lock — never against an
earlier, separate, unlocked read, which narrative.encounters.campaign_id
being mutable would otherwise leave open to a same-timeline reparenting
race. See _lock_encounter's and EncounterNotFoundError's own docstrings
for the full account, including the deliberate campaign_id=None
"unscoped" mode dnd_ai.commands.integration.apply_foundry_combat_sync()
currently relies on.

That caller-supplied campaign_id is only ever an *assertion*, never the
value persisted on the interaction.interactions/narrative.events rows
these commands create — those are always attributed to the locked
encounter's own, actual campaign_id (_lock_encounter's return value,
LockedEncounter.campaign_id), regardless of whether an assertion was
made. This matters specifically for the unscoped mode: skipping the
ownership assertion (campaign_id=None) must not also discard a
campaign-owned encounter's real provenance onto NULL child rows — those
are two independent questions ("is the caller authorized against this
campaign" vs. "which campaign do the rows this call creates actually
belong to"), and Foundry not yet answering the first (Phase 11's job) is
no reason to get the second wrong today. See LockedEncounter's own
docstring for the full account.
"""

import json
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

from ._shared import SessionNotInCampaignError as SessionNotInCampaignError
from ._shared import lookup_id
from ._shared import validate_session_campaign as _validate_session_campaign
from .events import EventParticipant, _insert_event_row

# SessionNotInCampaignError and _validate_session_campaign moved to
# dnd_ai.commands._shared once dnd_ai.commands.items needed the identical
# check — re-exported/aliased here (rather than dropped) so existing
# imports of dnd_ai.commands.encounters.SessionNotInCampaignError and this
# module's own internal callers below keep working unchanged. See
# _shared.SessionNotInCampaignError/.validate_session_campaign for the
# full docstrings.


class EncounterNotFoundError(DomainAuthorizationError):
    """Raised by `_lock_encounter()` when the locked `encounter_id` does
    not exist, or — when `expected_campaign_id` was supplied — belongs to
    a different campaign than expected. Both cases raise this identical
    error: confirming that an encounter exists but belongs to a different
    campaign would itself disclose cross-campaign information to a caller
    only authorized for the campaign it expected
    (docs/architecture/DATABASE_MODEL.md §19.7), the same reasoning
    `SessionNotInCampaignError` already applies to `session_id`.

    This is also what closes the campaign-ownership TOCTOU a *separate*,
    earlier, unlocked "does this encounter belong to my campaign" read
    would otherwise leave open: `narrative.encounters.campaign_id` is
    mutable (deliberately — see revision 081's own reparenting analysis),
    so nothing stops a concurrent transaction from reparenting an
    encounter to a different campaign on the same timeline between an
    earlier check and a later mutation. Checking ownership against the
    *locked* row, in the same `SELECT ... FOR UPDATE` a reparenting
    `UPDATE` would also have to wait behind, means there is no window
    where a caller can observe one owner and mutate under another — see
    `_lock_encounter()`'s own docstring for the full account.

    Inherits `DomainAuthorizationError`'s fixed 404 contract; the actual
    `encounter_id` and expected/actual `campaign_id` are available only
    via `str(self)` for local/server-side debugging, never in
    `safe_message`."""


class EncounterNotActiveError(SafeMessageError):
    """Raised by `_lock_encounter()` when the encounter it just locked is
    not `'active'` — already `'completed'`/`'aborted'`, still `'pending'`,
    or (the concurrent case this exists for) completed by a second
    `end_encounter`/`resolve_combat_turn` call that was serialized behind
    the same `FOR UPDATE` lock and only proceeds once the first caller's
    transaction has committed and released it. A conflict, not a
    validation failure — the request was well-formed, but the encounter's
    own state has since moved on — so this maps to HTTP 409, not 400.
    `safe_message` is a fixed, generic string; the encounter's id and its
    actual status are never included (only available via `str(self)` for
    local/server-side debugging, per `SafeMessageError`'s own contract)."""

    safe_status_code = 409
    safe_error_code = "conflict"
    safe_message = "The encounter is not active."


@dataclass(frozen=True)
class LockedEncounter:
    """The `_lock_encounter()` result: what was actually true of the row it
    just locked, as distinct from what a caller asserted before locking it.

    `campaign_id` here is the encounter's own, authoritative, just-locked
    value — never the caller's `expected_campaign_id` argument. The two
    agree whenever `expected_campaign_id` was supplied (a mismatch raises
    `EncounterNotFoundError` before this is ever constructed), but when
    `expected_campaign_id=None` (the unscoped mode — see `_lock_encounter`'s
    own docstring) they are *not* the same thing: `campaign_id` on this
    result can still be a real, non-NULL campaign, even though no assertion
    was made against it. Every caller that persists a child row attributed
    to the encounter (an `interaction.interactions` row, a completion
    `narrative.events` row) must stamp that row's own `campaign_id` from
    *this* field, not from whatever `expected_campaign_id` it happened to
    pass in — otherwise an unscoped call (Foundry's current
    `apply_foundry_combat_sync`) would silently discard a campaign-owned
    encounter's real provenance onto NULL child rows, rather than merely
    skipping the ownership assertion it was never meant to make."""

    timeline_id: uuid.UUID
    campaign_id: uuid.UUID | None


@dataclass(frozen=True)
class StartEncounterResult:
    encounter_id: uuid.UUID


@dataclass(frozen=True)
class ResolveCombatTurnResult:
    encounter_turn_id: uuid.UUID
    combat_action_id: uuid.UUID
    event_id: uuid.UUID | None
    previous_hit_points: int | None
    new_hit_points: int | None


@dataclass(frozen=True)
class EndEncounterResult:
    event_id: uuid.UUID


def _start_encounter_impl(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    participant_entity_ids: tuple[uuid.UUID, ...],
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    summary: str | None = None,
) -> StartEncounterResult:
    """The actual work of start_encounter(), on a connection the caller
    already has open — see _resolve_combat_turn_impl's docstring for why
    this package splits each command into a composable, connection-taking
    implementation and a public engine-based convenience wrapper (below).
    A caller that owns the surrounding transaction itself (e.g. the API
    layer's per-request connection) calls this directly.

    Validates session_id/campaign_id agreement (_validate_session_campaign)
    before inserting anything — see that function's own docstring."""
    _validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

    encounter_id = connection.execute(
        text("""
            INSERT INTO narrative.encounters
                (timeline_id, campaign_id, session_id, location_id, world_time_id, status,
                 summary)
            VALUES (:timeline, :campaign, :session, :location, :world_time, 'active', :summary)
            RETURNING encounter_id
        """),
        {
            "timeline": timeline_id,
            "campaign": campaign_id,
            "session": session_id,
            "location": location_id,
            "world_time": world_time_id,
            "summary": summary,
        },
    ).scalar()
    assert isinstance(encounter_id, uuid.UUID)

    for participant_entity_id in participant_entity_ids:
        connection.execute(
            text("""
                INSERT INTO narrative.encounter_participants
                    (encounter_id, participant_entity_id)
                VALUES (:encounter, :participant)
            """),
            {"encounter": encounter_id, "participant": participant_entity_id},
        )

    return StartEncounterResult(encounter_id=encounter_id)


def start_encounter(
    engine: Engine,
    *,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    participant_entity_ids: tuple[uuid.UUID, ...],
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    summary: str | None = None,
) -> StartEncounterResult:
    """Create an encounter and its initial participants, atomically. Public
    convenience API: opens and commits its own transaction. See
    _start_encounter_impl() for the composable form a caller with its own
    transaction (e.g. an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _start_encounter_impl(
            connection,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            participant_entity_ids=participant_entity_ids,
            campaign_id=campaign_id,
            session_id=session_id,
            location_id=location_id,
            summary=summary,
        )


def _lock_encounter(
    connection: Connection,
    encounter_id: uuid.UUID,
    *,
    expected_campaign_id: uuid.UUID | None = None,
) -> LockedEncounter:
    """Acquire an exclusive row lock on the encounter (a structural row
    that always exists), atomically verify campaign ownership when
    `expected_campaign_id` is supplied, and return a `LockedEncounter`
    carrying the locked row's real `timeline_id` and `campaign_id`. Every
    mutating caller (`_resolve_combat_turn_impl`, `_end_encounter_impl`)
    calls this before touching any other row.

    `expected_campaign_id` is an assertion, not a value to persist:
    it says "reject unless the encounter belongs to this campaign," never
    "attribute the rows this call creates to this campaign." Every caller
    that stamps `campaign_id` onto a child row it creates (an
    `interaction.interactions` row, a completion `narrative.events` row)
    must use the returned `LockedEncounter.campaign_id` — the encounter's
    own, actual, just-locked value — for that, not the `expected_campaign_id`
    it happened to pass in here. The two agree whenever an assertion was
    made and passed; see `LockedEncounter`'s own docstring for why they
    must not be conflated in the `expected_campaign_id=None` case.

    Ownership check order matters and is deliberate: existence and
    campaign ownership are checked *first*, against the just-locked row,
    before the lifecycle (`status`) check below, and long before any
    session-scope validation or mutation a caller performs afterward. A
    caller must never learn an encounter's lifecycle state, or have any
    side effect occur, for an encounter it is not authorized to touch.

    `expected_campaign_id` is checked against the row this `SELECT ... FOR
    UPDATE` itself locks, not against an earlier, separate, unlocked read
    — this is what closes the campaign-ownership TOCTOU an earlier check
    (e.g. an API layer's own prior "does this encounter belong to my
    campaign" query, run *before* this lock) would otherwise leave open:
    `narrative.encounters.campaign_id` is mutable (deliberately — revision
    081's own reparenting analysis explains why no immutability guard was
    added), so nothing would stop a concurrent transaction from
    reparenting the encounter to a different campaign on the same
    timeline between that earlier read and a later mutation. A concurrent
    `UPDATE narrative.encounters SET campaign_id = ...` for this same row
    needs the identical row lock this `SELECT ... FOR UPDATE` holds, so
    the two can never interleave: whichever reaches this row first — this
    lock, or a reparenting `UPDATE` — the other blocks until the first
    commits, and only then proceeds against the row's *true*, current,
    fully-committed `campaign_id`. There is no window in which this check
    can observe a stale owner.

    `expected_campaign_id=None` is a deliberate "unscoped" mode, not an
    oversight: `dnd_ai.commands.integration.apply_foundry_combat_sync()`
    is the one current caller that needs it, since Phase 9's `integration.*`
    schema scopes an external system to a `world_id` only, never a
    campaign (docs/architecture/DATABASE_MODEL.md §19) — there is no
    authoritative campaign to check a Foundry-originated combat turn
    against yet. Phase 11 is where Foundry's own campaign-scoped
    authorization is wired up; see that function's own docstring.

    A nonexistent encounter and a campaign mismatch both raise the
    identical `EncounterNotFoundError` (a fixed, non-disclosing 404) — see
    that class's own docstring for why they must be indistinguishable.

    Only once ownership passes does this also check the locked row's own
    status: raises `EncounterNotActiveError` if it isn't `'active'` — every
    caller requires an active encounter, so this is enforced once, here,
    under the same lock rather than re-checked independently by each. This
    is also what makes a second, concurrent `end_encounter`/
    `resolve_combat_turn` call for the same encounter safe: `FOR UPDATE`
    serializes the two callers, so the second one only proceeds past this
    `SELECT` once the first has committed — at which point it observes the
    first caller's already-`'completed'` (or otherwise non-`'active'`)
    status and is rejected here, before touching any other row, rather
    than racing to insert a second completion event or overwrite
    `resulting_event_id`."""
    row = connection.execute(
        text(
            "SELECT timeline_id, status, campaign_id FROM narrative.encounters "
            "WHERE encounter_id = :e FOR UPDATE"
        ),
        {"e": encounter_id},
    ).first()
    if row is None:
        raise EncounterNotFoundError(f"encounter {encounter_id} does not exist")
    if expected_campaign_id is not None and row.campaign_id != expected_campaign_id:
        raise EncounterNotFoundError(
            f"encounter {encounter_id} belongs to campaign {row.campaign_id!r}, "
            f"not the expected campaign {expected_campaign_id!r}"
        )
    if row.status != "active":
        raise EncounterNotActiveError(
            f"encounter {encounter_id} is not active (status={row.status!r})"
        )
    assert isinstance(row.timeline_id, uuid.UUID)
    assert row.campaign_id is None or isinstance(row.campaign_id, uuid.UUID)
    return LockedEncounter(timeline_id=row.timeline_id, campaign_id=row.campaign_id)


def _get_or_create_round(
    connection: Connection, *, encounter_id: uuid.UUID, round_number: int
) -> uuid.UUID:
    round_id = connection.execute(
        text("""
            SELECT encounter_round_id FROM narrative.encounter_rounds
            WHERE encounter_id = :encounter AND round_number = :round
            FOR UPDATE
        """),
        {"encounter": encounter_id, "round": round_number},
    ).scalar()
    if round_id is not None:
        assert isinstance(round_id, uuid.UUID)
        return round_id

    round_id = connection.execute(
        text("""
            INSERT INTO narrative.encounter_rounds (encounter_id, round_number)
            VALUES (:encounter, :round)
            RETURNING encounter_round_id
        """),
        {"encounter": encounter_id, "round": round_number},
    ).scalar()
    assert isinstance(round_id, uuid.UUID)
    return round_id


def _participant_id(
    connection: Connection, *, encounter_id: uuid.UUID, participant_entity_id: uuid.UUID
) -> uuid.UUID:
    value = connection.execute(
        text("""
            SELECT encounter_participant_id FROM narrative.encounter_participants
            WHERE encounter_id = :encounter AND participant_entity_id = :entity
        """),
        {"encounter": encounter_id, "entity": participant_entity_id},
    ).scalar()
    if value is None:
        raise ValueError(
            f"entity {participant_entity_id} is not a participant in encounter {encounter_id}"
        )
    assert isinstance(value, uuid.UUID)
    return value


def _character_hit_points(
    connection: Connection, *, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> int | None:
    value = connection.execute(
        text("""
            SELECT current_hit_points FROM campaign.character_state
            WHERE timeline_id = :timeline AND character_id = :character
            FOR UPDATE
        """),
        {"timeline": timeline_id, "character": character_id},
    ).scalar()
    return value


def _resolve_combat_turn_impl(
    connection: Connection,
    *,
    encounter_id: uuid.UUID,
    round_number: int,
    turn_order: int,
    actor_entity_id: uuid.UUID,
    world_time_id: uuid.UUID,
    action_kind: str = "attack",
    target_entity_id: uuid.UUID | None = None,
    item_instance_id: uuid.UUID | None = None,
    spell_id: uuid.UUID | None = None,
    hit: bool | None = None,
    damage_amount: int | None = None,
    damage_type_id: uuid.UUID | None = None,
    resulting_condition_id: uuid.UUID | None = None,
    interaction_type_code: str = "attack",
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> ResolveCombatTurnResult:
    """The actual work of resolve_combat_turn(), on a connection the caller
    already has open — without opening or closing a transaction of its own,
    so a caller composing a larger atomic unit of work (e.g.
    dnd_ai.commands.integration.apply_foundry_combat_sync(), which must
    commit the combat mutation and its own completion bookkeeping together
    or not at all) can call this directly inside its own engine.begin(),
    the same _insert_event_row()-style composition pattern used throughout
    this package. resolve_combat_turn(), below, is the public convenience
    wrapper for a caller with no other work to combine it with.

    hit=False never applies damage or records an event, regardless of
    damage_amount; hit=None applies damage when damage_amount is positive
    (no hit/miss distinction reported). See the inline comment above the
    damage-application check for the full reasoning.

    campaign_id, when set, is only an *assertion*: it is required to match
    the locked encounter's own campaign_id (_lock_encounter's
    expected_campaign_id), and a mismatch (including a same-timeline
    reparenting race — see _lock_encounter's own docstring) raises
    EncounterNotFoundError before anything else runs. campaign_id=None
    (apply_foundry_combat_sync's current usage) skips only that assertion
    — see _lock_encounter's docstring for why that is deliberate, not an
    oversight. Either way, the interaction.interactions row and any
    resulting narrative.events row this call creates are attributed to the
    *locked* encounter's actual campaign_id (LockedEncounter.campaign_id),
    never to this campaign_id argument — an unscoped call still inherits
    a campaign-owned encounter's real provenance, it just doesn't assert
    one.

    Validates session_id against the locked encounter's actual campaign
    (_validate_session_campaign), immediately after locking the encounter,
    before _get_or_create_round's own possible INSERT or any other
    mutation. A supplied session_id is never accepted or rejected based on
    this call's own (possibly unscoped) campaign_id argument.

    session_id=None is left NULL on the interaction.interactions row this
    call creates — it is never inherited from the encounter's own
    session_id (the session it was started in). An encounter can span more
    than one campaign.sessions row over its lifetime (it is a narrative
    span, not a single sitting), so silently attributing every turn to the
    encounter's *starting* session would misattribute any turn actually
    played in a later session — the same reasoning narrative.events and
    interaction.interactions already apply by treating session_id as a
    fact about the specific row being created, never derived from a
    parent/causing row (dnd_ai.commands.events._insert_event_row's own
    session_id parameter behaves identically). A caller that wants a
    turn's session recorded must supply it explicitly.
    """
    locked = _lock_encounter(connection, encounter_id, expected_campaign_id=campaign_id)
    timeline_id = locked.timeline_id
    _validate_session_campaign(connection, campaign_id=locked.campaign_id, session_id=session_id)
    encounter_round_id = _get_or_create_round(
        connection, encounter_id=encounter_id, round_number=round_number
    )
    participant_id = _participant_id(
        connection, encounter_id=encounter_id, participant_entity_id=actor_entity_id
    )

    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": timeline_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)

    interaction_type_id = lookup_id(
        connection,
        "interaction",
        "interaction_types",
        "interaction_type_id",
        interaction_type_code,
    )
    interaction_id = connection.execute(
        text("""
            INSERT INTO interaction.interactions
                (timeline_id, campaign_id, session_id, interaction_type_id, world_time_id)
            VALUES (:timeline, :campaign, :session, :itype, :world_time)
            RETURNING interaction_id
        """),
        {
            "timeline": timeline_id,
            "campaign": locked.campaign_id,
            "session": session_id,
            "itype": interaction_type_id,
            "world_time": world_time_id,
        },
    ).scalar()
    assert isinstance(interaction_id, uuid.UUID)

    action_id = connection.execute(
        text("""
            INSERT INTO interaction.actions (interaction_id, actor_entity_id)
            VALUES (:interaction, :actor)
            RETURNING action_id
        """),
        {"interaction": interaction_id, "actor": actor_entity_id},
    ).scalar()
    assert isinstance(action_id, uuid.UUID)

    target_id = None
    if target_entity_id is not None:
        target_id = connection.execute(
            text("""
                INSERT INTO interaction.targets (action_id, target_entity_id)
                VALUES (:action, :entity)
                RETURNING target_id
            """),
            {"action": action_id, "entity": target_entity_id},
        ).scalar()
        assert isinstance(target_id, uuid.UUID)

    combat_action_id = connection.execute(
        text("""
            INSERT INTO interaction.combat_actions
                (action_id, target_id, action_kind, item_instance_id, spell_id, hit,
                 damage_amount, damage_type_id, resulting_condition_id)
            VALUES (:action, :target, :kind, :item, :spell, :hit, :damage, :damage_type,
                    :condition)
            RETURNING combat_action_id
        """),
        {
            "action": action_id,
            "target": target_id,
            "kind": action_kind,
            "item": item_instance_id,
            "spell": spell_id,
            "hit": hit,
            "damage": damage_amount,
            "damage_type": damage_type_id,
            "condition": resulting_condition_id,
        },
    ).scalar()
    assert isinstance(combat_action_id, uuid.UUID)

    encounter_turn_id = connection.execute(
        text("""
            INSERT INTO narrative.encounter_turns
                (encounter_round_id, participant_id, turn_order, combat_action_id)
            VALUES (:round, :participant, :order, :combat_action)
            RETURNING encounter_turn_id
        """),
        {
            "round": encounter_round_id,
            "participant": participant_id,
            "order": turn_order,
            "combat_action": combat_action_id,
        },
    ).scalar()
    assert isinstance(encounter_turn_id, uuid.UUID)

    # Not every attack roll needs a permanent world event
    # (docs/architecture/DATABASE_MODEL.md §12.3) — only promote to a
    # narrative.events row when there was actual persistent state to
    # change: real damage, against a target with an existing
    # campaign.character_state row on this timeline. A miss, a
    # non-damaging action, or damage against an entity with no tracked
    # HP (e.g. an untracked monster) leaves only the turn/combat_action
    # record behind.
    #
    # hit is the authority on whether the action connected: hit=False
    # never applies damage or records an event, even if a caller also
    # passed a positive damage_amount (a submitted-but-not-landed
    # damage roll) — damage_amount is still stored on combat_actions
    # above regardless, since it's useful payload/result data either
    # way. hit=None means the caller didn't report hit/miss at all
    # (not every combat source distinguishes the two); damage is
    # applied in that case if damage_amount is positive, preserving
    # this function's original behavior for callers with no hit/miss
    # concept — only hit=False is a hard stop.
    event_id: uuid.UUID | None = None
    previous_hit_points: int | None = None
    new_hit_points: int | None = None

    if (
        hit is not False
        and damage_amount is not None
        and damage_amount > 0
        and target_entity_id is not None
    ):
        previous_hit_points = _character_hit_points(
            connection, timeline_id=timeline_id, character_id=target_entity_id
        )

    if previous_hit_points is not None:
        assert target_entity_id is not None
        assert damage_amount is not None
        new_hit_points = previous_hit_points - damage_amount

        event_id = _insert_event_row(
            connection,
            world_id=world_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code="combat_damage_dealt",
            name="Combat damage dealt",
            details=event_details,
            campaign_id=locked.campaign_id,
            session_id=session_id,
            participants=(
                EventParticipant(entity_id=actor_entity_id, role_code="actor"),
                EventParticipant(entity_id=target_entity_id, role_code="victim"),
            ),
            cause_description=None,
        )
        connection.execute(
            text("""
                INSERT INTO narrative.event_causes (event_id, cause_encounter_id)
                VALUES (:event, :encounter)
            """),
            {"event": event_id, "encounter": encounter_id},
        )
        connection.execute(
            text("""
                UPDATE campaign.character_state
                SET current_hit_points = :hp, updated_at = now()
                WHERE timeline_id = :timeline AND character_id = :character
            """),
            {"hp": new_hit_points, "timeline": timeline_id, "character": target_entity_id},
        )
        connection.execute(
            text("""
                INSERT INTO narrative.event_effects
                    (event_id, target_entity_id, target_component, previous_value,
                     new_value, effective_world_time_id)
                VALUES (:event, :character, 'current_hit_points', :previous, :new,
                        :world_time)
            """),
            {
                "event": event_id,
                "character": target_entity_id,
                "previous": json.dumps(previous_hit_points),
                "new": json.dumps(new_hit_points),
                "world_time": world_time_id,
            },
        )

    return ResolveCombatTurnResult(
        encounter_turn_id=encounter_turn_id,
        combat_action_id=combat_action_id,
        event_id=event_id,
        previous_hit_points=previous_hit_points,
        new_hit_points=new_hit_points,
    )


def resolve_combat_turn(
    engine: Engine,
    *,
    encounter_id: uuid.UUID,
    round_number: int,
    turn_order: int,
    actor_entity_id: uuid.UUID,
    world_time_id: uuid.UUID,
    action_kind: str = "attack",
    target_entity_id: uuid.UUID | None = None,
    item_instance_id: uuid.UUID | None = None,
    spell_id: uuid.UUID | None = None,
    hit: bool | None = None,
    damage_amount: int | None = None,
    damage_type_id: uuid.UUID | None = None,
    resulting_condition_id: uuid.UUID | None = None,
    interaction_type_code: str = "attack",
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> ResolveCombatTurnResult:
    """Record one participant's turn — the interaction/action/combat_action
    it resolved via, and (when it dealt damage to a character with existing
    campaign.character_state on this timeline) the resulting HP change,
    with a causal narrative.events row citing the encounter — atomically.
    Public convenience API: opens and commits its own transaction. See
    _resolve_combat_turn_impl() for the composable form a caller with its
    own transaction (e.g. apply_foundry_combat_sync()) uses instead.
    """
    with engine.begin() as connection:
        return _resolve_combat_turn_impl(
            connection,
            encounter_id=encounter_id,
            round_number=round_number,
            turn_order=turn_order,
            actor_entity_id=actor_entity_id,
            world_time_id=world_time_id,
            action_kind=action_kind,
            target_entity_id=target_entity_id,
            item_instance_id=item_instance_id,
            spell_id=spell_id,
            hit=hit,
            damage_amount=damage_amount,
            damage_type_id=damage_type_id,
            resulting_condition_id=resulting_condition_id,
            interaction_type_code=interaction_type_code,
            campaign_id=campaign_id,
            session_id=session_id,
            event_details=event_details,
        )


def _validate_outcome_participants(
    connection: Connection,
    *,
    encounter_id: uuid.UUID,
    outcomes: tuple[tuple[uuid.UUID, str], ...],
) -> None:
    """Rejects an end_encounter() outcomes list before anything is mutated.

    Without this, the per-outcome UPDATE below (`WHERE encounter_id = ...
    AND participant_entity_id = ...`) silently matches zero rows for a
    participant_entity_id that isn't actually in the encounter, or for a
    later duplicate of one already applied — neither is a constraint
    violation Postgres would ever reject, so the encounter would still be
    marked completed, with a resulting_event_id, while the caller's
    outcome request was partly or entirely discarded without any error: a
    durable false success. Checked as one explicit, atomic precondition
    instead, entirely in Python against data already read (no per-outcome
    round trip), so a rejection here happens before the completion event,
    its event_causes row, the encounter's own status/resulting_event_id
    update, or any outcome UPDATE — nothing from a rejected request is
    left partially applied."""
    if not outcomes:
        return

    participant_entity_ids = [participant_entity_id for participant_entity_id, _ in outcomes]
    counts = Counter(participant_entity_ids)
    duplicates = {participant_entity_id for participant_entity_id, n in counts.items() if n > 1}
    if duplicates:
        raise ValueError(
            f"duplicate outcome participant_entity_id(s) {sorted(duplicates)} "
            f"for encounter {encounter_id}"
        )

    known_participant_ids = {
        row[0]
        for row in connection.execute(
            text(
                "SELECT participant_entity_id FROM narrative.encounter_participants "
                "WHERE encounter_id = :encounter"
            ),
            {"encounter": encounter_id},
        )
    }
    unknown = set(participant_entity_ids) - known_participant_ids
    if unknown:
        raise ValueError(
            f"outcome participant_entity_id(s) {sorted(unknown)} are not participants "
            f"in encounter {encounter_id}"
        )


def _end_encounter_impl(
    connection: Connection,
    *,
    encounter_id: uuid.UUID,
    world_time_id: uuid.UUID,
    outcomes: tuple[tuple[uuid.UUID, str], ...] = (),
    summary: str | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
) -> EndEncounterResult:
    """The actual work of end_encounter(), on a connection the caller
    already has open — see _resolve_combat_turn_impl's docstring for the
    composition pattern this mirrors, and for the campaign_id/
    expected_campaign_id contract (an assertion, checked but never
    persisted) this shares with it. The completion event's own campaign_id
    is always the locked encounter's actual campaign
    (LockedEncounter.campaign_id), not this call's campaign_id argument —
    an unscoped call (campaign_id=None) still attributes the completion
    event to a campaign-owned encounter's real campaign.

    Validates session_id against the locked encounter's actual campaign
    (_validate_session_campaign) immediately after locking the encounter,
    before _validate_outcome_participants or any mutation — session_id
    here lands on the completion event _insert_event_row() creates below,
    not on the encounter row itself. session_id=None is left NULL, never
    inherited from the encounter's own session_id — see
    _resolve_combat_turn_impl's docstring for the identical reasoning
    (an encounter can outlive the session it was started in, so the
    session an encounter actually *ended* in is a fact about the
    completion event, not something to infer from the encounter's start).
    """
    locked = _lock_encounter(connection, encounter_id, expected_campaign_id=campaign_id)
    timeline_id = locked.timeline_id
    _validate_session_campaign(connection, campaign_id=locked.campaign_id, session_id=session_id)
    _validate_outcome_participants(connection, encounter_id=encounter_id, outcomes=outcomes)

    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": timeline_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)

    event_id = _insert_event_row(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="other",
        name="Encounter ended",
        details=summary,
        campaign_id=locked.campaign_id,
        session_id=session_id,
    )
    connection.execute(
        text("""
            INSERT INTO narrative.event_causes (event_id, cause_encounter_id)
            VALUES (:event, :encounter)
        """),
        {"event": event_id, "encounter": encounter_id},
    )

    connection.execute(
        text("""
            UPDATE narrative.encounters
            SET status = 'completed', summary = COALESCE(:summary, summary),
                resulting_event_id = :event, updated_at = now()
            WHERE encounter_id = :encounter
        """),
        {"summary": summary, "event": event_id, "encounter": encounter_id},
    )

    for participant_entity_id, outcome in outcomes:
        connection.execute(
            text("""
                UPDATE narrative.encounter_participants
                SET outcome = :outcome, updated_at = now()
                WHERE encounter_id = :encounter AND participant_entity_id = :entity
            """),
            {"outcome": outcome, "encounter": encounter_id, "entity": participant_entity_id},
        )

    return EndEncounterResult(event_id=event_id)


def end_encounter(
    engine: Engine,
    *,
    encounter_id: uuid.UUID,
    world_time_id: uuid.UUID,
    outcomes: tuple[tuple[uuid.UUID, str], ...] = (),
    summary: str | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
) -> EndEncounterResult:
    """Mark an encounter completed, record each participant's outcome
    (defeated/escaped/surrendered/captured), and link the resulting event —
    atomically. Public convenience API: opens and commits its own
    transaction. See _end_encounter_impl() for the composable form a caller
    with its own transaction (e.g. an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _end_encounter_impl(
            connection,
            encounter_id=encounter_id,
            world_time_id=world_time_id,
            outcomes=outcomes,
            summary=summary,
            campaign_id=campaign_id,
            session_id=session_id,
        )
