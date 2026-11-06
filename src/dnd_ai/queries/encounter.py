"""Audience-filtered effective encounter query.

`narrative.encounters`/`.encounter_participants`/`.encounter_rounds`/
`.encounter_turns` and `interaction.combat_actions` together are already
the current, timeline-scoped record of a combat encounter — unlike every
other domain this package queries, there is no separate "definition versus
state" split here (docs/architecture/DATABASE_MODEL.md §13: "the database
captures synchronized state and meaningful outcomes rather than
duplicating every tactical decision"), so this module reassembles one
encounter's full history directly rather than layering a definition query
over a state query.

Audience filtering: a resolved round, turn and combat action is the
witnessed outcome of the fight, but the record around it is not uniformly
visible. ADR 0016 classifies `narrative.encounters.summary` and
`narrative.encounter_turns.notes` GM_ONLY; a `pending` encounter is unstarted
GM preparation; and every participant, location, event and item reference is
an entity id the caller may not be allowed to discover. Callers holding
`canon.edit` pass no `audience` and get the full record. Any other campaign
member passes an `EncounterAudience` and gets a projection computed here,
inside the read-model boundary, so a hidden row, id or count never reaches
the API layer: see `get_encounter_view`.

Cross-campaign ownership: `narrative.encounters.campaign_id` is a direct
column (unlike the world-scoped domains `dnd_ai.queries.dungeon`/
`.character`/`.quest`/`.relationship` query, which have no `campaign_id`
column at all) — this module reuses `dnd_ai.commands.encounters.
EncounterNotFoundError` directly rather than defining a duplicate, since
both raise the identical fixed, non-disclosing 404 for the identical
"doesn't exist or belongs to a different campaign" case.
"""

import uuid
from dataclasses import dataclass, replace

from sqlalchemy import Connection, text

from dnd_ai.commands.encounters import EncounterNotFoundError

from .world_explorer import WorldEntityVisibility, discoverable_entity_ids

__all__ = [
    "EncounterAudience",
    "EncounterNotFoundError",
    "get_encounter_view",
    "member_may_read_encounter",
]


@dataclass(frozen=True)
class EncounterParticipantView:
    encounter_participant_id: uuid.UUID
    participant_entity_id: uuid.UUID
    side: str
    initiative: int | None
    outcome: str | None


@dataclass(frozen=True)
class CombatActionView:
    action_kind: str
    item_instance_id: uuid.UUID | None
    spell_id: uuid.UUID | None
    hit: bool | None
    damage_amount: int | None
    damage_type_code: str | None
    resulting_condition_code: str | None


@dataclass(frozen=True)
class EncounterTurnView:
    encounter_turn_id: uuid.UUID
    participant_id: uuid.UUID
    turn_order: int
    notes: str | None
    combat_action: CombatActionView | None


@dataclass(frozen=True)
class EncounterRoundView:
    encounter_round_id: uuid.UUID
    round_number: int
    turns: tuple[EncounterTurnView, ...]


@dataclass(frozen=True)
class EncounterView:
    encounter_id: uuid.UUID
    status: str
    current_round: int
    summary: str | None
    location_id: uuid.UUID | None
    world_time_id: uuid.UUID
    resulting_event_id: uuid.UUID | None
    participants: tuple[EncounterParticipantView, ...]
    rounds: tuple[EncounterRoundView, ...]


# Statuses a member without `canon.edit` may read. `pending` is unstarted GM
# preparation; `aborted` is readable only when it was started (see
# `member_may_read_encounter`).
_MEMBER_READABLE_STATUSES = frozenset({"active", "completed"})


@dataclass(frozen=True)
class EncounterAudience:
    """Who a member-safe encounter is for: the World Explorer's resolved
    discoverability bundle plus the caller's validated world and timeline."""

    visibility: WorldEntityVisibility
    world_id: uuid.UUID
    timeline_id: uuid.UUID


def member_may_read_encounter(status: str, resulting_event_id: uuid.UUID | None) -> bool:
    """The member (non-`canon.edit`) read rule, shared with
    `dnd_ai.queries.character.get_character_view`'s `active_encounter_id` so the
    two surfaces cannot drift. `aborted` records an event only when the encounter was `active`
    (`commands.encounter_operations.abort_encounter`; no other writer sets the
    status), so an aborted row with no `resulting_event_id` never started. The
    column is `ON DELETE SET NULL`, so a started encounter whose abort event
    was physically removed also reads as unstarted: that fails closed."""
    return status in _MEMBER_READABLE_STATUSES or (
        status == "aborted" and resulting_event_id is not None
    )


