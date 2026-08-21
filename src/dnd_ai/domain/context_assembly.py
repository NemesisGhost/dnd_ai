"""Deterministic, audience-filtered context assembly for an NPC-conversation
agent invocation (docs/PLAN.md Phase 12, exit criteria: "The NPC receives
only permitted knowledge; party-private and character-private knowledge do
not leak," "Responses can reference current encounter, quest, and
relationship state").

`assemble_npc_conversation_context()` is the one function `dnd_ai.commands.
ai_npc.request_npc_conversation_turn` calls to build the payload recorded in
`ai.context_snapshots` and sent to the AI provider. It composes only
already-established, already-authorized query results and a small number of
narrowly scoped direct reads — it performs no authorization of its own
(the same "authorization happens at the API/access boundary" split every
`dnd_ai.queries.*` module already follows): `requesting_character_id`/
`requesting_party_id` must already be authorized (the caller's own resolved
character and `dnd_ai.api.access.resolve_party_perspective` result) by the
time they reach here.

The `revealable_knowledge` list is the mechanism that keeps an approved
`reveal_knowledge` proposal safe: it is the closed, pre-computed set of
`knowledge.knowledge_items` rows whose `subject_entity_id` is this NPC and
that `requesting_party_id` does **not** already know, per `campaign.
party_knowledge`. `dnd_ai.commands.ai_npc` only ever accepts a
`knowledge_item_id` from this set for a `reveal_knowledge` proposal — the
model is never free to name an arbitrary knowledge item, which is what
keeps "AI output cannot directly mutate canonical state" true even for an
auto-approved proposal: the *candidate set* itself is deterministic,
already-authored, database-computed, and audience-filtered before the model
ever sees it, not something the model's own text output could expand.

`advanceable_objectives` is the identical mechanism for the second proposal
kind, `advance_quest_objective`: the closed, pre-computed set of `narrative.
quest_objectives` this NPC's own related quests (`related_quests`) make
visible to `requesting_party_id`, whose current status is not already
terminal — see `AdvanceableObjective`'s own docstring for the full
membership rule. `dnd_ai.commands.ai_npc` only ever accepts a `quest_
objective_id` from this set, the same never-trust-the-model's-own-id
posture `reveal_knowledge_item_id` already established.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.queries.character import get_character_view
from dnd_ai.queries.quest import get_quest_view
from dnd_ai.queries.summary import get_campaign_summary_view

# Mirrors dnd_ai.commands.quests._TERMINAL_OBJECTIVE_STATUSES — that module
# is the actual enforcement (_advance_objective_impl re-checks this itself
# at apply time, regardless of what candidate set produced the proposal);
# this copy only decides which objectives are even *offered* as candidates
# here, so an NPC is never offered something the command would reject
# anyway. Duplicated rather than imported to keep this domain-layer module
# from depending on the application/command layer (SYSTEM_ARCHITECTURE.md
# §5's domain-below-application layering) for one small, stable, closed
# vocabulary — the seven campaign.objective_statuses codes are a fixed
# lookup set, not something expected to change independently in one copy
# and not the other.
_TERMINAL_OBJECTIVE_STATUSES = frozenset({"completed", "failed", "skipped", "superseded"})


@dataclass(frozen=True)
class RevealableKnowledge:
    knowledge_item_id: uuid.UUID
    statement: str
    sensitivity: str


@dataclass(frozen=True)
class RelatedQuest:
    quest_id: uuid.UUID
    name: str
    participant_role: str
    status_code: str


@dataclass(frozen=True)
class AdvanceableObjective:
    """One objective this NPC's conversation may propose completing or
    failing — the closed candidate set `advance_quest_objective` proposals
    draw from, the same role `RevealableKnowledge` plays for
    `reveal_knowledge`. Membership already proves every safety property the
    exit criteria require: it belongs to a quest this NPC participates in
    (`related_quests`' own scope), it is the requesting party's own
    effective view (`dnd_ai.queries.quest.get_quest_view`, party-scoped,
    `include_hidden=False` — so a `'gm_only'` objective, or one this party
    has no visibility into yet, can never appear here), and its current
    status is not already terminal — `dnd_ai.commands.ai_npc` only ever
    accepts a `quest_objective_id` from this set, never an arbitrary one the
    model names."""

    quest_objective_id: uuid.UUID
    quest_id: uuid.UUID
    name: str
    current_status_code: str | None


@dataclass(frozen=True)
class NpcConversationContext:
    npc_entity_id: uuid.UUID
    npc_name: str
    requesting_character_id: uuid.UUID
    requesting_character_name: str
    relationship_status_code: str | None
    affinity: int | None
    trust: int | None
    active_encounter_id: uuid.UUID | None
    known_facts_about_npc: tuple[str, ...]
    revealable_knowledge: tuple[RevealableKnowledge, ...]
    related_quests: tuple[RelatedQuest, ...]
    advanceable_objectives: tuple[AdvanceableObjective, ...]

    def as_prompt_payload(self) -> dict[str, Any]:
        """The exact structure persisted to `ai.context_snapshots.
        assembled_context` and sent to the AI provider — a plain, JSON-
        serializable dict, never the dataclass itself (JSONB storage,
        conventions §5.7)."""
        return {
            "npc": {"entity_id": str(self.npc_entity_id), "name": self.npc_name},
            "requesting_character": {
                "entity_id": str(self.requesting_character_id),
                "name": self.requesting_character_name,
            },
            "relationship": {
                "status": self.relationship_status_code,
                "affinity": self.affinity,
                "trust": self.trust,
            },
            "active_encounter_id": (
                str(self.active_encounter_id) if self.active_encounter_id is not None else None
            ),
            "known_facts_about_npc": list(self.known_facts_about_npc),
            "revealable_knowledge": [
                {"knowledge_item_id": str(k.knowledge_item_id), "statement": k.statement}
                for k in self.revealable_knowledge
            ],
            "related_quests": [
                {
                    "quest_id": str(q.quest_id),
                    "name": q.name,
                    "participant_role": q.participant_role,
                    "status": q.status_code,
                }
                for q in self.related_quests
            ],
            "advanceable_objectives": [
                {
                    "quest_objective_id": str(o.quest_objective_id),
                    "quest_id": str(o.quest_id),
                    "name": o.name,
                    "current_status": o.current_status_code,
                }
                for o in self.advanceable_objectives
            ],
        }


def _relationship_state(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    npc_entity_id: uuid.UUID,
    other_entity_id: uuid.UUID,
) -> tuple[str | None, int | None, int | None]:
    """The NPC's own perspective (`perspective_holder_entity_id =
    npc_entity_id`) on its relationship with `other_entity_id`, if a
    `world.relationships` row connects the two — deliberately a direct
    query rather than `dnd_ai.queries.relationship.get_relationship_view`,
    which is keyed by a known `relationship_id`; there is no existing
    by-participant-pair lookup to reuse. Returns `(None, None, None)` when
    no relationship (or no NPC-perspective state row) exists — a
    conversational NPC and a character with no established relationship is
    an ordinary, unremarkable case, not an error."""
    row = connection.execute(
        text("""
            SELECT rs.affinity, rs.trust, cs.code AS status_code
            FROM world.relationship_participants rp_npc
            JOIN world.relationship_participants rp_other
                ON rp_other.relationship_id = rp_npc.relationship_id
               AND rp_other.entity_id = :other
            JOIN campaign.relationship_state rs
                ON rs.relationship_id = rp_npc.relationship_id
               AND rs.timeline_id = :timeline
               AND rs.perspective_holder_entity_id = :npc
            JOIN campaign.relationship_statuses cs
                ON cs.relationship_status_id = rs.relationship_status_id
            WHERE rp_npc.entity_id = :npc
            ORDER BY rs.updated_at DESC
            LIMIT 1
        """),
        {"npc": npc_entity_id, "other": other_entity_id, "timeline": timeline_id},
    ).one_or_none()
    if row is None:
        return None, None, None
    return row.status_code, row.affinity, row.trust


def _known_facts_about_npc(
    connection: Connection, *, timeline_id: uuid.UUID, party_id: uuid.UUID, npc_entity_id: uuid.UUID
) -> tuple[str, ...]:
    """What `party_id` already believes about `npc_entity_id`
    (`campaign.party_knowledge`'s own current-belief statement, falling
    back to the item's canonical statement when the party's belief carries
    no recorded distortion — the same resolution `dnd_ai.queries.knowledge`
    already documents for its own single-item case)."""
    rows = connection.execute(
        text("""
            SELECT COALESCE(pk.interpretation, ki.canonical_statement) AS statement
            FROM campaign.party_knowledge pk
            JOIN knowledge.knowledge_items ki ON ki.knowledge_item_id = pk.knowledge_item_id
            WHERE pk.timeline_id = :timeline AND pk.party_id = :party
              AND ki.subject_entity_id = :npc
            ORDER BY pk.created_at
        """),
        {"timeline": timeline_id, "party": party_id, "npc": npc_entity_id},
    ).scalars()
    return tuple(rows)


def _revealable_knowledge(
    connection: Connection, *, timeline_id: uuid.UUID, party_id: uuid.UUID, npc_entity_id: uuid.UUID
) -> tuple[RevealableKnowledge, ...]:
    """Knowledge items about `npc_entity_id` that `party_id` does not yet
    know — the closed candidate set a `reveal_knowledge` proposal may draw
    from. See this module's own docstring for why this is the mechanism
    that keeps an AI-authored proposal safe."""
    rows = connection.execute(
        text("""
            SELECT ki.knowledge_item_id, ki.canonical_statement, ki.sensitivity
            FROM knowledge.knowledge_items ki
            WHERE ki.subject_entity_id = :npc
              AND NOT EXISTS (
                  SELECT 1 FROM campaign.party_knowledge pk
                  WHERE pk.timeline_id = :timeline AND pk.party_id = :party
                    AND pk.knowledge_item_id = ki.knowledge_item_id
              )
            ORDER BY ki.created_at
        """),
        {"npc": npc_entity_id, "timeline": timeline_id, "party": party_id},
    ).all()
    return tuple(
        RevealableKnowledge(
            knowledge_item_id=row.knowledge_item_id,
            statement=row.canonical_statement,
            sensitivity=row.sensitivity,
        )
        for row in rows
    )


def _related_quests(
    connection: Connection, *, timeline_id: uuid.UUID, party_id: uuid.UUID, npc_entity_id: uuid.UUID
) -> tuple[RelatedQuest, ...]:
    """Quests `npc_entity_id` participates in, with `party_id`'s own
    current status for each (`campaign.quest_state`, preferring a party-
    scoped row over a campaign/timeline-wide one when both exist) — the
    "responses can reference current ... quest ... state" exit criterion.
    Only the quest's own name and status are included, never per-
    objective detail: `narrative.quests` carries no visibility split of
    its own (unlike `narrative.quest_objectives.visibility_policy`), so
    surfacing anything more granular here would risk exposing GM-only
    objective content through an NPC's mouth."""
    rows = connection.execute(
        text("""
            SELECT DISTINCT ON (q.quest_id)
                q.quest_id, ce.canonical_name AS name, qp.participant_role, qs.code AS status_code
            FROM narrative.quest_participants qp
            JOIN narrative.quests q ON q.quest_id = qp.quest_id
            JOIN core.entities ce ON ce.entity_id = q.quest_id
            JOIN campaign.quest_state cqs
                ON cqs.quest_id = q.quest_id AND cqs.timeline_id = :timeline
               AND (cqs.party_id = :party OR cqs.party_id IS NULL)
            JOIN campaign.quest_statuses qs ON qs.quest_status_id = cqs.quest_status_id
            WHERE qp.participant_entity_id = :npc
            ORDER BY q.quest_id, cqs.party_id NULLS LAST
        """),
        {"npc": npc_entity_id, "timeline": timeline_id, "party": party_id},
    ).all()
    return tuple(
        RelatedQuest(
            quest_id=row.quest_id,
            name=row.name,
            participant_role=row.participant_role,
            status_code=row.status_code,
        )
        for row in rows
    )


def _advanceable_objectives(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    party_id: uuid.UUID,
    related_quests: tuple[RelatedQuest, ...],
) -> tuple[AdvanceableObjective, ...]:
    """Objectives eligible for an `advance_quest_objective` proposal, drawn
    only from quests this NPC already participates in (`related_quests`) —
    never a campaign-wide objective scan. For each such quest, reuses
    `dnd_ai.queries.quest.get_quest_view` (`include_hidden=False`, the same
    party-scoped, non-GM audience filter every other player-facing query in
    this codebase applies) rather than re-deriving visibility/status
    resolution here, so this candidate set can never drift from what that
    query already treats as "this party can see." An objective whose
    current effective status is already terminal (or would be excluded
    entirely by that query's own audience filter — `'gm_only'`, or a
    `'hidden_until_active'`/`'hidden_until_discovered'` objective with no
    state row yet) is never included."""
    candidates: list[AdvanceableObjective] = []
    for related in related_quests:
        quest_view = get_quest_view(
            connection,
            quest_id=related.quest_id,
            timeline_id=timeline_id,
            expected_world_id=expected_world_id,
            party_id=party_id,
            include_hidden=False,
        )
        for stage in quest_view.stages:
            for objective in stage.objectives:
                if objective.status_code in _TERMINAL_OBJECTIVE_STATUSES:
                    continue
                candidates.append(
                    AdvanceableObjective(
                        quest_objective_id=objective.quest_objective_id,
                        quest_id=related.quest_id,
                        name=objective.name,
                        current_status_code=objective.status_code,
                    )
                )
    return tuple(candidates)


def assemble_npc_conversation_context(
    connection: Connection,
    *,
    npc_entity_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    requesting_character_id: uuid.UUID,
    requesting_party_id: uuid.UUID,
) -> NpcConversationContext:
    """Assemble the full, audience-filtered context for one NPC-
    conversation turn. Raises whatever `get_character_view` raises
    (`CharacterNotFoundError`, a `DomainAuthorizationError`) for a
    nonexistent or cross-world `npc_entity_id`/`requesting_character_id` —
    the same fixed, non-disclosing contract every query in this codebase
    already uses."""
    npc = get_character_view(
        connection,
        character_id=npc_entity_id,
        timeline_id=timeline_id,
        expected_world_id=expected_world_id,
        include_full=True,
    )
    requester = get_character_view(
        connection,
        character_id=requesting_character_id,
        timeline_id=timeline_id,
        expected_world_id=expected_world_id,
        include_full=False,
    )
    status_code, affinity, trust = _relationship_state(
        connection,
        timeline_id=timeline_id,
        npc_entity_id=npc_entity_id,
        other_entity_id=requesting_character_id,
    )
    related_quests = _related_quests(
        connection,
        timeline_id=timeline_id,
        party_id=requesting_party_id,
        npc_entity_id=npc_entity_id,
    )
    return NpcConversationContext(
        npc_entity_id=npc_entity_id,
        npc_name=npc.name,
        requesting_character_id=requesting_character_id,
        requesting_character_name=requester.name,
        relationship_status_code=status_code,
        affinity=affinity,
        trust=trust,
        active_encounter_id=npc.active_encounter_id,
        known_facts_about_npc=_known_facts_about_npc(
            connection,
            timeline_id=timeline_id,
            party_id=requesting_party_id,
            npc_entity_id=npc_entity_id,
        ),
        revealable_knowledge=_revealable_knowledge(
            connection,
            timeline_id=timeline_id,
            party_id=requesting_party_id,
            npc_entity_id=npc_entity_id,
        ),
        related_quests=related_quests,
        advanceable_objectives=_advanceable_objectives(
            connection,
            timeline_id=timeline_id,
            expected_world_id=expected_world_id,
            party_id=requesting_party_id,
            related_quests=related_quests,
        ),
    )


# ---------------------------------------------------------------------------
# Audience-aware campaign synthesis (GM brief / player-character question /
# observer-safe summary) — `dnd_ai.commands.ai_synthesis.request_campaign_
# synthesis`, docs/PLAN.md Phase 12's exit criterion "the same question
# produces appropriately different GM, player-character, and observer
# answers from pre-filtered context, and inaccessible facts never enter the
# provider request."
#
# The three tiers differ in which *query path* assembles their context, not
# in a post-hoc filter over one shared payload — the same "fetch nothing
# rather than fetch-and-withhold" discipline `dnd_ai.queries.summary` and
# every other query module in this package already follow:
#   - gm_brief:          dnd_ai.queries.summary.get_campaign_summary_view
#                         with include_draft_events=True (only a caller who
#                         already holds canon.edit may request this tier —
#                         enforced by dnd_ai.api.ai_synthesis, not here).
#   - player_summary:    the same query with include_draft_events=False,
#                         plus requesting_party_id's own known-knowledge
#                         statements (campaign.party_knowledge) — requires an
#                         authorized character/party perspective
#                         (dnd_ai.api.access.resolve_party_perspective).
#   - observer_summary:  the same non-draft query only — no party-knowledge
#                         layer at all, regardless of what the caller
#                         supplies; see assemble_campaign_synthesis_context's
#                         own docstring.
# ---------------------------------------------------------------------------

GM_BRIEF = "gm_brief"
PLAYER_SUMMARY = "player_summary"
OBSERVER_SUMMARY = "observer_summary"
_AUDIENCE_TIERS = frozenset({GM_BRIEF, PLAYER_SUMMARY, OBSERVER_SUMMARY})


@dataclass(frozen=True)
class CampaignSynthesisContext:
    audience_tier: str
    current_session_title: str | None
    previous_session_recap: str | None
    recent_event_summaries: tuple[str, ...]
    party_known_facts: tuple[str, ...]

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "audience_tier": self.audience_tier,
            "current_session_title": self.current_session_title,
            "previous_session_recap": self.previous_session_recap,
            "recent_event_summaries": list(self.recent_event_summaries),
            "party_known_facts": list(self.party_known_facts),
        }


