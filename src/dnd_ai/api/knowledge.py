"""Audience-filtered knowledge query endpoints.

`GET /campaigns/{campaign_id}/knowledge` (Phase 13D — new) is the
audience-filtered discovery/list side of the Knowledge screen
(docs/UI_DESIGN.md §5.6): given a `view` and an authorized perspective, it
returns the knowledge records the caller may see, cursor-paginated, with
enough per-record data to render a compact item and navigate to detail.
Visibility, the `view` vocabulary, ordering, and the GM-vs-perspective
split are all documented on `dnd_ai.queries.knowledge_browse`.

`GET /campaigns/{campaign_id}/knowledge/{knowledge_item_id}` is the
pre-existing single-item read (`dnd_ai.queries.knowledge.
get_knowledge_view`), unchanged for its existing GM / party-perspective
callers and extended (backward-compatibly) to also serve a
character-private lookup: a non-GM caller who supplies `character_id`
without `party_id` and holds `character.view_knowledge` for that character
gets that character's own `knowledge.entity_knowledge` belief — so the
`character_private` list and this route agree.

Authorization: every route requires `campaign.view`. Whether the caller
may *discover* an item is `campaign.view` (a targeted deny hides it from
list and detail alike); whether the caller may see an item's *canonical /
GM-only fields* is a separate, per-item `canon.edit` decision (baseline, or
a targeted allow, minus a targeted deny) — a `canon.edit` deny only strips
those fields, it never hides an item the caller could otherwise see
(`dnd_ai.queries.knowledge_browse` documents the split). Anyone without
ground truth for an item must prove an authorized party
(`dnd_ai.api.access.resolve_party_perspective`, `character.view_knowledge`
+ current party membership) or, for character-private, hold
`character.view_knowledge` for the named character. An omitted perspective
contributes no audience-specific records to a list page, or — for the
detail route — yields the identical fixed, non-disclosing 404 a nonexistent
item produces (a knowledge item's own existence can be sensitive). Public
knowledge (`knowledge.public_knowledge`) needs no perspective: the list
includes it in every view unless the caller passes `include_public=false`,
and the detail route falls back to it. The
list's `subject_entity_id`/`source_event_id`/`source_interaction_id` are
each returned only when the caller can independently discover that
resource (`_resolve_related_id_redaction`). List and detail both carry an
optional `subject` summary (name, category, type) for display and
navigation, returned only when the caller may open the subject itself —
`resolve_subject_summaries`, which also decides the list's
`subject_entity_id`. These are reads: no idempotency
key, no `audit.change_log` row, no mutation.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.entity_lifecycle import lifecycle_hidden_entity_ids
from dnd_ai.queries.knowledge import get_knowledge_view
from dnd_ai.queries.knowledge_authoring import knowledge_definition_states
from dnd_ai.queries.knowledge_browse import (
    KNOWLEDGE_VIEWS,
    KNOWN_KEYSET,
    RECENT_KEYSET,
    KnowledgeListItem,
    list_knowledge,
)
from dnd_ai.queries.quest import audience_tracked_quest_ids
from dnd_ai.queries.world_explorer import discoverable_entity_ids, world_category_for_type_code

from ._shared import timeline_world_id
from .access import (
    PartyPerspectiveNotAuthorizedError,
    require_campaign_capability,
    resolve_party_perspective,
)
from .deps import get_connection
from .errors import NotFoundError
from .pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CursorFieldType,
    build_page,
    decode_typed_cursor,
)
from .world_explorer import resolve_world_entity_visibility

router = APIRouter(tags=["knowledge"])

_KNOWLEDGE_VIEW_CAPABILITY = "campaign.view"
_KNOWLEDGE_GROUND_TRUTH_CAPABILITY = "canon.edit"
_CHARACTER_KNOWLEDGE_CAPABILITY = "character.view_knowledge"

KnowledgeView = Literal["known", "rumors", "party_shared", "character_private", "recent", "public"]

_MAX_QUERY_LEN = 200


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


SubjectCategory = Literal[
    "location", "character", "organization", "religion", "item", "event", "quest"
]


class KnowledgeSubjectResponse(BaseModel):
    """What a claim is *about*, returned only when this caller may open the
    subject itself (`resolve_subject_summaries`). `category` picks the
    destination route — a World Explorer category or `quest`;
    `entity_type_code` is the finer type for the label."""

    entity_id: uuid.UUID
    name: str
    category: SubjectCategory
    entity_type_code: str


class KnowledgeResponse(BaseModel):
    knowledge_item_id: uuid.UUID
    knowledge_type_code: str
    statement: str
    truth_status_code: str | None
    sensitivity: str | None
    awareness_level: str | None
    confidence: int | None
    willing_to_share: bool | None
    # The authorized subject summary, or `null` — for no subject and for one
    # this caller may not open alike (the two are indistinguishable).
    subject: KnowledgeSubjectResponse | None = None


class KnowledgeListItemResponse(BaseModel):
    knowledge_item_id: uuid.UUID
    knowledge_type_code: str
    statement: str
    truth_status_code: str | None
    sensitivity: str | None
    awareness_level: str | None
    confidence: int | None
    willing_to_share: bool | None
    scope: str
    discovery_world_time_id: uuid.UUID | None
    # `subject_entity_id` / `source_event_id` / `source_interaction_id` are
    # returned only when this caller can *independently* discover that
    # resource — the subject/source entity under the shared World Explorer
    # discoverability rule, the interaction only when it is on the caller's
    # own campaign timeline. Otherwise `null` (Issue 1 — returning the id is
    # a disclosure; the knowledge item itself stays visible either way).
    source_event_id: uuid.UUID | None
    source_interaction_id: uuid.UUID | None
    subject_entity_id: uuid.UUID | None
    # The same authorization decision as `subject_entity_id`, with the name
    # and category a card needs to label and link it (`KnowledgeResponse`).
    subject: KnowledgeSubjectResponse | None = None
    # Authoring state, present only for `canon.edit` holders (Phase 15.1).
    canon_status: str | None = None
    lifecycle_status: str | None = None


class KnowledgeListResponse(BaseModel):
    items: list[KnowledgeListItemResponse]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _denied_item_ids(access: AccessContext) -> frozenset[uuid.UUID]:
    """Items removed from the list entirely — a targeted `campaign.view`
    deny only. A targeted `canon.edit` deny is deliberately **not** folded
    in here: it strips an item's ground-truth fields (below), it does not
    hide an otherwise-visible item (Issue 4 — this route used to conflate
    the two, so a `canon.edit` deny made an item vanish from every caller's
    list, including a player whose party legitimately believes it, and
    disagreed with the detail route which never did this)."""
    view_denied, _ = access.resource_grant_targets(_KNOWLEDGE_VIEW_CAPABILITY, "knowledge_item_id")
    return view_denied


def _ground_truth_item_targets(
    access: AccessContext,
) -> tuple[frozenset[uuid.UUID], frozenset[uuid.UUID]]:
    """`(allowed, denied)` `knowledge_item_id` targets of a `canon.edit`
    resource grant — layered over baseline `canon.edit` per item exactly as
    `AccessContext.has_capability(..., knowledge_item_id=...)` does for the
    detail route, so list and detail agree on which items show ground truth.
    (`resource_grant_targets` itself returns `(denied, allowed)`; this flips
    to `(allowed, denied)` to match `list_knowledge`'s parameter order.)"""
    denied, allowed = access.resource_grant_targets(
        _KNOWLEDGE_GROUND_TRUTH_CAPABILITY, "knowledge_item_id"
    )
    return allowed, denied


def _subject_summaries(
    connection: Connection,
    subject_ids: set[uuid.UUID],
    *,
    discoverable_world_ids: frozenset[uuid.UUID],
    access: AccessContext,
    world_id: uuid.UUID,
    quest_party_id: uuid.UUID | None,
) -> dict[uuid.UUID, KnowledgeSubjectResponse]:
    """The summaries for those of `subject_ids` the caller may open, given
    the already-resolved World Explorer discoverable set. See
    `resolve_subject_summaries`. A fixed number of queries regardless of page
    size (one when no subject is a quest)."""
    if not subject_ids:
        return {}
    rows = connection.execute(
        text(
            "SELECT e.entity_id, e.canonical_name, et.code AS entity_type_code "
            "FROM core.entities e "
            "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
            "WHERE e.entity_id = ANY(CAST(:ids AS uuid[])) AND e.world_id = :world"
        ),
        {"ids": list(subject_ids), "world": world_id},
    ).mappings()
    summaries: dict[uuid.UUID, KnowledgeSubjectResponse] = {}
    quest_names: dict[uuid.UUID, str] = {}
    for row in rows:
        category = world_category_for_type_code(row["entity_type_code"])
        if category is not None:
            if row["entity_id"] in discoverable_world_ids:
                summaries[row["entity_id"]] = KnowledgeSubjectResponse(
                    entity_id=row["entity_id"],
                    name=row["canonical_name"],
                    category=cast(SubjectCategory, category),
                    entity_type_code=row["entity_type_code"],
                )
        elif row["entity_type_code"] == "quest":
            quest_names[row["entity_id"]] = row["canonical_name"]
        # Any other type has no detail route a subject could link to.

    if quest_names:
        # The quest detail route's own contract (`dnd_ai.api.quests.
        # resolve_quest_response`): no per-quest `campaign.view` deny, not
        # lifecycle-hidden by reference, and tracked on this timeline for
        # this audience — a GM any party's row, anyone else a campaign-wide
        # row or their own authorized party's.
        is_gm = access.has_capability(_KNOWLEDGE_GROUND_TRUTH_CAPABILITY)
        hidden = lifecycle_hidden_entity_ids(
            connection, world_id=world_id, mode="reference", can_edit_canon=is_gm
        )
        candidates = [
            quest_id
            for quest_id in quest_names
            if quest_id not in hidden
            and access.has_capability(_KNOWLEDGE_VIEW_CAPABILITY, quest_id=quest_id)
        ]
        for quest_id in audience_tracked_quest_ids(
            connection,
            candidates,
            timeline_id=access.timeline_id,
            world_id=world_id,
            party_id=None if is_gm else quest_party_id,
            include_all_parties=is_gm,
        ):
            summaries[quest_id] = KnowledgeSubjectResponse(
                entity_id=quest_id,
                name=quest_names[quest_id],
                category="quest",
                entity_type_code="quest",
            )
    return summaries


def resolve_subject_summaries(
    connection: Connection,
    subject_ids: set[uuid.UUID],
    *,
    access: AccessContext,
    world_id: uuid.UUID,
    quest_party_id: uuid.UUID | None,
) -> dict[uuid.UUID, KnowledgeSubjectResponse]:
    """`{subject_entity_id: summary}` for the subjects this caller may open
    — never for one they may not. Knowing a claim grants nothing about its
    subject: a World subject must be independently discoverable under the
    World Explorer rule (`discoverable_entity_ids` — characters gated by the
    discover tiers, per-entity `campaign.view` denies, unpublished
    definitions, event timeline/draft scope), and a quest subject must pass
    the quest detail route's own visibility contract under the caller's
    authorized party perspective (`quest_party_id`). A subject in another
    world, of a type with no detail route, hidden, or nonexistent is simply
    absent, so a response can never distinguish "no subject" from "a
    subject you may not see"."""
    if not subject_ids:
        return {}
    discoverable = discoverable_entity_ids(
        connection,
        list(subject_ids),
        world_id=world_id,
        timeline_id=access.timeline_id,
        visibility=resolve_world_entity_visibility(access, connection),
    )
    return _subject_summaries(
        connection,
        subject_ids,
        discoverable_world_ids=discoverable,
        access=access,
        world_id=world_id,
        quest_party_id=quest_party_id,
    )


@dataclass(frozen=True)
class _RelatedIdRedaction:
    """The per-page allow-lists for a `KnowledgeListItem`'s optional related
    ids. An id absent from its set is redacted to `null` in the response
    (Issue 1) — a knowledge item stays visible with its own content, but a
    `subject_entity_id` / `source_event_id` / `source_interaction_id` is
    returned only when this caller could independently discover that
    resource. Returning the id is itself a disclosure; it cannot be
    deferred to "the caller re-authorizes it on the next request"."""

    discoverable_entities: frozenset[uuid.UUID]
    visible_interactions: frozenset[uuid.UUID]
    subjects: dict[uuid.UUID, KnowledgeSubjectResponse]

    def subject(self, item: KnowledgeListItem) -> KnowledgeSubjectResponse | None:
        sid = item.subject_entity_id
        return self.subjects.get(sid) if sid is not None else None

    def source_event(self, item: KnowledgeListItem) -> uuid.UUID | None:
        eid = item.source_event_id
        return eid if eid is not None and eid in self.discoverable_entities else None

    def source_interaction(self, item: KnowledgeListItem) -> uuid.UUID | None:
        iid = item.source_interaction_id
        return iid if iid is not None and iid in self.visible_interactions else None


def _resolve_related_id_redaction(
    connection: Connection,
    items: tuple[KnowledgeListItem, ...],
    *,
    access: AccessContext,
    timeline_id: uuid.UUID,
    world_id: uuid.UUID,
    quest_party_id: uuid.UUID | None,
) -> _RelatedIdRedaction:
    subject_candidates = {i.subject_entity_id for i in items if i.subject_entity_id is not None}
    entity_candidates = subject_candidates | {
        i.source_event_id for i in items if i.source_event_id is not None
    }
    discoverable = (
        discoverable_entity_ids(
            connection,
            list(entity_candidates),
            world_id=world_id,
            timeline_id=timeline_id,
            visibility=resolve_world_entity_visibility(access, connection),
        )
        if entity_candidates
        else frozenset()
    )
    interaction_candidates = [
        i.source_interaction_id for i in items if i.source_interaction_id is not None
    ]
    # `interaction.interactions` has no browse/detail endpoint and no
    # resource-grant target column — the only independent "may I see this"
    # signal is that the interaction happened on the caller's own resolved
    # campaign timeline (its own events are already visible to a
    # `campaign.view` member). A cross-timeline reference is redacted.
    visible_interactions: frozenset[uuid.UUID] = frozenset()
    if interaction_candidates:
        visible_interactions = frozenset(
            connection.execute(
                text(
                    "SELECT interaction_id FROM interaction.interactions "
                    "WHERE interaction_id = ANY(CAST(:ids AS uuid[])) AND timeline_id = :timeline"
                ),
                {"ids": interaction_candidates, "timeline": timeline_id},
            ).scalars()
        )
    return _RelatedIdRedaction(
        discoverable_entities=discoverable,
        visible_interactions=visible_interactions,
        subjects=_subject_summaries(
            connection,
            subject_candidates,
            discoverable_world_ids=discoverable,
            access=access,
            world_id=world_id,
            quest_party_id=quest_party_id,
        ),
    )


@router.get(
    "/campaigns/{campaign_id}/knowledge",
    response_model=KnowledgeListResponse,
    status_code=200,
)
def list_knowledge_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_KNOWLEDGE_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    view: Annotated[KnowledgeView, Query()] = "known",
    character_id: Annotated[uuid.UUID | None, Query()] = None,
    party_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=_MAX_QUERY_LEN)] = None,
    type: Annotated[str | None, Query(max_length=64)] = None,
    include_public: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> KnowledgeListResponse:
    """The audience-filtered Knowledge screen list. See
    `dnd_ai.queries.knowledge_browse` for the `view` vocabulary and
    semantics. `character_id`/`party_id` are the perspective: the
    audience-specific part of `known`/`rumors`/`party_shared` needs an
    authorized `(character_id, party_id)` pair; `character_private` needs
    `character_id` (with `character.view_knowledge` held for it); `recent`
    uses either or both. Public knowledge needs no perspective and is
    included in every view by default — an omitted perspective yields just
    the public items, never an error or an existence hint. `include_public=
    false` is the explicit opt-out; `view=public` is the public-only
    filter. An item both public and in the caller's audience is listed once,
    in its audience-specific projection."""
    include_ground_truth = access.has_capability(_KNOWLEDGE_GROUND_TRUTH_CAPABILITY)

    authorized_party_id = resolve_party_perspective(
        connection,
        access=access,
        campaign_id=campaign_id,
        character_id=character_id,
        party_id=party_id,
    )
    authorized_knower_id: uuid.UUID | None = None
    if character_id is not None and access.has_capability(
        _CHARACTER_KNOWLEDGE_CAPABILITY, character_id=character_id
    ):
        authorized_knower_id = character_id

    time_ordered = view == "recent"
    keyset_name = RECENT_KEYSET if time_ordered else KNOWN_KEYSET
    # `recent` orders by an integer world-time sort key (nullable); every
    # other view orders by a bounded statement-prefix string. A cursor
    # shaped for the wrong one — or carrying a non-int / non-UUID / `null`
    # value — is rejected as `invalid_cursor` (422) here, never converted
    # with a bare `int()`/`uuid.UUID()` that would raise deeper (500).
    cursor_fields: tuple[CursorFieldType, ...] = (
        ("int_or_none", "uuid") if time_ordered else ("str", "uuid")
    )
    keyset = decode_typed_cursor(cursor, keyset=keyset_name, fields=cursor_fields)
    after_statement: str | None = None
    after_time_sort: int | None = None
    after_record_id: uuid.UUID | None = None
    if keyset is not None:
        after_record_id = cast(uuid.UUID, keyset[1])
        if time_ordered:
            after_time_sort = cast("int | None", keyset[0])
        else:
            after_statement = cast(str, keyset[0])

    ground_truth_allowed, ground_truth_denied = _ground_truth_item_targets(access)
    world_id = timeline_world_id(connection, access.timeline_id)
    # Phase 15.1 draft/published separation: everyone sees only published, active
    # claims in lists; a `canon.edit` holder also sees unpublished ones.
    lifecycle_hidden = lifecycle_hidden_entity_ids(
        connection,
        world_id=world_id,
        mode="browse",
        can_edit_canon=include_ground_truth,
        include_noncanon=include_ground_truth,
        include_archived=False,
    )
    items = list_knowledge(
        connection,
        view=view,
        timeline_id=access.timeline_id,
        world_id=timeline_world_id(connection, access.timeline_id),
        include_ground_truth=include_ground_truth,
        authorized_party_id=authorized_party_id,
        authorized_knower_id=authorized_knower_id,
        query_text=q,
        knowledge_type_code=type,
        denied_item_ids=_denied_item_ids(access) | lifecycle_hidden,
        ground_truth_allowed_item_ids=ground_truth_allowed,
        ground_truth_denied_item_ids=ground_truth_denied,
        limit=limit,
        after_statement=after_statement,
        after_time_sort=after_time_sort,
        after_record_id=after_record_id,
        include_public=include_public,
    )

    if time_ordered:
        page = build_page(
            items,
            limit=limit,
            keyset=keyset_name,
            cursor_key=lambda item: [item.time_sort, item.record_id],
        )
    else:
        page = build_page(
            items,
            limit=limit,
            keyset=keyset_name,
            cursor_key=lambda item: [item.statement_sort, item.record_id],
        )

    redaction = _resolve_related_id_redaction(
        connection,
        tuple(page.items),
        access=access,
        timeline_id=access.timeline_id,
        world_id=world_id,
        quest_party_id=authorized_party_id,
    )

    states = (
        knowledge_definition_states(
            connection,
            world_id=world_id,
            knowledge_item_ids=[item.knowledge_item_id for item in page.items],
        )
        if include_ground_truth
        else {}
    )
    subjects = [redaction.subject(item) for item in page.items]
    return KnowledgeListResponse(
        items=[
            KnowledgeListItemResponse(
                knowledge_item_id=item.knowledge_item_id,
                knowledge_type_code=item.knowledge_type_code,
                statement=item.statement,
                truth_status_code=item.truth_status_code,
                sensitivity=item.sensitivity,
                awareness_level=item.awareness_level,
                confidence=item.confidence,
                willing_to_share=item.willing_to_share,
                scope=item.scope,
                discovery_world_time_id=item.discovery_world_time_id,
                source_event_id=redaction.source_event(item),
                source_interaction_id=redaction.source_interaction(item),
                subject_entity_id=None if subject is None else subject.entity_id,
                subject=subject,
                canon_status=states.get(item.knowledge_item_id, (None, None))[0],
                lifecycle_status=states.get(item.knowledge_item_id, (None, None))[1],
            )
            for item, subject in zip(page.items, subjects, strict=True)
        ],
        next_cursor=page.next_cursor,
    )


