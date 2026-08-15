"""Request-scoped campaign-capability enforcement for command endpoints
(docs/architecture/DATABASE_MODEL.md §19.7, docs/PLAN.md Phase 10 deliverable
"command endpoints over the existing command/application services").

`dnd_ai.domain.access.resolve_access_context` already centralizes role,
character-relationship, and resource-grant resolution into one
`AccessContext`; this module is the thin FastAPI-specific wiring that turns
a path-supplied `campaign_id` plus the authenticated caller into that
context (or a mapped `ApiError`), so individual routers never re-derive the
same `security.*` joins or invent their own authorization shape.

A missing/non-authorizing membership and an unrecognized capability are
deliberately mapped differently, per `dnd_ai.api.errors.ForbiddenError`'s
own docstring ("prefer NotFoundError when revealing that a resource exists
at all would itself be a disclosure"): no active membership resolves to
`NotFoundError` (a non-member cannot distinguish "this campaign doesn't
exist" from "you have no access to it"), while an authenticated member who
simply lacks the required capability — membership itself is already not in
question — gets `ForbiddenError`.

`resolve_party_perspective()` and `resolve_character_view_tier()` below
are this module's resource-scoped resolvers: not "does this caller have a
campaign-wide capability" but "is this caller authorized to view fictional
knowledge through a specific party's eyes" or "...at a specific character's
full detail." Both are materially different, resource-scoped questions a
bare campaign-wide capability (or, for the former, a bare
`campaign.campaign_parties` association) cannot answer on its own — see
each function's own docstring. `resolve_party_perspective`'s docstring
also records the vulnerability it closes (a same-campaign member supplying
any other party's UUID and reading that party's hidden knowledge, since
party membership in a campaign says nothing about which *human* is
entitled to see through that party's eyes; docs/architecture/
DATABASE_MODEL.md §15's own words: "A fact known by a character is exposed
to a user only when that user has the appropriate character relationship
and capability for the requested perspective").
"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection, text

from dnd_ai.commands._shared import validate_campaign_party
from dnd_ai.domain.access import AccessContext, resolve_access_context
from dnd_ai.domain.errors import DomainAuthorizationError

from .auth import get_authenticated_user_id
from .deps import get_connection
from .errors import ForbiddenError, NotFoundError


def require_campaign_capability(
    capability_code: str,
) -> Callable[[uuid.UUID, uuid.UUID, Connection], AccessContext]:
    """Returns a FastAPI dependency requiring `capability_code` (role- or
    character-relationship-derived, per `AccessContext.has_capability`) in
    the campaign named by the route's own `campaign_id` path parameter.

    Resolves access against the campaign's own pinned timeline only — never
    a caller-supplied timeline — matching `resolve_access_context`'s own
    scope rule; no route built on this dependency accepts a `timeline_id`
    from the request."""

    def _dependency(
        campaign_id: uuid.UUID,
        user_id: Annotated[uuid.UUID, Depends(get_authenticated_user_id)],
        connection: Annotated[Connection, Depends(get_connection)],
    ) -> AccessContext:
        access = resolve_access_context(connection, user_id=user_id, campaign_id=campaign_id)
        if access is None:
            raise NotFoundError()
        if not access.has_capability(capability_code):
            raise ForbiddenError()
        return access

    return _dependency


class PartyPerspectiveNotAuthorizedError(DomainAuthorizationError):
    """Raised by `resolve_party_perspective()` for any combination that
    does not prove the authenticated caller is entitled to view fictional
    knowledge through the requested party's eyes — a missing/foreign
    character-view capability, a `party_id` not associated with
    `campaign_id`, and a character not *currently* a member of that party
    all raise this identically, so a caller can never learn which case
    applied (docs/architecture/DATABASE_MODEL.md §19.7's "prefer NotFound
    when existence itself is a disclosure" rule — the same reasoning
    `dnd_ai.commands._shared.PartyNotInCampaignError`/
    `SessionNotInCampaignError` and `dnd_ai.commands.encounters.
    EncounterNotFoundError` already apply to their own resource-scoped
    checks). The supplied character/party ids are included only in the
    constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


