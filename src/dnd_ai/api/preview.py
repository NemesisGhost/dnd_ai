"""Per-resource audience preview (Phase 13E-B checkpoint 15, docs/UI_DESIGN.md
§16 / PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §8.4b) — the spoiler-checking
half of D-1's "preview as a selected member" answer. `dnd_ai.queries.
effective_access` (checkpoint 13) already tells a GM *what capabilities* a
member holds; it cannot show what a specific quest or knowledge item
actually renders as for that member, since quest/knowledge detail is
`visibility_policy`-driven, not capability-listing-driven. This module adds
`GET` routes for that: one detail route per previewable resource kind,
plus, for Knowledge, the collection and the subject's own selectable perspectives:

```
GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/quests/{quest_id}
GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge/{knowledge_item_id}
GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge
GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge/perspectives
```

**The actor and the subject are never interchangeable.** `require_campaign_
capability` is not modified at all — it authorizes the **actor** (the GM
viewing this preview) for `access.manage` in `campaign_id` and returns their
own `AccessContext`, exactly as every other Access-page route. That
authorization decision is complete, and unaffected by anything below,
before either route resolves who the preview is *about*. `resolve_preview_
subject` then separately resolves the **subject** — the named
`campaign_membership_id` — into a `PreviewSubjectContext`, a distinct
frozen wrapper type nothing else in this codebase returns, and that no
mutation anywhere accepts. A caller cannot pass a `PreviewSubjectContext`
where an `AccessContext` is expected (it is not one), and `require_campaign_
capability` can never hand back a `PreviewSubjectContext` for a route to
misuse as if it were the actor's own — "the variables got swapped" is a
mypy error here, not a runtime authorization bypass, which is the entire
point of the wrapper rather than merely documenting the distinction.

**The preview must not lie.** Both routes call `dnd_ai.api.quests.
resolve_quest_response`/`dnd_ai.api.knowledge.resolve_knowledge_response` —
the exact same audience-derivation functions `get_quest_endpoint`/
`get_knowledge_endpoint` call for a real request — passing the *subject's*
own resolved `AccessContext` in place of the actor's. Nothing here
reimplements or approximates that derivation; a preview is therefore
byte-identical to what the subject's own authenticated request against the
same resource and query parameters would return. `character_id`/`party_id`
query parameters are interpreted against the **subject**, never the actor.

**Non-disclosure.** Every failure — the subject membership missing,
belonging to a different campaign, closed, suspended, or its owning account
platform-disabled; the resource itself denying the subject access; the
subject simply not being entitled to see this resource at all — collapses
to the identical `NotFoundError` (404) `require_campaign_capability` already
gives for the actor's own missing/insufficient access. A caller can never
learn which case applied.

**Closed registry.** The only previewable resources are the entries of
`PREVIEW_ADAPTERS` (`quests`, `knowledge`), each bound to one fixed GET route
above. No path or query parameter selects an adapter, nothing dispatches to an
arbitrary URL or endpoint, only GET is registered, and an adapter's declared
`ceiling` (the data classes its projection may contain) can never include
`PLAYER_PRIVATE` or `SECRET`. A future private resource is not previewable
unless a reviewed adapter is added deliberately.

**Audit (metadata only).** Viewing a preview is not acting as another user --
no second session is created, nothing is mutable -- but it is a sensitive read,
so every request that passes the actor's own `access.manage` authorization writes
one `audit.change_log` row with action `sensitive_read`: actor, world, resource
kind and id, subject membership id, outcome (`shown` or `refused`), whether a
character/party perspective was supplied (booleans only), and the correlation
id. Never the projected response, narrative, query-string values, credentials,
or tokens. A refusal still raises the identical 404, and its audit row is
committed before the error is raised (the request transaction would otherwise
roll it back)."""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext, resolve_access_context
from dnd_ai.domain.data_classification import DataClass
from dnd_ai.domain.errors import SafeMessageError
from dnd_ai.queries.bootstrap import get_session_bootstrap

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection
from .errors import NotFoundError
from .knowledge import (
    KnowledgeListResponse,
    KnowledgeResponse,
    KnowledgeView,
    resolve_knowledge_list,
    resolve_knowledge_response,
)
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .quests import QuestResponse, resolve_quest_response