def resolve_knowledge_response(
    connection: Connection,
    *,
    access: AccessContext,
    campaign_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    character_id: uuid.UUID | None,
    party_id: uuid.UUID | None,
) -> KnowledgeResponse | None:
    """The exact audience-scoped `KnowledgeResponse` `access` would see for
    `knowledge_item_id` in `campaign_id`, or `None` for the identical non-
    disclosing "this caller may not see this item at all" case
    `get_knowledge_endpoint` itself used to raise `NotFoundError` for
    inline.

    Extracted (checkpoint 15, PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md
    §8.4b) for the identical reason `dnd_ai.api.quests.
    resolve_quest_response` was — see that function's own docstring. Every
    line below is unchanged from the pre-checkpoint-15 body of
    `get_knowledge_endpoint`; only the 404 became a `None` return."""
    if not access.has_capability(_KNOWLEDGE_VIEW_CAPABILITY, knowledge_item_id=knowledge_item_id):
        # A per-item `campaign.view` deny — indistinguishable from a
        # nonexistent item, and keeps this route in agreement with the
        # Phase 13D `GET /campaigns/{id}/knowledge` list, which excludes a
        # denied `knowledge_item_id` in SQL.
        return None

    include_ground_truth = access.has_capability(
        _KNOWLEDGE_GROUND_TRUTH_CAPABILITY,
        knowledge_item_id=knowledge_item_id,
    )
    # Phase 15.1: an unpublished claim is the same "not visible" answer for a
    # caller without `canon.edit`; archived and superseded stay readable by id.
    if knowledge_item_id in lifecycle_hidden_entity_ids(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        mode="reference",
        can_edit_canon=include_ground_truth,
    ):
        return None
    authorized_party_id = (
        None
        if include_ground_truth
        else resolve_party_perspective(
            connection,
            access=access,
            campaign_id=campaign_id,
            character_id=character_id,
            party_id=party_id,
        )
    )
    # Character-private fallback: a non-GM caller who named only a
    # character (no party) and holds character.view_knowledge for it gets
    # that character's own entity_knowledge belief — keeping this route in
    # agreement with the `character_private` list view.
    knower_entity_id: uuid.UUID | None = None
    if (
        not include_ground_truth
        and authorized_party_id is None
        and character_id is not None
        and access.has_capability(_CHARACTER_KNOWLEDGE_CAPABILITY, character_id=character_id)
    ):
        knower_entity_id = character_id

    view = get_knowledge_view(
        connection,
        knowledge_item_id=knowledge_item_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        party_id=authorized_party_id,
        include_ground_truth=include_ground_truth,
        knower_entity_id=knower_entity_id,
        allow_public=True,
    )

    subject: KnowledgeSubjectResponse | None = None
    if view.subject_entity_id is not None:
        subject = resolve_subject_summaries(
            connection,
            {view.subject_entity_id},
            access=access,
            world_id=timeline_world_id(connection, access.timeline_id),
            quest_party_id=_subject_quest_party(
                connection,
                access=access,
                campaign_id=campaign_id,
                character_id=character_id,
                party_id=party_id,
                resolved_party_id=authorized_party_id,
                resolved=not include_ground_truth,
            ),
        ).get(view.subject_entity_id)

    return KnowledgeResponse(
        knowledge_item_id=view.knowledge_item_id,
        knowledge_type_code=view.knowledge_type_code,
        statement=view.statement,
        truth_status_code=view.truth_status_code,
        sensitivity=view.sensitivity,
        awareness_level=view.awareness_level,
        confidence=view.confidence,
        willing_to_share=view.willing_to_share,
        subject=subject,
    )


