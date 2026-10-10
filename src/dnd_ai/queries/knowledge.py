"""Audience-filtered effective knowledge query.

`knowledge.knowledge_items` records a claim — its canonical (ground-truth)
statement, truth status, and sensitivity; `campaign.party_knowledge`
records a party's own current effective belief about it on a timeline,
deliberately kept separate so a false belief is never silently overwritten
by the canonical truth (docs/architecture/DATABASE_MODEL.md §15). This
module resolves exactly the two audiences that split already implies:

- a caller holding `canon.edit` (a GM) sees the item's own ground truth —
  `canonical_statement`, `truth_status_code`, `sensitivity` — regardless
  of what any party currently believes;
- anyone else sees only their own authorized party's current belief
  (`campaign.party_knowledge`'s `awareness_level`/`confidence`/
  `willing_to_share`, and a `statement` resolved as that party's own
  `interpretation` when one is recorded, falling back to the item's
  `canonical_statement` when the party's belief carries no recorded
  distortion at all) — never the item's `truth_status`/`sensitivity`
  metadata, which describe the fact's own nature to the GM, not what the
  party perceives.

Per §15's own words ("A user may be allowed to inspect a claim because the
user's selected character knows it, because the user's party knows it,
because it is public, ... or because an explicit resource grant allows
it"), a non-GM caller is resolved through, in order: the selected
character's own `knowledge.entity_knowledge` belief, an authorized party's
`campaign.party_knowledge` belief (the explicit party filter, or the
character's eligible parties when none is chosen), then — when the caller
allows it — the public projection (`knowledge.public_knowledge`). A non-GM
with none of these for the item gets nothing: a belief row's existence is
itself the "does this audience know this at all" signal, and a knowledge
item's very existence can be sensitive (`sensitivity` up to
`'dangerous'`), so this module raises the same fixed, non-disclosing error
for "the item doesn't exist" and "this audience has no belief about it"
identically.

This module is framework-free and performs no authorization of its own:
`include_ground_truth` and `party_id` must already be authorized decisions
(a resolved `canon.edit` check and `dnd_ai.api.access.
resolve_party_perspective`, respectively) by the time they reach here —
the same "authorization happens at the API/access boundary, the query
only filters" split every other query module in this package follows.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError


class KnowledgeNotAuthorizedError(DomainAuthorizationError):
    """Raised by `get_knowledge_view()` for a nonexistent
    `knowledge_item_id`, one belonging to a different world than
    `expected_world_id`, or — for a non-GM caller — one the authorized
    party has no `campaign.party_knowledge` row for at all. All three
    raise this identically, so a caller can never learn which case
    applied: a knowledge item's own existence can itself be sensitive
    (`sensitivity` up to `'dangerous'`), so "exists but your party doesn't
    know it" must be indistinguishable from "doesn't exist." The supplied
    knowledge item/world ids are included only in the constructor's
    `detail` argument (`str(self)`), never in `safe_message`."""


@dataclass(frozen=True)
class KnowledgeView:
    knowledge_item_id: uuid.UUID
    knowledge_type_code: str
    statement: str
    # GM-only ground-truth fields — None for a non-GM caller.
    truth_status_code: str | None
    sensitivity: str | None
    # Party-perspective fields — None for a GM caller (who sees ground
    # truth instead, not any one party's belief).
    awareness_level: str | None
    confidence: int | None
    willing_to_share: bool | None
    # The claim's optional subject, unredacted — the API decides whether this
    # caller may be shown it (`dnd_ai.api.knowledge.resolve_subject_summaries`).
    subject_entity_id: uuid.UUID | None = None
    # The knowledge path that produced this view — the same vocabulary as the
    # list's `scope`: `canonical` (ground truth), `character` (the knower's own
    # record), `party` (an authorized party's record) or `public` (public lore,
    # no personal record at all).
    scope: str = "canonical"


def get_knowledge_view(
    connection: Connection,
    *,
    knowledge_item_id: uuid.UUID,
    timeline_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    party_id: uuid.UUID | None,
    include_ground_truth: bool,
    knower_entity_id: uuid.UUID | None = None,
    allow_public: bool = False,
    eligible_party_ids: tuple[uuid.UUID, ...] = (),
) -> KnowledgeView:
    """The effective view of one knowledge item: ground truth for a GM
    (`include_ground_truth=True`); otherwise the authorized
    `knower_entity_id`'s own `knowledge.entity_knowledge` belief when one is
    recorded, else the belief of the authorized `party_id` — or, with no
    party filter, of the lowest-`party_knowledge_id` row among
    `eligible_party_ids` — (`campaign.party_knowledge`), else (with
    `allow_public`) the public projection. That is the precedence
    `dnd_ai.queries.knowledge_browse` resolves for the list. Raises
    `KnowledgeNotAuthorizedError` for a nonexistent item, one in a
    different world than `expected_world_id` (always the caller's own
    resolved-timeline world — `dnd_ai.api._shared.timeline_world_id`, never
    caller-supplied), or — for a non-GM caller — one the authorized
    party/knower has no belief record for.

    `knower_entity_id` and `eligible_party_ids` must already be authorized
    decisions (the caller holds `character.view_knowledge` for the knower,
    and each party passes `dnd_ai.api.access.resolve_party_perspective`)
    exactly like `party_id` — this query performs no authorization of its
    own."""
    row = (
        connection.execute(
            text("""
                SELECT ki.knowledge_item_id, e.world_id, kt.code AS knowledge_type_code,
                       ki.canonical_statement, ts.code AS truth_status_code, ki.sensitivity,
                       ki.subject_entity_id
                FROM knowledge.knowledge_items ki
                JOIN core.entities e ON e.entity_id = ki.knowledge_item_id
                JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
                JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
                WHERE ki.knowledge_item_id = :item
            """),
            {"item": knowledge_item_id},
        )
        .mappings()
        .one_or_none()
    )

    if row is None or row["world_id"] != expected_world_id:
        raise KnowledgeNotAuthorizedError(
            f"knowledge item {knowledge_item_id} does not exist in world {expected_world_id} "
            f"(actual world: {row['world_id'] if row is not None else None})"
        )

    if include_ground_truth:
        return KnowledgeView(
            knowledge_item_id=row["knowledge_item_id"],
            knowledge_type_code=row["knowledge_type_code"],
            statement=row["canonical_statement"],
            truth_status_code=row["truth_status_code"],
            sensitivity=row["sensitivity"],
            awareness_level=None,
            confidence=None,
            willing_to_share=None,
            subject_entity_id=row["subject_entity_id"],
            scope="canonical",
        )

    party_ids = (party_id,) if party_id is not None else eligible_party_ids
    belief_row = None
    scope = "character"
    if knower_entity_id is not None:
        # The selected character's own belief is the most specific projection
        # and wins over any party's (the list's precedence, too).
        belief_row = (
            connection.execute(
                text("""
                    SELECT awareness_level, confidence, interpretation, willing_to_share
                    FROM knowledge.entity_knowledge
                    WHERE timeline_id = :timeline AND knower_entity_id = :knower
                      AND knowledge_item_id = :item
                """),
                {"timeline": timeline_id, "knower": knower_entity_id, "item": knowledge_item_id},
            )
            .mappings()
            .one_or_none()
        )
    if belief_row is None and party_ids:
        scope = "party"
        belief_row = (
            connection.execute(
                text("""
                    SELECT awareness_level, confidence, interpretation, willing_to_share
                    FROM campaign.party_knowledge
                    WHERE timeline_id = :timeline AND party_id = ANY(CAST(:parties AS uuid[]))
                      AND knowledge_item_id = :item
                    ORDER BY party_knowledge_id
                    LIMIT 1
                """),
                {"timeline": timeline_id, "parties": list(party_ids), "item": knowledge_item_id},
            )
            .mappings()
            .first()
        )

    if belief_row is None and allow_public:
        # Public lore fallback (Phase 13D Knowledge screen `public` view):
        # a knowledge item published within any location on this timeline
        # (`knowledge.public_knowledge`) is viewable by any `campaign.view`
        # caller — its canonical statement only, never the GM-only
        # `truth_status`/`sensitivity` metadata. This keeps the `public`
        # list and this detail route in agreement.
        # The representative row is the list's own (`knowledge_browse.
        # _PUBLIC_ITEMS_CTE`): public longest, earliest `known_since`, so the
        # awareness shown here is the awareness the list card shows.
        public_row = (
            connection.execute(
                text("""
                    SELECT pub.awareness_level
                    FROM knowledge.public_knowledge pub
                    LEFT JOIN core.world_times pwt
                           ON pwt.world_time_id = pub.known_since_world_time_id
                    WHERE pub.timeline_id = :timeline AND pub.knowledge_item_id = :item
                    ORDER BY pwt.sort_key ASC NULLS LAST, pub.public_knowledge_id
                    LIMIT 1
                """),
                {"timeline": timeline_id, "item": knowledge_item_id},
            )
            .mappings()
            .first()
        )
        if public_row is not None:
            # Public lore has no personal record: confidence and willingness to
            # share are never invented for it.
            return KnowledgeView(
                knowledge_item_id=row["knowledge_item_id"],
                knowledge_type_code=row["knowledge_type_code"],
                statement=row["canonical_statement"],
                truth_status_code=None,
                sensitivity=None,
                awareness_level=public_row["awareness_level"],
                confidence=None,
                willing_to_share=None,
                subject_entity_id=row["subject_entity_id"],
                scope="public",
            )

    if belief_row is None:
        raise KnowledgeNotAuthorizedError(
            f"no belief recorded for knowledge item {knowledge_item_id} on timeline "
            f"{timeline_id} (parties={party_ids}, knower={knower_entity_id})"
        )

    return KnowledgeView(
        knowledge_item_id=row["knowledge_item_id"],
        knowledge_type_code=row["knowledge_type_code"],
        statement=belief_row["interpretation"] or row["canonical_statement"],
        truth_status_code=None,
        sensitivity=None,
        awareness_level=belief_row["awareness_level"],
        confidence=belief_row["confidence"],
        willing_to_share=belief_row["willing_to_share"],
        subject_entity_id=row["subject_entity_id"],
        scope=scope,
    )