def resolve_party_perspective(
    connection: Connection,
    *,
    access: AccessContext,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID | None,
    party_id: uuid.UUID | None,
    capability_code: str = "character.view_knowledge",
) -> uuid.UUID | None:
    """Authorizes `party_id` as the specific party perspective a
    query may filter hidden knowledge through, or returns `None` — the safe
    default that limits a query to non-hidden content only — when no
    perspective was requested at all.

    A `campaign.campaign_parties` association is not, by itself, ever
    sufficient authorization for a non-GM party perspective (docs/
    architecture/DATABASE_MODEL.md §15: fictional party knowledge is not
    itself human authorization) — every other campaign member could
    otherwise supply any same-campaign party's UUID and read that party's
    hidden discoveries, regardless of whether they control, view, or have
    ever heard of any character in it. This function instead requires the
    caller to name a specific `character_id` and proves three independent
    things before trusting `party_id` for anything:

    1. the caller holds `capability_code` (default `character.view_knowledge`
       — the capability this codebase's own seed data names for exactly
       this purpose) for `character_id`, via `AccessContext.has_capability`
       — role capabilities, the caller's resolved
       `security.membership_character_relationships` row for this specific
       character, and any `security.resource_grants` allow/deny override
       for it, exactly as every other capability check in this codebase
       already resolves;
    2. `party_id` is actually associated with `campaign_id`
       (`dnd_ai.commands._shared.validate_campaign_party`);
    3. `character_id` is *currently* a member of `party_id` on the
       caller's own resolved timeline (`access.timeline_id`) — a
       `campaign.party_memberships` row with `effective_to_world_time_id
       IS NULL`, this table's own documented "the single representation of
       'still a member'" (migration 009), used here as the trusted,
       time-independent perspective contract rather than guessing or
       requiring a fictional "now" this API has no other source for. A
       character may belong to several parties at once (the same table's
       own comment), so `party_id` is never derived/guessed from
       `character_id` alone — the caller must name both, and both must
       agree.

    Any failure among the three raises `PartyPerspectiveNotAuthorizedError`
    (a fixed, non-disclosing 404) rather than returning `None` — a caller
    who names a specific character/party pair that fails authorization
    gets an explicit rejection, not a silent downgrade to non-hidden
    content, so a genuine misconfiguration is never mistaken for "you
    simply didn't ask for a perspective." `character_id is None or
    party_id is None` (including only one supplied) is the only case
    treated as "no perspective requested" and returns `None` silently:
    with no character named, there is nothing to authorize, and silently
    ignoring an unpaired `party_id` is what keeps it from ever being
    trusted on its own (requirement 1 above) — it never reaches
    `validate_campaign_party` or the membership check at all.
    """
    if character_id is None or party_id is None:
        return None

    if not access.has_capability(capability_code, character_id=character_id):
        raise PartyPerspectiveNotAuthorizedError(
            f"user {access.user_id} lacks {capability_code!r} for character {character_id} "
            f"in campaign {campaign_id}"
        )

    validate_campaign_party(connection, campaign_id=campaign_id, party_id=party_id)

    current_membership = connection.execute(
        text("""
            SELECT 1 FROM campaign.party_memberships
            WHERE timeline_id = :timeline
              AND party_id = :party
              AND member_entity_id = :character
              AND effective_to_world_time_id IS NULL
        """),
        {"timeline": access.timeline_id, "party": party_id, "character": character_id},
    ).scalar()
    if current_membership is None:
        raise PartyPerspectiveNotAuthorizedError(
            f"character {character_id} is not currently a member of party {party_id} "
            f"on timeline {access.timeline_id}"
        )

    return party_id


class CharacterViewNotAuthorizedError(DomainAuthorizationError):
    """Raised by `resolve_character_view_tier()` when the caller holds
    neither `character.view_full` nor `character.view_summary` (nor
    `canon.edit`) for the named character — identical for a nonexistent
    character and one the caller genuinely has no relationship to, so a
    caller can never learn which case applied. The supplied character id is
    included only in the constructor's `detail` argument (`str(self)`),
    never in `safe_message`."""


def resolve_character_view_tier(access: AccessContext, *, character_id: uuid.UUID) -> bool:
    """Returns `True` if the caller may see a character's full mechanical
    detail (`character.view_full`, or `canon.edit` — a GM), `False` if only
    the summary tier (`character.view_summary`) applies. Raises
    `CharacterViewNotAuthorizedError` if neither capability is held for
    this specific `character_id` — checked via `AccessContext.
    has_capability`, so a role capability, the caller's own resolved
    `security.membership_character_relationships` row for this character,
    and any `security.resource_grants` override all apply exactly as they
    do for every other capability check in this codebase. Pure — resolves
    entirely from the already-loaded `AccessContext`, no database access,
    since (unlike `resolve_party_perspective`) there is no further fact
    about the fictional world to verify here."""
    if access.has_capability("canon.edit"):
        return True
    if access.has_capability("character.view_full", character_id=character_id):
        return True
    if access.has_capability("character.view_summary", character_id=character_id):
        return False
    raise CharacterViewNotAuthorizedError(
        f"user {access.user_id} holds no character-view capability for character {character_id}"
    )