def _subject_quest_party(
    connection: Connection,
    *,
    access: AccessContext,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID | None,
    party_id: uuid.UUID | None,
    resolved_party_id: uuid.UUID | None,
    resolved: bool,
) -> uuid.UUID | None:
    """The party perspective a quest subject is checked under — the one the
    quest detail route would resolve for the same `character_id`/`party_id`.
    The knowledge detail skips resolving it for a caller with ground truth on
    this item; a baseline GM needs none (they see every party's tracking),
    but a non-GM holding only an item-targeted `canon.edit` allow still does.
    An unauthorized pair there yields no perspective rather than an error,
    so naming a subject never changes whether the knowledge item itself is
    returned."""
    if resolved or access.has_capability(_KNOWLEDGE_GROUND_TRUTH_CAPABILITY):
        return resolved_party_id
    try:
        return resolve_party_perspective(
            connection,
            access=access,
            campaign_id=campaign_id,
            character_id=character_id,
            party_id=party_id,
        )
    except PartyPerspectiveNotAuthorizedError:
        return None


@router.get(
    "/campaigns/{campaign_id}/knowledge/{knowledge_item_id}",
    response_model=KnowledgeResponse,
    status_code=200,
)
def get_knowledge_endpoint(
    campaign_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_KNOWLEDGE_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> KnowledgeResponse:
    response = resolve_knowledge_response(
        connection,
        access=access,
        campaign_id=campaign_id,
        knowledge_item_id=knowledge_item_id,
        character_id=character_id,
        party_id=party_id,
    )
    if response is None:
        raise NotFoundError()
    return response


# A module-level guard so a typo in `KnowledgeView` above cannot silently
# drift from the query layer's own view vocabulary.
assert set(KnowledgeView.__args__) == set(KNOWLEDGE_VIEWS)  # type: ignore[attr-defined]