def _party_known_facts(
    connection: Connection, *, timeline_id: uuid.UUID, party_id: uuid.UUID, limit: int = 15
) -> tuple[str, ...]:
    """The party's own most recently acquired beliefs, campaign-wide — the
    general-purpose sibling of `_known_facts_about_npc`, with no
    `subject_entity_id` filter."""
    rows = connection.execute(
        text("""
            SELECT COALESCE(pk.interpretation, ki.canonical_statement) AS statement
            FROM campaign.party_knowledge pk
            JOIN knowledge.knowledge_items ki ON ki.knowledge_item_id = pk.knowledge_item_id
            WHERE pk.timeline_id = :timeline AND pk.party_id = :party
            ORDER BY pk.created_at DESC
            LIMIT :limit
        """),
        {"timeline": timeline_id, "party": party_id, "limit": limit},
    ).scalars()
    return tuple(rows)


def assemble_campaign_synthesis_context(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    audience_tier: str,
    timeline_id: uuid.UUID | None = None,
    requesting_party_id: uuid.UUID | None = None,
) -> CampaignSynthesisContext:
    """Assemble audience-filtered campaign context for one synthesis
    request. `audience_tier` must be one of `GM_BRIEF`/`PLAYER_SUMMARY`/
    `OBSERVER_SUMMARY`.

    This function performs no authorization of its own (matching every
    other function in this module) but it does enforce one structural
    safety rule directly, since violating it would mean an inaccessible
    fact reaching the provider request regardless of what the caller
    passes: `requesting_party_id` is only ever consulted for `PLAYER_
    SUMMARY` — for `GM_BRIEF` and `OBSERVER_SUMMARY` it is accepted but
    silently ignored, so a caller (or a future bug in `dnd_ai.api.ai_
    synthesis`) that passes a party id alongside `OBSERVER_SUMMARY` can
    never leak that party's own knowledge into an observer-tier answer."""
    if audience_tier not in _AUDIENCE_TIERS:
        raise ValueError(
            f"audience_tier must be one of {sorted(_AUDIENCE_TIERS)}, got {audience_tier!r}"
        )

    summary = get_campaign_summary_view(
        connection, campaign_id=campaign_id, include_draft_events=(audience_tier == GM_BRIEF)
    )

    party_known: tuple[str, ...] = ()
    if (
        audience_tier == PLAYER_SUMMARY
        and requesting_party_id is not None
        and timeline_id is not None
    ):
        party_known = _party_known_facts(
            connection, timeline_id=timeline_id, party_id=requesting_party_id
        )

    return CampaignSynthesisContext(
        audience_tier=audience_tier,
        current_session_title=(
            summary.current_session.title if summary.current_session is not None else None
        ),
        previous_session_recap=summary.previous_session_recap,
        recent_event_summaries=tuple(e.summary or e.name for e in summary.recent_events),
        party_known_facts=party_known,
    )