def get_encounter_view(
    connection: Connection,
    *,
    encounter_id: uuid.UUID,
    campaign_id: uuid.UUID,
    audience: EncounterAudience | None = None,
) -> EncounterView:
    """The current record of one encounter: its participants and every
    round/turn/combat action so far. Raises `EncounterNotFoundError` for a
    nonexistent encounter or one belonging to a different campaign than
    `campaign_id` (always the URL's own already-authorized campaign) —
    identically, so a caller can never distinguish the two.

    With no `audience` this is the unfiltered view, for `canon.edit` holders
    only (the route decides). With an `audience` (a member without
    `canon.edit`):

    - a `pending` encounter, or one aborted before it started, raises the same
      `EncounterNotFoundError`;
    - `summary` and every turn's `notes` (GM_ONLY) are `None`;
    - only participants whose entity the audience may discover are returned,
      and only the turns they took, with `turn_order` re-ranked densely per
      round in the established order so gaps cannot reveal a hidden turn;
    - `location_id`, `resulting_event_id` and a combat action's
      `item_instance_id` are `None` unless discoverable.

    All candidate ids are checked with one `discoverable_entity_ids` call."""
    row = (
        connection.execute(
            text("""
                SELECT encounter_id, status, current_round, summary, location_id, world_time_id,
                       resulting_event_id
                FROM narrative.encounters
                WHERE encounter_id = :encounter AND campaign_id = :campaign
            """),
            {"encounter": encounter_id, "campaign": campaign_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise EncounterNotFoundError(
            f"encounter {encounter_id} does not exist in campaign {campaign_id}"
        )
    if audience is not None and not member_may_read_encounter(
        row["status"], row["resulting_event_id"]
    ):
        raise EncounterNotFoundError(
            f"encounter {encounter_id} does not exist in campaign {campaign_id}"
        )

    participant_rows = connection.execute(
        text("""
            SELECT encounter_participant_id, participant_entity_id, side, initiative, outcome
            FROM narrative.encounter_participants
            WHERE encounter_id = :encounter
            ORDER BY encounter_participant_id
        """),
        {"encounter": encounter_id},
    ).mappings()
    participants = tuple(
        EncounterParticipantView(
            encounter_participant_id=p["encounter_participant_id"],
            participant_entity_id=p["participant_entity_id"],
            side=p["side"],
            initiative=p["initiative"],
            outcome=p["outcome"],
        )
        for p in participant_rows
    )

    turn_rows = connection.execute(
        text("""
            SELECT t.encounter_round_id, t.encounter_turn_id, t.participant_id, t.turn_order,
                   t.notes,
                   ca.action_kind, ca.item_instance_id, ca.spell_id, ca.hit, ca.damage_amount,
                   dt.code AS damage_type_code, rc.code AS resulting_condition_code
            FROM narrative.encounter_turns t
            JOIN narrative.encounter_rounds r ON r.encounter_round_id = t.encounter_round_id
            LEFT JOIN interaction.combat_actions ca ON ca.combat_action_id = t.combat_action_id
            LEFT JOIN rules.damage_types dt ON dt.damage_type_id = ca.damage_type_id
            LEFT JOIN rules.conditions rc ON rc.condition_id = ca.resulting_condition_id
            WHERE r.encounter_id = :encounter
            ORDER BY t.turn_order
        """),
        {"encounter": encounter_id},
    ).mappings()
    turns_by_round: dict[uuid.UUID, list[EncounterTurnView]] = {}
    for t in turn_rows:
        combat_action = (
            None
            if t["action_kind"] is None
            else CombatActionView(
                action_kind=t["action_kind"],
                item_instance_id=t["item_instance_id"],
                spell_id=t["spell_id"],
                hit=t["hit"],
                damage_amount=t["damage_amount"],
                damage_type_code=t["damage_type_code"],
                resulting_condition_code=t["resulting_condition_code"],
            )
        )
        turns_by_round.setdefault(t["encounter_round_id"], []).append(
            EncounterTurnView(
                encounter_turn_id=t["encounter_turn_id"],
                participant_id=t["participant_id"],
                turn_order=t["turn_order"],
                notes=t["notes"],
                combat_action=combat_action,
            )
        )

    round_rows = connection.execute(
        text("""
            SELECT encounter_round_id, round_number
            FROM narrative.encounter_rounds
            WHERE encounter_id = :encounter
            ORDER BY round_number
        """),
        {"encounter": encounter_id},
    ).mappings()
    rounds = tuple(
        EncounterRoundView(
            encounter_round_id=r["encounter_round_id"],
            round_number=r["round_number"],
            turns=tuple(turns_by_round.get(r["encounter_round_id"], [])),
        )
        for r in round_rows
    )

    view = EncounterView(
        encounter_id=row["encounter_id"],
        status=row["status"],
        current_round=row["current_round"],
        summary=row["summary"],
        location_id=row["location_id"],
        world_time_id=row["world_time_id"],
        resulting_event_id=row["resulting_event_id"],
        participants=participants,
        rounds=rounds,
    )
    if audience is None:
        return view
    return _project_for_audience(connection, view, audience)


def _project_for_audience(
    connection: Connection, view: EncounterView, audience: EncounterAudience
) -> EncounterView:
    candidates = {p.participant_entity_id for p in view.participants}
    for reference in (view.location_id, view.resulting_event_id):
        if reference is not None:
            candidates.add(reference)
    for round_view in view.rounds:
        for turn in round_view.turns:
            if turn.combat_action is not None and turn.combat_action.item_instance_id is not None:
                candidates.add(turn.combat_action.item_instance_id)
    visible = discoverable_entity_ids(
        connection,
        sorted(candidates),
        world_id=audience.world_id,
        timeline_id=audience.timeline_id,
        visibility=audience.visibility,
    )

    participants = tuple(p for p in view.participants if p.participant_entity_id in visible)
    visible_participant_ids = {p.encounter_participant_id for p in participants}
    rounds = []
    for round_view in view.rounds:
        kept = sorted(
            (t for t in round_view.turns if t.participant_id in visible_participant_ids),
            key=lambda t: (t.turn_order, t.encounter_turn_id),
        )
        turns = tuple(
            replace(
                t,
                turn_order=rank,
                notes=None,
                combat_action=_project_combat_action(t.combat_action, visible),
            )
            for rank, t in enumerate(kept)
        )
        rounds.append(replace(round_view, turns=turns))
    return replace(
        view,
        summary=None,
        location_id=view.location_id if view.location_id in visible else None,
        resulting_event_id=view.resulting_event_id if view.resulting_event_id in visible else None,
        participants=participants,
        rounds=tuple(rounds),
    )


def _project_combat_action(
    action: CombatActionView | None, visible: frozenset[uuid.UUID]
) -> CombatActionView | None:
    if action is None or action.item_instance_id is None or action.item_instance_id in visible:
        return action
    return replace(action, item_instance_id=None)
