"""Per-resource audience preview (Phase 13E-B checkpoint 15, docs/UI_DESIGN.md
§16 / PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §8.4b) — the spoiler-checking
half of D-1's "preview as a selected member" answer. `dnd_ai.queries.
effective_access` (checkpoint 13) already tells a GM *what capabilities* a
member holds; it cannot show what a specific quest or knowledge item
actually renders as for that member, since quest/knowledge detail is
`visibility_policy`-driven, not capability-listing-driven. This module adds
exactly two `GET` routes for that:

```
GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/quests/{quest_id}
GET /campaigns/{campaign_id}/members/{campaign_membership_id}/preview/knowledge/{knowledge_item_id}
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

**Audit.** A pure read: no idempotency key, no `audit.change_log` row.
Viewing a preview is not acting as another user — no second session is
created, and nothing here is mutable."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext, resolve_access_context

from .access import require_campaign_capability
from .deps import get_connection
from .errors import NotFoundError
from .knowledge import KnowledgeResponse, resolve_knowledge_response
from .quests import QuestResponse, resolve_quest_response

router = APIRouter(tags=["preview"])

_ACCESS_MANAGE_CAPABILITY = "access.manage"


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
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> QuestResponse:
    """`character_id`/`party_id` are interpreted against the **subject**
    (`campaign_membership_id`), never the actor — see this module's own
    docstring."""
    subject = resolve_preview_subject(
        connection, actor=actor, campaign_membership_id=campaign_membership_id
    )
    if subject is None:
        raise NotFoundError()

    response = resolve_quest_response(
        connection,
        access=subject.access,
        campaign_id=campaign_id,
        quest_id=quest_id,
        character_id=character_id,
        party_id=party_id,
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
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> KnowledgeResponse:
    """`character_id`/`party_id` are interpreted against the **subject**
    (`campaign_membership_id`), never the actor — see this module's own
    docstring."""
    subject = resolve_preview_subject(
        connection, actor=actor, campaign_membership_id=campaign_membership_id
    )
    if subject is None:
        raise NotFoundError()

    response = resolve_knowledge_response(
        connection,
        access=subject.access,
        campaign_id=campaign_id,
        knowledge_item_id=knowledge_item_id,
        character_id=character_id,
        party_id=party_id,
    )
    if response is None:
        raise NotFoundError()
    return response
