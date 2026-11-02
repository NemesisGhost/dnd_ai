"""World Reader surface: browse a world's published canon
(docs/adr/0020-scoped-system-world-and-campaign-roles.md, decision D5, checkpoint SR-7).

    GET /worlds/{world_id}/canon       (world.canon.read)

A world Reader is not a member of any campaign. This route shows them what a campaign
*player* may see of the world's definitions and nothing more: it reuses the World
Explorer's search with its player-safe parameters rather than adding projection rules.

- **Published canon only** (`canon`, active). Drafts, proposed, approved and rejected
  definitions are filtered out exactly as for a player; archived ones too.
- **No characters, items or events**: characters are discoverable only through a
  campaign relationship or knowledge, items (instances) and events are campaign-
  originated records. A world-scoped reader has no campaign, so none qualify.
- **Cards only**: name, category, and the entity summary. No GM-only fields, revisions,
  provenance, sources, or any campaign data (state, sessions, knowledge, AI output).

A caller without `world.canon.read` on the world (including a use-grant holder, whose
permission to host campaigns is separate from permission to read) gets the usual
non-disclosing 404.
"""

import uuid
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection, text

from dnd_ai.domain.world_authority import WORLD_CANON_READ, WorldAuthority
from dnd_ai.queries.entity_lifecycle import lifecycle_hidden_entity_ids
from dnd_ai.queries.world_explorer import (
    ENTITY_SEARCH_KEYSET,
    WORLD_CATEGORY_TYPE_CODES,
    CharacterVisibility,
    search_world_entities,
)

from .deps import get_connection
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, build_page, decode_typed_cursor
from .world_access import require_world_capability

router = APIRouter(tags=["world-canon"])

ReaderCategory = Literal["location", "organization", "religion"]
_READER_CATEGORIES: tuple[str, ...] = ("location", "organization", "religion")
_MAX_QUERY_LEN = 200


@router.get("/worlds/{world_id}/canon")
def browse_world_canon_endpoint(
    authority: Annotated[WorldAuthority, Depends(require_world_capability(WORLD_CANON_READ))],
    connection: Annotated[Connection, Depends(get_connection)],
    category: Annotated[list[ReaderCategory] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=_MAX_QUERY_LEN)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    categories = list(category) if category else list(_READER_CATEGORIES)
    type_codes: list[str] = []
    for name in categories:
        type_codes.extend(WORLD_CATEGORY_TYPE_CODES[name])

    keyset = decode_typed_cursor(cursor, keyset=ENTITY_SEARCH_KEYSET, fields=("str", "uuid"))
    after_name = cast(str, keyset[0]) if keyset is not None else None
    after_entity_id = cast(uuid.UUID, keyset[1]) if keyset is not None else None

    # Only used to scope event rows, and the reader sees none; any timeline id works.
    timeline_id = connection.execute(
        text("SELECT timeline_id FROM campaign.timelines WHERE world_id = :w AND is_primary"),
        {"w": authority.world_id},
    ).scalar()
    cards = search_world_entities(
        connection,
        world_id=authority.world_id,
        timeline_id=timeline_id or uuid.uuid4(),
        category_type_codes=type_codes,
        query_text=q,
        # Player-safe: published, active definitions only (never `can_edit_canon`).
        campaign_view_denied_entity_ids=lifecycle_hidden_entity_ids(
            connection,
            world_id=authority.world_id,
            mode="browse",
            viewer_user_id=authority.user_id,
            can_edit_canon=False,
        ),
        character_visibility=CharacterVisibility(discover_all=False),
        include_draft_events=False,
        draft_event_allowed_ids=frozenset(),
        draft_event_denied_ids=frozenset(),
        limit=limit,
        after_name=after_name,
        after_entity_id=after_entity_id,
    )
    page = build_page(
        cards,
        limit=limit,
        keyset=ENTITY_SEARCH_KEYSET,
        cursor_key=lambda card: [card.name_sort, card.entity_id],
    )
    return {
        "items": [
            {
                "entity_id": str(card.entity_id),
                "category": card.category,
                "name": card.name,
                "summary": card.summary,
            }
            for card in page.items
        ],
        "next_cursor": page.next_cursor,
    }