router = APIRouter(tags=["preview"])

_ACCESS_MANAGE_CAPABILITY = "access.manage"

_PREVIEW_ACTION = "sensitive_read"
_FORBIDDEN_CEILING_CLASSES = frozenset({DataClass.PLAYER_PRIVATE, DataClass.SECRET})


@dataclass(frozen=True)
class PreviewAdapter:
    """One previewable resource kind. `schema_name`/`table_name` identify the
    audited record; `ceiling` is the closed set of data classes the adapter's
    projection may contain, and may never include `PLAYER_PRIVATE`/`SECRET`."""

    resource_kind: str
    command_name: str
    schema_name: str
    table_name: str
    ceiling: frozenset[DataClass]

    def __post_init__(self) -> None:
        if self.ceiling & _FORBIDDEN_CEILING_CLASSES:
            raise ValueError(f"preview adapter {self.resource_kind!r} may not expose private data")


# The closed registry. Adding a previewable resource means adding an entry here
# deliberately (and a pinned-registry test updates with it); nothing else can
# become previewable.
_ADAPTER_CEILING = frozenset(
    {
        DataClass.PUBLIC_WORLD,
        DataClass.CAMPAIGN_VISIBLE,
        DataClass.CHARACTER_VISIBLE,
        DataClass.PARTY_VISIBLE,
        DataClass.STRUCTURAL,
    }
)
PREVIEW_ADAPTERS: Mapping[str, PreviewAdapter] = MappingProxyType(
    {
        "quests": PreviewAdapter(
            resource_kind="quest",
            command_name="preview_quest",
            schema_name="narrative",
            table_name="quests",
            ceiling=_ADAPTER_CEILING,
        ),
        "knowledge": PreviewAdapter(
            resource_kind="knowledge_item",
            command_name="preview_knowledge",
            schema_name="knowledge",
            table_name="knowledge_items",
            ceiling=_ADAPTER_CEILING,
        ),
    }
)


def _resolve_or_refuse[T](
    connection: Connection,
    *,
    adapter: PreviewAdapter,
    actor: AccessContext,
    campaign_membership_id: uuid.UUID,
    resource_id: uuid.UUID | None,
    character_supplied: bool,
    party_supplied: bool,
    correlation_id: str | None,
    subject: "PreviewSubjectContext | None",
    resolve: Callable[[AccessContext], T | None],
    scope: str | None = None,
) -> T | None:
    """Run the adapter's resolver for the subject. A resolver that refuses by
    raising (an unauthorized character/party perspective, for example) is
    audited as `refused` before the same error propagates, so every request that
    passed the actor's own authorization leaves exactly one audit row."""
    if subject is None:
        return None
    try:
        return resolve(subject.access)
    except SafeMessageError:
        _audit_preview(
            connection,
            adapter=adapter,
            actor=actor,
            campaign_membership_id=campaign_membership_id,
            resource_id=resource_id,
            shown=False,
            character_supplied=character_supplied,
            party_supplied=party_supplied,
            correlation_id=correlation_id,
            scope=scope,
        )
        raise


