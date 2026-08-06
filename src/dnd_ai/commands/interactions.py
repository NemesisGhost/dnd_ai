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
"""

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, text

from ._shared import lookup_id
from .events import EventParticipant, _insert_event_row


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
    target_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    check_request_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)


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
    with engine.begin() as connection:
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
        target_ids=tuple(target_ids),
        check_request_ids=tuple(check_request_ids),
    )


@dataclass(frozen=True)
class ResolveCheckResult:
    check_result_id: uuid.UUID
    event_id: uuid.UUID | None = None
    area_connection_opened: bool = False


@dataclass(frozen=True)
class _CheckContext:
    actor_entity_id: uuid.UUID
    interaction_id: uuid.UUID
    timeline_id: uuid.UUID
    world_time_id: uuid.UUID
    world_id: uuid.UUID
    campaign_id: uuid.UUID | None
    session_id: uuid.UUID | None
    target_area_connection_id: uuid.UUID | None


def _check_context(connection: Connection, check_request_id: uuid.UUID) -> _CheckContext:
    row = (
        connection.execute(
            text("""
            SELECT cr.actor_entity_id, i.interaction_id, i.timeline_id, i.world_time_id,
                   i.campaign_id, i.session_id, t.world_id, tgt.target_area_connection_id
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
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
        timeline_id=row["timeline_id"],
        world_time_id=row["world_time_id"],
        world_id=row["world_id"],
        campaign_id=row["campaign_id"],
        session_id=row["session_id"],
        target_area_connection_id=row["target_area_connection_id"],
    )


_TERMINAL_INTERACTION_STATUSES = frozenset({"resolved", "failed", "cancelled"})


def _interaction_id_for_check_request(
    connection: Connection, check_request_id: uuid.UUID
) -> uuid.UUID:
    interaction_id = connection.execute(
        text("""
            SELECT i.interaction_id
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            JOIN interaction.interactions i ON i.interaction_id = a.interaction_id
            WHERE cr.check_request_id = :check_request_id
        """),
        {"check_request_id": check_request_id},
    ).scalar()
    if interaction_id is None:
        raise ValueError(f"check request {check_request_id} does not exist")
    assert isinstance(interaction_id, uuid.UUID)
    return interaction_id


def _lock_interaction_for_resolution(connection: Connection, interaction_id: uuid.UUID) -> None:
    """Acquire an exclusive row lock on the parent interaction before any
    check result is recorded against it, so two resolve_check() calls
    against the same interaction (e.g. two of its check_requests resolving
    concurrently) serialize rather than both reading the same "not yet
    finished" state. Raises if the interaction has already reached a
    terminal status — a check cannot be resolved against an interaction
    that has already finished (interaction.enforce_check_result_interaction_
    open(), revision 070, enforces the same rule at the database level as a
    second, independent guard).
    """
    status = connection.execute(
        text("SELECT status FROM interaction.interactions WHERE interaction_id = :i FOR UPDATE"),
        {"i": interaction_id},
    ).scalar()
    if status in _TERMINAL_INTERACTION_STATUSES:
        raise ValueError(
            f"interaction {interaction_id} has status {status!r} and cannot accept another "
            "check resolution — resolved, failed, and cancelled interactions are terminal"
        )


def _interaction_check_completion(
    connection: Connection, interaction_id: uuid.UUID
) -> tuple[int, int]:
    """(total check requests, requests with a result) across every action the
    interaction has — not just the one check_request this resolve_check()
    call is resolving. perform_interaction() creates a single action today,
    but check_requests is action-scoped and DOMAIN_MODEL.md §16.2 allows a
    complex interaction several actions, so completion is interaction-wide.
    """
    total, resolved = connection.execute(
        text("""
            SELECT count(cr.check_request_id), count(res.check_result_id)
            FROM interaction.check_requests cr
            JOIN interaction.actions a ON a.action_id = cr.action_id
            LEFT JOIN interaction.check_results res ON res.check_request_id = cr.check_request_id
            WHERE a.interaction_id = :interaction
        """),
        {"interaction": interaction_id},
    ).one()
    assert isinstance(total, int)
    assert isinstance(resolved, int)
    return total, resolved


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


