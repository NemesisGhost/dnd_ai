"""Audience-filtered effective quest-progress query.

`narrative.quests`/`.quest_stages`/`.quest_objectives` describe what a
quest is; `campaign.quest_state`/`.objective_state` describe current
progress on a timeline, optionally scoped to one party (docs/architecture/
DATABASE_MODEL.md §14). This module reassembles those into one effective,
audience-filtered view, keyed by `narrative.quest_objectives.
visibility_policy` — the vocabulary revision 074 added for exactly this
purpose ('visible', 'hidden_until_active', 'hidden_until_discovered',
'gm_only'), documented there as "an inferred, illustrative vocabulary...
docs/PLAN.md does not enumerate policy values, only the concept."

Audience filtering: `include_hidden=True` (a caller holding `canon.edit` —
a GM) sees every objective regardless of `visibility_policy`. Otherwise:
`'visible'` is always included; `'gm_only'` is always excluded;
`'hidden_until_active'` and `'hidden_until_discovered'` are treated
identically for this first cut — included only once *some*
`campaign.objective_state` row exists for the objective (party-scoped or
campaign-wide), since both values equally imply "this objective's own
tracked history has begun," which a state row's mere existence already
proves regardless of *why* progress started. Distinguishing "became active"
from "was discovered via a specific `knowledge.knowledge_items` row" (the
way `dnd_ai.queries.dungeon` distinguishes discovery per structural child)
is deferred until a caller actually needs that finer distinction — not
invented speculatively here, consistent with this column's own "inferred,
illustrative" scope.

Party scope: `campaign.quest_state`/`.objective_state` each may carry both
a campaign-wide row (`party_id IS NULL`) and independent per-party rows at
once (docs/architecture/DATABASE_MODEL.md §14, migration 073's own partial
unique indexes). When a caller supplies `party_id`, its own row (if one
exists) is preferred over the campaign-wide row; `party_id=None` always
falls back to the campaign-wide row. Like `dnd_ai.queries.dungeon`, this
module performs no authorization of its own — `party_id` must already be
an authorized perspective (`dnd_ai.api.access.resolve_party_perspective`)
by the time it reaches here.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError


class QuestNotFoundError(DomainAuthorizationError):
    """Raised by `get_quest_view()` for a nonexistent `quest_id`, or one
    whose own world does not match the caller's `expected_world_id` —
    identically, so a caller can never distinguish "doesn't exist" from
    "belongs to a different world" (mirroring `dnd_ai.queries.dungeon.
    DungeonAreaNotFoundError`'s identical reasoning). The supplied
    quest/world ids are included only in the constructor's `detail`
    argument (`str(self)`), never in `safe_message`."""


@dataclass(frozen=True)
class QuestObjectiveView:
    quest_objective_id: uuid.UUID
    name: str
    description: str | None
    requirement_level: str
    completion_mode: str
    visibility_policy: str
    quantity_required: int | None
    status_code: str | None


@dataclass(frozen=True)
class QuestStageView:
    quest_stage_id: uuid.UUID
    name: str
    description: str | None
    sequence_number: int
    stage_type: str
    objectives: tuple[QuestObjectiveView, ...]


@dataclass(frozen=True)
class QuestView:
    quest_id: uuid.UUID
    name: str
    status_code: str | None
    stages: tuple[QuestStageView, ...]


def get_quest_view(
    connection: Connection,
    *,
    quest_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    party_id: uuid.UUID | None,
    include_hidden: bool,
) -> QuestView:
    """The effective, audience-filtered state of one quest: its stages and
    objectives, each with the applicable current status (the party-scoped
    row when `party_id` is supplied and one exists, otherwise the
    campaign-wide row). Raises `QuestNotFoundError` for a nonexistent quest
    or one belonging to a different world than `expected_world_id` (always
    the caller's own resolved-timeline world — `dnd_ai.api._shared.
    timeline_world_id`, never caller-supplied)."""
    quest_row = (
        connection.execute(
            text("""
                SELECT q.quest_id, e.world_id, e.canonical_name
                FROM narrative.quests q
                JOIN core.entities e ON e.entity_id = q.quest_id
                WHERE q.quest_id = :quest
            """),
            {"quest": quest_id},
        )
        .mappings()
        .one_or_none()
    )

    if quest_row is None or quest_row["world_id"] != expected_world_id:
        raise QuestNotFoundError(
            f"quest {quest_id} does not exist in world {expected_world_id} "
            f"(actual world: {quest_row['world_id'] if quest_row is not None else None})"
        )

    quest_status_row = (
        connection.execute(
            text("""
                SELECT qs_party.code AS party_status_code,
                       qs_campaign.code AS campaign_status_code
                FROM (SELECT 1) AS one_row
                LEFT JOIN campaign.quest_state qst_party
                       ON qst_party.timeline_id = :timeline AND qst_party.quest_id = :quest
                      AND qst_party.party_id = :party
                LEFT JOIN campaign.quest_statuses qs_party
                       ON qs_party.quest_status_id = qst_party.quest_status_id
                LEFT JOIN campaign.quest_state qst_campaign
                       ON qst_campaign.timeline_id = :timeline AND qst_campaign.quest_id = :quest
                      AND qst_campaign.party_id IS NULL
                LEFT JOIN campaign.quest_statuses qs_campaign
                       ON qs_campaign.quest_status_id = qst_campaign.quest_status_id
            """),
            {"timeline": timeline_id, "quest": quest_id, "party": party_id},
        )
        .mappings()
        .one()
    )
    quest_status_code = (
        quest_status_row["party_status_code"]
        if party_id is not None and quest_status_row["party_status_code"] is not None
        else quest_status_row["campaign_status_code"]
    )

    objective_rows = connection.execute(
        text("""
            SELECT qo.quest_objective_id, qo.quest_stage_id, qo.name, qo.description,
                   qo.requirement_level, qo.completion_mode, qo.visibility_policy,
                   qo.quantity_required,
                   os_party.code AS party_status_code,
                   os_campaign.code AS campaign_status_code,
                   (ost_party.objective_state_id IS NOT NULL
                    OR ost_campaign.objective_state_id IS NOT NULL) AS has_state
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            LEFT JOIN campaign.objective_state ost_party
                   ON ost_party.timeline_id = :timeline
                  AND ost_party.quest_objective_id = qo.quest_objective_id
                  AND ost_party.party_id = :party
            LEFT JOIN campaign.objective_statuses os_party
                   ON os_party.objective_status_id = ost_party.objective_status_id
            LEFT JOIN campaign.objective_state ost_campaign
                   ON ost_campaign.timeline_id = :timeline
                  AND ost_campaign.quest_objective_id = qo.quest_objective_id
                  AND ost_campaign.party_id IS NULL
            LEFT JOIN campaign.objective_statuses os_campaign
                   ON os_campaign.objective_status_id = ost_campaign.objective_status_id
            WHERE qs.quest_id = :quest
              AND (
                :include_hidden
                OR qo.visibility_policy = 'visible'
                OR (
                    qo.visibility_policy IN ('hidden_until_active', 'hidden_until_discovered')
                    AND (ost_party.objective_state_id IS NOT NULL
                         OR ost_campaign.objective_state_id IS NOT NULL)
                )
              )
            ORDER BY qo.quest_objective_id
        """),
        {
            "timeline": timeline_id,
            "quest": quest_id,
            "party": party_id,
            "include_hidden": include_hidden,
        },
    ).mappings()

    objectives_by_stage: dict[uuid.UUID, list[QuestObjectiveView]] = {}
    for obj_row in objective_rows:
        status_code = (
            obj_row["party_status_code"]
            if party_id is not None and obj_row["party_status_code"] is not None
            else obj_row["campaign_status_code"]
        )
        objectives_by_stage.setdefault(obj_row["quest_stage_id"], []).append(
            QuestObjectiveView(
                quest_objective_id=obj_row["quest_objective_id"],
                name=obj_row["name"],
                description=obj_row["description"],
                requirement_level=obj_row["requirement_level"],
                completion_mode=obj_row["completion_mode"],
                visibility_policy=obj_row["visibility_policy"],
                quantity_required=obj_row["quantity_required"],
                status_code=status_code,
            )
        )

    stage_rows = connection.execute(
        text("""
            SELECT quest_stage_id, name, description, sequence_number, stage_type
            FROM narrative.quest_stages
            WHERE quest_id = :quest
            ORDER BY sequence_number, quest_stage_id
        """),
        {"quest": quest_id},
    ).mappings()
    stages = tuple(
        QuestStageView(
            quest_stage_id=stage_row["quest_stage_id"],
            name=stage_row["name"],
            description=stage_row["description"],
            sequence_number=stage_row["sequence_number"],
            stage_type=stage_row["stage_type"],
            objectives=tuple(objectives_by_stage.get(stage_row["quest_stage_id"], [])),
        )
        for stage_row in stage_rows
    )

    return QuestView(
        quest_id=quest_row["quest_id"],
        name=quest_row["canonical_name"],
        status_code=quest_status_code,
        stages=stages,
    )


@dataclass(frozen=True)
class QuestListItemView:
    quest_id: uuid.UUID
    name: str
    status_code: str | None


def list_campaign_quests(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    party_id: uuid.UUID | None,
    include_all_parties: bool,
    denied_quest_ids: frozenset[uuid.UUID] = frozenset(),
) -> tuple[QuestListItemView, ...]:
    """Every quest currently tracked on `timeline_id` — i.e. one with at
    least one `campaign.quest_state` row there — most recently defined by
    `narrative.quests` itself carrying no `campaign_id` (world-scoped, like
    the dungeon/item/relationship domains; §14): a quest with no tracked
    state at all was never surfaced to this campaign in the first place, so
    it is not listed. `status_code` prefers `party_id`'s own row over the
    campaign-wide one when both exist, identically to `get_quest_view`'s
    own per-objective preference; a quest tracked *only* by some other
    party's independent row (no campaign-wide row, and not `party_id`'s own)
    resolves to `status_code=None` rather than being silently excluded —
    the caller learns the quest is tracked even without a resolvable status
    for their own perspective.

    `include_all_parties` (docs/PHASE13D_BACKEND_READINESS.md §5) decides
    which quests count as "tracked" in the first place:

    - `True` — a caller who sees canonical truth across every party (a GM,
      resolved via `AccessContext.has_capability("canon.edit")` with no
      resource target — the same baseline-only check `dnd_ai.api.summary`
      already uses for its own list-wide default) sees every quest with
      *any* `campaign.quest_state` row on this timeline, campaign-wide or
      scoped to any party — including a quest tracked exclusively through
      one party's own independent progress, with no campaign-wide row ever
      created (`docs/architecture/DATABASE_MODEL.md` §14: campaign-wide and
      per-party tracking are independent, neither implies the other).
      `party_id` is expected to be `None` in this case (mirroring
      `get_quest_endpoint`'s own "a GM never resolves a party perspective"
      rule), so status resolution still only ever prefers the campaign-wide
      row, never leaking one party's status into another party's absence of
      one.
    - `False` — a non-GM caller sees only campaign-wide-tracked quests plus
      any tracked exclusively through their own authorized `party_id` — a
      quest another party tracks independently, with no campaign-wide row,
      stays invisible to a caller not authorized for that party's own
      perspective. This preserves cross-party privacy: one party's private
      quest tracking is not disclosed to a different party's own member
      merely because both are `campaign.view` holders in the same campaign.

    `denied_quest_ids` (resolved by the caller from `AccessContext.
    resource_grant_targets("campaign.view", field_name="quest_id")`)
    excludes specific quests even from a caller who would otherwise see
    them under either rule above — a per-quest `campaign.view` deny
    overrides both the GM's canonical-truth visibility and the
    campaign-wide/own-party default, the same "deny overrides baseline"
    precedence every other resource-grant check in this codebase applies.
    There is no `allowed_quest_ids` counterpart: unlike a draft event
    (baseline visibility `False` for a non-GM), every quest's baseline
    listing visibility under the rule above is already `True` for any
    `campaign.view` caller, so there is no default-hidden state for an
    explicit allow to ever add back — the same reasoning `dnd_ai.queries.
    session.list_campaign_sessions` already documents for its own
    `denied_session_ids`-only contract.

    Unlike `get_quest_view`, this function needs no separate objective-
    level `include_hidden` parameter: `quest_id`/`name`/`status_code` are
    the same three fields `get_quest_endpoint` already returns
    unconditionally to any authorized caller at the top level of its own
    response (only per-objective `visibility_policy` is audience-split
    there) — so there is no baseline this list could leak beyond what the
    existing detail endpoint already discloses for the same quest, once
    `denied_quest_ids` is honored identically by both routes. This module
    is framework-free and performs no authorization of its own:
    `include_all_parties`, `party_id`, and `denied_quest_ids` must already
    be authorized/resolved decisions by the time they reach here, exactly
    like `get_quest_view`."""
    rows = connection.execute(
        text("""
            WITH tracked AS (
                SELECT DISTINCT quest_id
                FROM campaign.quest_state
                WHERE timeline_id = :timeline
                  AND (:include_all_parties OR party_id IS NULL OR party_id = :party)
                  AND NOT (quest_id = ANY(CAST(:denied AS uuid[])))
            )
            SELECT e.entity_id AS quest_id, e.canonical_name AS name,
                   COALESCE(qs_party.code, qs_campaign.code) AS status_code
            FROM tracked t
            JOIN core.entities e ON e.entity_id = t.quest_id
            LEFT JOIN campaign.quest_state qst_party
                   ON qst_party.timeline_id = :timeline AND qst_party.quest_id = t.quest_id
                  AND qst_party.party_id = :party
            LEFT JOIN campaign.quest_statuses qs_party
                   ON qs_party.quest_status_id = qst_party.quest_status_id
            LEFT JOIN campaign.quest_state qst_campaign
                   ON qst_campaign.timeline_id = :timeline AND qst_campaign.quest_id = t.quest_id
                  AND qst_campaign.party_id IS NULL
            LEFT JOIN campaign.quest_statuses qs_campaign
                   ON qs_campaign.quest_status_id = qst_campaign.quest_status_id
            ORDER BY e.canonical_name, e.entity_id
        """),
        {
            "timeline": timeline_id,
            "party": party_id,
            "include_all_parties": include_all_parties,
            "denied": list(denied_quest_ids),
        },
    ).mappings()
    return tuple(
        QuestListItemView(
            quest_id=row["quest_id"], name=row["name"], status_code=row["status_code"]
        )
        for row in rows
    )