def _audit_preview(
    connection: Connection,
    *,
    adapter: PreviewAdapter,
    actor: AccessContext,
    campaign_membership_id: uuid.UUID,
    resource_id: uuid.UUID | None,
    shown: bool,
    character_supplied: bool,
    party_supplied: bool,
    correlation_id: str | None,
    scope: str | None = None,
) -> None:
    """One metadata-only `sensitive_read` row. Never the response body, any
    narrative, a query-string value, or a token."""
    changed: dict[str, Any] = {
        "resource_kind": adapter.resource_kind,
        "subject_membership_id": str(campaign_membership_id),
        "outcome": "shown" if shown else "refused",
        "character_perspective_supplied": character_supplied,
        "party_perspective_supplied": party_supplied,
    }
    if scope is not None:
        # A preview of no single record: the Knowledge collection, or the subject's perspectives.
        changed["scope"] = scope
    record_change_log(
        connection,
        change_action_code=_PREVIEW_ACTION,
        schema_name=adapter.schema_name,
        table_name=adapter.table_name,
        record_id=resource_id,
        entity_id=resource_id,
        world_id=timeline_world_id(connection, actor.timeline_id),
        actor_user_id=actor.user_id,
        correlation_id=correlation_id,
        command_name=adapter.command_name,
        event_id=None,
        changed_fields=changed,
    )
    if not shown:
        # The caller raises NotFoundError next, which rolls the request
        # transaction back; commit now so a refused preview is still recorded
        # (the same pattern as the failed-login audit row).
        connection.commit()


@dataclass(frozen=True)
class PreviewSubjectContext:
    """The resolved identity of an audience-preview **subject** — a
    campaign member other than the actor viewing the preview. Deliberately
    not an `AccessContext` itself (and not a subclass of one): nothing in
    this codebase ever accepts a `PreviewSubjectContext` where an
    `AccessContext` is expected, and `dnd_ai.api.access.
    require_campaign_capability` can never construct or return one — the
    only way to obtain the `AccessContext` this wraps is to explicitly read
    `.access`, an unmistakable, deliberate unwrap at each of this module's
    two call sites, never an accidental substitution of actor for subject.
    """

    access: AccessContext
    display_name: str