def _resolve_interaction(
    connection: Connection,
    *,
    interaction_id: uuid.UUID,
    event_id: uuid.UUID | None,
    description: str | None,
    is_final: bool,
) -> None:
    """Link this call's event (if any) to the interaction and, only once
    every check_request the interaction has has a result (is_final), move
    it to the terminal 'resolved' status. A complex interaction may have
    several check_requests (perform_interaction creates one today, but
    DOMAIN_MODEL.md §16.2 allows more per action, and resolve_check() may be
    called once per request) — the interaction must stay open until all of
    them have answered, and must only ever make the resolved transition
    once (interaction.enforce_interaction_status_irreversible(), revision
    070, additionally guarantees it can never be undone).

    A failed or non-matching check still contributes no event — it simply
    has nothing to link and no consequence to record (SYSTEM_ARCHITECTURE.md
    §6) — but still counts toward completion.
    """
    if event_id is not None:
        connection.execute(
            text("""
                UPDATE interaction.interactions SET resulting_event_id = :event
                WHERE interaction_id = :interaction
            """),
            {"event": event_id, "interaction": interaction_id},
        )
        connection.execute(
            text("""
                INSERT INTO interaction.consequences
                    (interaction_id, consequence_type, status, resulting_event_id, description)
                VALUES (:interaction, 'state_change', 'resolved', :event, :description)
            """),
            {"interaction": interaction_id, "event": event_id, "description": description},
        )

    if is_final:
        connection.execute(
            text(
                "UPDATE interaction.interactions SET status = 'resolved' "
                "WHERE interaction_id = :interaction"
            ),
            {"interaction": interaction_id},
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
) -> ResolveCheckResult:
    """Record a check's outcome and, when it satisfies a conditional route's
    requirement (world.conditional_route_requirement_satisfied), record the
    resulting event and open the route atomically. A check with no
    conditional-route target, or one that doesn't satisfy the requirement,
    still records its result — it simply has no further reaction, per
    docs/architecture/SYSTEM_ARCHITECTURE.md §6 step 5 ("create events when
    the mutation is narratively significant"). The parent interaction moves
    to a terminal resolved state once every check_request it has has a
    result — never before, and never more than once (_resolve_interaction).

    The parent interaction is locked (_lock_interaction_for_resolution)
    before anything else happens: this both rejects resolving a check whose
    interaction has already reached a terminal status, and — since the lock
    is held until commit — serializes concurrent resolve_check() calls
    against the same interaction, so two of its check_requests resolving at
    once can't both miscount how many are still outstanding.

    Concurrent resolve_check() calls targeting the same conditional route
    are additionally serialized by _lock_area_connection: the second caller
    blocks until the first commits, then re-reads campaign.
    area_connection_state under that lock before deciding whether the route
    still needs opening — so a route two competing successful checks both
    satisfy is opened, and its event/effect recorded, exactly once. This
    matters even when both checks belong to the same interaction (locked
    above) and, unchanged, when they belong to two different interactions
    entirely (not covered by the interaction-level lock at all).
    """
    with engine.begin() as connection:
        interaction_id = _interaction_id_for_check_request(connection, check_request_id)
        _lock_interaction_for_resolution(connection, interaction_id)

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

        total_checks, resolved_checks = _interaction_check_completion(connection, interaction_id)
        _resolve_interaction(
            connection,
            interaction_id=interaction_id,
            event_id=event_id,
            is_final=resolved_checks >= total_checks,
            description=(
                f"Check satisfied area connection {target_area_connection_id}'s requirement; "
                "route opened."
                if area_connection_opened
                else None
            ),
        )

    return ResolveCheckResult(
        check_result_id=check_result_id,
        event_id=event_id,
        area_connection_opened=area_connection_opened,
    )
