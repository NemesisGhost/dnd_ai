"""AdvanceObjective — the command that lets a dungeon event advance or fail a
quest objective, atomically (docs/PLAN.md Phase 7 exit criterion, CLAUDE.md
rule 6).

Mirrors dnd_ai.commands.interactions.resolve_check's shape: lock a
structural row that always exists (narrative.quest_objectives, the same
role world.area_connections plays for _lock_area_connection) before
touching the possibly-absent campaign.objective_state row, so two
concurrent advancements of the same objective serialize rather than race,
then record the causing narrative.events row, update campaign.
objective_state to match, and link the two through a narrative.
event_effects row — all in one transaction.

Split into a connection-taking `_advance_objective_impl` plus a thin
engine-based public wrapper — the same composition
`dnd_ai.commands.encounters`/`.items` use — so Phase 10's API layer
(`dnd_ai.api.quests`) can run this on the request's own transaction instead
of opening a second, nested one. `_advance_objective_impl` validates a
caller-supplied `session_id` against `campaign_id`
(`dnd_ai.commands._shared.validate_session_campaign`) before mutating
anything, the same guard `_start_encounter_impl`/`_transfer_item_
possession_impl` already apply — neither `narrative.quest_objectives` nor
`campaign.objective_state` carries a `campaign_id` column at all (both are
scoped by `timeline_id`, like the item domain), so this is the only place
a caller-supplied session/campaign mismatch would otherwise go unchecked.

It also validates a caller-supplied `party_id` against `campaign_id`
(`_validate_campaign_party`, from `dnd_ai.commands._shared`) before
mutating anything: `campaign.campaign_parties` (revision 010) only
enforces that a party and the campaigns using it agree on *world* — a
party belonging to the right world but a *different* campaign on the same
timeline passes that trigger cleanly, so nothing at the database layer
stops a caller from advancing an objective "for" a party that has nothing
to do with the campaign named in the request. `PartyNotInCampaignError`/
`_validate_campaign_party` originated here and moved to
`dnd_ai.commands._shared` once `dnd_ai.queries.dungeon` needed the
identical check (see that module's docstring and `_shared.
PartyNotInCampaignError`'s own docstring) — the same promote-on-second-use
history `SessionNotInCampaignError`/`validate_session_campaign` already
went through. Both names are re-exported here unchanged for backward
compatibility with existing imports/tests.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from ._shared import PartyNotInCampaignError as PartyNotInCampaignError
from ._shared import lookup_id
from ._shared import validate_campaign_party as _validate_campaign_party
from ._shared import validate_session_campaign as _validate_session_campaign
from .events import EventParticipant, _insert_event_row

_TERMINAL_OBJECTIVE_STATUSES = frozenset({"completed", "failed", "skipped", "superseded"})
_ADVANCEABLE_STATUSES = frozenset({"completed", "failed"})


@dataclass(frozen=True)
class AdvanceObjectiveResult:
    objective_state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status_code: str | None
    new_status_code: str
    world_id: uuid.UUID
    quest_id: uuid.UUID


@dataclass(frozen=True)
class _QuestObjectiveContext:
    """`_quest_objective_context()`'s result: the owning quest's world and
    the quest itself. `quest_id` doubles as the quest's `core.entities.
    entity_id` (class-table inheritance, CLAUDE.md rule 4) — `narrative.
    quest_objectives`/`.quest_stages` have no entity identity of their own,
    so a caller needing "the core.entities row this concerns" (e.g.
    `dnd_ai.api.quests`' `audit.change_log.entity_id`) uses this, never
    `quest_objective_id` itself."""

    world_id: uuid.UUID
    quest_id: uuid.UUID


def _quest_objective_context(
    connection: Connection, quest_objective_id: uuid.UUID
) -> _QuestObjectiveContext:
    row = connection.execute(
        text("""
            SELECT e.world_id, q.quest_id
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            JOIN narrative.quests q ON q.quest_id = qs.quest_id
            JOIN core.entities e ON e.entity_id = q.quest_id
            WHERE qo.quest_objective_id = :objective
        """),
        {"objective": quest_objective_id},
    ).one_or_none()
    if row is None:
        raise ValueError(f"quest objective {quest_objective_id} does not exist")
    assert isinstance(row.world_id, uuid.UUID)
    assert isinstance(row.quest_id, uuid.UUID)
    return _QuestObjectiveContext(world_id=row.world_id, quest_id=row.quest_id)


def _lock_quest_objective(connection: Connection, quest_objective_id: uuid.UUID) -> None:
    """Acquire an exclusive row lock on the objective itself (a structural
    row that always exists, unlike its possibly-absent campaign.
    objective_state row) before touching campaign.objective_state at all.

    _lock_objective_state's own SELECT ... FOR UPDATE has nothing to lock
    until a state row already exists, so on a first transition two
    concurrent advance_objective() calls for the same (timeline,
    objective[, party]) scope could both observe "no state yet" and race
    to INSERT into campaign.objective_state, colliding on
    ux_objective_state_timeline_objective_no_party/_party — the same class
    of gap Phase 6's correction pass (revision 067) found in
    resolve_check() and fixed with _lock_area_connection. Locking this
    always-present row first closes it here the same way."""
    connection.execute(
        text(
            "SELECT quest_objective_id FROM narrative.quest_objectives WHERE quest_objective_id = :o FOR UPDATE"
        ),
        {"o": quest_objective_id},
    )


def _lock_objective_state(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    party_id: uuid.UUID | None,
) -> tuple[uuid.UUID, str] | None:
    """Row-lock the current campaign.objective_state row for this
    (timeline, objective[, party]), if one exists. Only meaningful once
    _lock_quest_objective has already been called — see that function's
    docstring for why locking this row alone is not sufficient on a first
    transition."""
    row = connection.execute(
        text("""
            SELECT objective_state_id,
                   (SELECT code FROM campaign.objective_statuses
                    WHERE objective_status_id = os.objective_status_id) AS status_code
            FROM campaign.objective_state os
            WHERE os.timeline_id = :timeline AND os.quest_objective_id = :objective
              AND os.party_id IS NOT DISTINCT FROM :party
            FOR UPDATE
        """),
        {"timeline": timeline_id, "objective": quest_objective_id, "party": party_id},
    ).one_or_none()
    if row is None:
        return None
    objective_state_id, status_code = row
    assert isinstance(objective_state_id, uuid.UUID)
    assert isinstance(status_code, str)
    return objective_state_id, status_code


def _advance_objective_impl(
    connection: Connection,
    *,
    quest_objective_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    new_status_code: str,
    party_id: uuid.UUID | None = None,
    actor_entity_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> AdvanceObjectiveResult:
    """The actual work of advance_objective(), on a connection the caller
    already has open — see dnd_ai.commands.encounters._resolve_combat_turn_
    impl's docstring for the composable-implementation/public-wrapper
    pattern this mirrors. A caller that owns the surrounding transaction
    itself (e.g. the API layer's per-request connection) calls this
    directly.

    Record the narrative.events row that advances or fails a quest
    objective and update campaign.objective_state to match, atomically. Only
    'completed' and 'failed' are accepted — the only two transitions a
    dungeon event actually drives (docs/PLAN.md's exit criterion names
    "advance or fail"); other objective_status values (hidden, available,
    active, skipped, superseded) are administrative/GM-driven and have no
    causing event to record.

    Rejects advancing an objective whose current state is already terminal
    (completed, failed, skipped, superseded) — there is no application-level
    guard preventing this at the database level yet (unlike interaction.
    interactions' status irreversibility, Phase 6 revisions 070-072); this
    command enforces it itself as the one path that currently writes
    campaign.objective_state.

    Validates session_id/campaign_id agreement (_validate_session_campaign)
    and party_id/campaign_id agreement (_validate_campaign_party) before
    touching any row — campaign_id here is an ordinary caller-supplied
    assertion (there is no locked, authoritative row to derive it from,
    unlike _lock_encounter's LockedEncounter.campaign_id), matching how
    dnd_ai.commands.items' routes already treat it.
    """
    if new_status_code not in _ADVANCEABLE_STATUSES:
        raise ValueError(
            f"new_status_code must be one of {sorted(_ADVANCEABLE_STATUSES)}, got {new_status_code!r}"
        )

    _validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)
    _validate_campaign_party(connection, campaign_id=campaign_id, party_id=party_id)

    context = _quest_objective_context(connection, quest_objective_id)
    world_id = context.world_id
    _lock_quest_objective(connection, quest_objective_id)

    existing = _lock_objective_state(
        connection,
        timeline_id=timeline_id,
        quest_objective_id=quest_objective_id,
        party_id=party_id,
    )
    previous_status_code = existing[1] if existing is not None else None

    if previous_status_code in _TERMINAL_OBJECTIVE_STATUSES:
        raise ValueError(
            f"objective {quest_objective_id} has status {previous_status_code!r} and cannot "
            "be advanced further — completed, failed, skipped, and superseded are terminal"
        )

    event_type_code = (
        "objective_completed" if new_status_code == "completed" else "objective_failed"
    )
    event_id = _insert_event_row(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code=event_type_code,
        name=f"Quest objective {new_status_code}",
        details=event_details,
        campaign_id=campaign_id,
        session_id=session_id,
        participants=(
            (EventParticipant(entity_id=actor_entity_id, role_code="actor"),)
            if actor_entity_id is not None
            else ()
        ),
        cause_interaction_id=cause_interaction_id,
        cause_event_id=cause_event_id,
    )

    new_status_id = lookup_id(
        connection, "campaign", "objective_statuses", "objective_status_id", new_status_code
    )

    if existing is None:
        objective_state_id = connection.execute(
            text("""
                INSERT INTO campaign.objective_state
                    (timeline_id, quest_objective_id, party_id, objective_status_id, last_event_id)
                VALUES (:timeline, :objective, :party, :status, :event)
                RETURNING objective_state_id
            """),
            {
                "timeline": timeline_id,
                "objective": quest_objective_id,
                "party": party_id,
                "status": new_status_id,
                "event": event_id,
            },
        ).scalar()
        assert isinstance(objective_state_id, uuid.UUID)
    else:
        objective_state_id = existing[0]
        connection.execute(
            text("""
                UPDATE campaign.objective_state
                SET objective_status_id = :status, last_event_id = :event, updated_at = now()
                WHERE objective_state_id = :id
            """),
            {"status": new_status_id, "event": event_id, "id": objective_state_id},
        )

    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_quest_objective_id, target_component, previous_value,
                 new_value, effective_world_time_id)
            VALUES (:event, :objective, 'objective_status_id', :previous, :new, :world_time)
        """),
        {
            "event": event_id,
            "objective": quest_objective_id,
            "previous": json.dumps(previous_status_code),
            "new": json.dumps(new_status_code),
            "world_time": world_time_id,
        },
    )

    return AdvanceObjectiveResult(
        objective_state_id=objective_state_id,
        event_id=event_id,
        previous_status_code=previous_status_code,
        new_status_code=new_status_code,
        world_id=world_id,
        quest_id=context.quest_id,
    )


def advance_objective(
    engine: Engine,
    *,
    quest_objective_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    new_status_code: str,
    party_id: uuid.UUID | None = None,
    actor_entity_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> AdvanceObjectiveResult:
    """Advance or fail a quest objective, atomically. Public convenience
    API: opens and commits its own transaction. See
    _advance_objective_impl() for the composable form a caller with its own
    transaction (e.g. an API command endpoint) uses instead."""
    with engine.begin() as connection:
        return _advance_objective_impl(
            connection,
            quest_objective_id=quest_objective_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            new_status_code=new_status_code,
            party_id=party_id,
            actor_entity_id=actor_entity_id,
            campaign_id=campaign_id,
            session_id=session_id,
            cause_interaction_id=cause_interaction_id,
            cause_event_id=cause_event_id,
            event_details=event_details,
        )