def resolve_preview_subject(
    connection: Connection,
    *,
    actor: AccessContext,
    campaign_membership_id: uuid.UUID,
) -> PreviewSubjectContext | None:
    """Resolves `campaign_membership_id` as an audience-preview subject in
    `actor.campaign_id`, or `None` for any of: the membership does not
    exist or does not belong to `actor.campaign_id`; the membership is not
    currently open (`ended_at IS NOT NULL`) or not `active`; the owning
    account is not currently platform-active. Reuses the identical
    eligibility bar `dnd_ai.commands.access_grants`/`.access_groups` already
    apply when validating a *mutation's* target membership — see, e.g.,
    `grant_character_relationship`'s own `MembershipNotActiveError` check —
    except read-only: this never takes a row lock (`FOR UPDATE`), since a
    preview is a pure `GET` with nothing to serialize against.

    On success, resolves the subject's own full `AccessContext` via `dnd_ai.
    domain.access.resolve_access_context` against the actor's own pinned
    `timeline_id` (never a caller-supplied one, matching that resolver's own
    scope rule) — the identical resolution a real request from that member
    would produce. A `None` there (the membership eligibility above passed,
    but `resolve_access_context` still finds no authorizing membership — not
    expected to occur in practice, since the same "open and active" facts
    were just read, but resolved independently rather than assumed) also
    maps to this function's own `None`, never treated as a bug."""
    row = (
        connection.execute(
            text("""
                SELECT cm.user_id, u.display_name,
                       ms.code AS membership_status_code,
                       ms.is_active AS membership_status_is_active,
                       account_status.code AS account_status_code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                JOIN security.users u ON u.user_id = cm.user_id
                JOIN core.lifecycle_statuses account_status
                    ON account_status.lifecycle_status_id = u.lifecycle_status_id
                WHERE cm.campaign_membership_id = :membership_id
                  AND cm.campaign_id = :campaign_id
                  AND cm.ended_at IS NULL
            """),
            {
                "membership_id": campaign_membership_id,
                "campaign_id": actor.campaign_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if row["membership_status_code"] != "active" or not row["membership_status_is_active"]:
        return None
    if row["account_status_code"] != "active":
        return None

    subject_access = resolve_access_context(
        connection,
        user_id=row["user_id"],
        campaign_id=actor.campaign_id,
        timeline_id=actor.timeline_id,
    )
    if subject_access is None:
        return None

    return PreviewSubjectContext(access=subject_access, display_name=str(row["display_name"]))


@router.get(
    "/campaigns/{campaign_id}/members/{campaign_membership_id}/preview/quests/{quest_id}",
    response_model=QuestResponse,
    status_code=200,
)
def preview_quest_endpoint(
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> QuestResponse:
    """`character_id`/`party_id` are interpreted against the **subject**
    (`campaign_membership_id`), never the actor — see this module's own
    docstring."""
    adapter = PREVIEW_ADAPTERS["quests"]
    subject = resolve_preview_subject(
        connection, actor=actor, campaign_membership_id=campaign_membership_id
    )
    response = _resolve_or_refuse(
        connection,
        adapter=adapter,
        actor=actor,
        campaign_membership_id=campaign_membership_id,
        resource_id=quest_id,
        character_supplied=character_id is not None,
        party_supplied=party_id is not None,
        correlation_id=correlation_id,
        subject=subject,
        resolve=lambda access: resolve_quest_response(
            connection,
            access=access,
            campaign_id=campaign_id,
            quest_id=quest_id,
            character_id=character_id,
            party_id=party_id,
        ),
    )
    _audit_preview(
        connection,
        adapter=adapter,
        actor=actor,
        campaign_membership_id=campaign_membership_id,
        resource_id=quest_id,
        shown=response is not None,
        character_supplied=character_id is not None,
        party_supplied=party_id is not None,
        correlation_id=correlation_id,
    )
    if response is None:
        raise NotFoundError()
    return response


class PreviewPartyRef(BaseModel):
    party_id: uuid.UUID
    party_name: str


class PreviewCharacterPerspective(BaseModel):
    character_id: uuid.UUID
    character_name: str
    authorized_parties: list[PreviewPartyRef]


class PreviewPerspectivesResponse(BaseModel):
    """What the **subject** may choose as a Knowledge perspective: exactly the character and
    party perspectives their own session bootstrap would offer, so the preview never invites a
    character or party the server would refuse for them."""

    display_name: str
    roles: list[str]
    character_perspectives: list[PreviewCharacterPerspective]


# Declared before the `{knowledge_item_id}` route so the fixed segment is never read as an id.
@router.get(
    "/campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge/perspectives",
    response_model=PreviewPerspectivesResponse,
    status_code=200,
)
def preview_knowledge_perspectives_endpoint(
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    actor: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> PreviewPerspectivesResponse:
    """The subject's own selectable character and party perspectives (`get_session_bootstrap`
    run for the subject, the derivation their own bootstrap uses). Same non-disclosing 404 as every
    other unresolvable subject."""
    adapter = PREVIEW_ADAPTERS["knowledge"]
    subject = resolve_preview_subject(
        connection, actor=actor, campaign_membership_id=campaign_membership_id
    )
    response: PreviewPerspectivesResponse | None = None
    if subject is not None:
        bootstrap = get_session_bootstrap(connection, user_id=subject.access.user_id)
        campaign = next((c for c in bootstrap.campaigns if c.campaign_id == campaign_id), None)
        if campaign is not None:
            response = PreviewPerspectivesResponse(
                display_name=subject.display_name,
                roles=list(campaign.roles),
                character_perspectives=[
                    PreviewCharacterPerspective(
                        character_id=perspective.character_id,
                        character_name=perspective.character_name,
                        authorized_parties=[
                            PreviewPartyRef(party_id=party.party_id, party_name=party.party_name)
                            for party in perspective.authorized_parties
                        ],
                    )
                    for perspective in campaign.character_perspectives
                ],
            )
    _audit_preview(
        connection,
        adapter=adapter,
        actor=actor,
        campaign_membership_id=campaign_membership_id,
        resource_id=None,
        shown=response is not None,
        character_supplied=False,
        party_supplied=False,
        correlation_id=correlation_id,
        scope="perspectives",
    )
    if response is None:
        raise NotFoundError()
    return response


@router.get(
    "/campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge/{knowledge_item_id}",
    response_model=KnowledgeResponse,
    status_code=200,
)
def preview_knowledge_endpoint(
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    actor: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> KnowledgeResponse:
    """`character_id`/`party_id` are interpreted against the **subject**
    (`campaign_membership_id`), never the actor — see this module's own
    docstring."""
    adapter = PREVIEW_ADAPTERS["knowledge"]
    subject = resolve_preview_subject(
        connection, actor=actor, campaign_membership_id=campaign_membership_id
    )
    response = _resolve_or_refuse(
        connection,
        adapter=adapter,
        actor=actor,
        campaign_membership_id=campaign_membership_id,
        resource_id=knowledge_item_id,
        character_supplied=character_id is not None,
        party_supplied=party_id is not None,
        correlation_id=correlation_id,
        subject=subject,
        resolve=lambda access: resolve_knowledge_response(
            connection,
            access=access,
            campaign_id=campaign_id,
            knowledge_item_id=knowledge_item_id,
            character_id=character_id,
            party_id=party_id,
        ),
    )
    _audit_preview(
        connection,
        adapter=adapter,
        actor=actor,
        campaign_membership_id=campaign_membership_id,
        resource_id=knowledge_item_id,
        shown=response is not None,
        character_supplied=character_id is not None,
        party_supplied=party_id is not None,
        correlation_id=correlation_id,
    )
    if response is None:
        raise NotFoundError()
    return response


@router.get(
    "/campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge",
    response_model=KnowledgeListResponse,
    status_code=200,
)
def preview_knowledge_list_endpoint(
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    actor: Annotated[
        AccessContext, Depends(require_campaign_capability(_ACCESS_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
    view: Annotated[KnowledgeView, Query()] = "known",
    character_id: Annotated[uuid.UUID | None, Query()] = None,
    party_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    type: Annotated[str | None, Query(max_length=64)] = None,
    include_public: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> KnowledgeListResponse:
    """The Knowledge collection as the **subject** (`campaign_membership_id`) would receive it:
    the same derivation as their own `GET /campaigns/{id}/knowledge` (`resolve_knowledge_list`)
    with the subject's `AccessContext`, never the actor's. A subject who could not open the
    Knowledge screen at all (no `campaign.view`) is the same non-disclosing 404 as any other
    unresolvable subject. `character_id`/`party_id` are interpreted against the subject."""
    adapter = PREVIEW_ADAPTERS["knowledge"]
    subject = resolve_preview_subject(
        connection, actor=actor, campaign_membership_id=campaign_membership_id
    )
    response = _resolve_or_refuse(
        connection,
        adapter=adapter,
        actor=actor,
        campaign_membership_id=campaign_membership_id,
        resource_id=None,
        character_supplied=character_id is not None,
        party_supplied=party_id is not None,
        correlation_id=correlation_id,
        subject=subject,
        resolve=lambda access: (
            resolve_knowledge_list(
                connection,
                access=access,
                campaign_id=campaign_id,
                view=view,
                character_id=character_id,
                party_id=party_id,
                q=q,
                type=type,
                include_public=include_public,
                limit=limit,
                cursor=cursor,
            )
            if access.has_capability("campaign.view")
            else None
        ),
        scope="collection",
    )
    _audit_preview(
        connection,
        adapter=adapter,
        actor=actor,
        campaign_membership_id=campaign_membership_id,
        resource_id=None,
        shown=response is not None,
        character_supplied=character_id is not None,
        party_supplied=party_id is not None,
        correlation_id=correlation_id,
        scope="collection",
    )
    if response is None:
        raise NotFoundError()
    return response
