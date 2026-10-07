"""The authoritative `/auth/session` portal-bootstrap query (docs/PLAN.md
§23.4, §23.7 — Phase 13B blocker: `GET /auth/session` previously returned
only minimal session-security fields, deferring campaign/capability/
feature-manifest listing to "whichever Phase 13 query surface actually
needs it" — see `dnd_ai.api.local_auth.session_bootstrap_endpoint`'s prior
docstring. This module is that surface).

Framework-free, read-only, and performs no authorization decisions of its
own beyond what its `WHERE` clauses already scope to `user_id` — every
capability, role, and character-perspective value it returns is resolved
through `dnd_ai.domain.access.resolve_access_context`, the same resolver
every other command/query in this codebase authorizes through, so the
portal is never given a second, parallel authorization system to drift out
of sync with the first (docs/architecture/DATABASE_MODEL.md §19.7).

Scope, matching the campaign-membership scan `resolve_access_context`
itself already performs per campaign:

- only campaigns with an active (`security.membership_statuses.code =
  'active'`, `is_active`, `ended_at IS NULL`) membership for `user_id`;
- only campaigns whose own `core.lifecycle_statuses.code = 'active'`
  (an archived/pending campaign is not offered as a bootstrap selection —
  a member of one is not thereby proven to still be entitled to see it
  listed, and `resolve_access_context` does not filter on this itself, so
  this module applies it explicitly);
- only campaigns where the resolved access currently carries
  `campaign.view` — the same capability every campaign read route requires
  (`dnd_ai.api.access.require_campaign_capability`). An active membership
  whose role assignments are all revoked or expired, or that never had one,
  is not a selectable campaign: offering it would land the portal on routes
  that each answer 403;
- roles: only `security.membership_roles` rows currently in force
  (`revoked_at IS NULL`, `expires_at IS NULL OR expires_at > now()`,
  `security.roles.is_active`) for that membership — the same conditions
  `resolve_access_context`'s own role-capability join already applies,
  duplicated here only because that resolver returns capability codes, not
  role codes, and the bootstrap contract wants both;
- capabilities: `AccessContext.role_capabilities` verbatim — the
  campaign-wide, role-derived capability set, never re-derived here;
- world/timeline identity: the campaign's own `campaign.timelines` row
  (resolved from `AccessContext.timeline_id`, never caller-supplied) and
  that timeline's `core.worlds` row — `world_id`/`world_name`/`timeline_id`/
  `timeline_name`, the minimum the portal needs to build the World ->
  Timeline -> Campaign hierarchy (docs/UI_DESIGN.md §4.1/§5.2). Only worlds
  and timelines reachable through an active membership above ever appear;
  an unrelated world or a branch timeline the campaign is not played on is
  never returned;
- character perspectives: every `character_id` key of `AccessContext.
  character_capabilities` with a non-empty capability set — i.e. every
  character this membership currently holds *some* relationship-derived
  capability for (owner, controller, viewer, portrayer, ...), the same
  `security.membership_character_relationships` resolution
  `resolve_access_context` already performs; a relationship type mapped to
  no capabilities at all (`security.character_relationship_type_
  capabilities` has no row for it) is not offered as a selectable
  perspective, since there would be nothing authorized to do through it;
- a character is listed as a perspective only when the user holds
  `character.view_knowledge` for it (Phase 15 checkpoint 15.2A-1) — of the
  built-in relationship types: owner, primary_controller, co_controller, and
  portrayer. A viewer-type relationship (or a former_controller one) never makes
  a character selectable;
- `authorized_parties` under each character perspective: the user's current
  parties for that character, which `dnd_ai.api.access.resolve_party_perspective`
  will accept (it requires the same `character.view_knowledge`), so the portal
  is never handed a `(character_id, party_id)` pair the resolver would reject.

Campaign startup (docs/UI_DESIGN.md §4.2, §4.7):

- `campaign_preferences` carries the user's stored `security.user_portal_
  preferences` values, but only while each stored campaign ID is still in
  the authorized campaign set above — a stored ID never grants access and
  is silently dropped (never disclosed) once membership or campaign status
  no longer authorizes it;
- `startup_campaign_id` is the server-computed landing campaign
  (`resolve_startup_campaign_id`): `None` with no accessible campaigns,
  the only campaign when exactly one is accessible, otherwise a valid
  preferred campaign, otherwise a valid last-visited campaign, otherwise
  `None` (the portal then lands on the campaign list). It is never the
  first alphabetical campaign by default;
- `selected_character_id` is `None` unless exactly one character
  perspective is authorized for that campaign, in which case that one is
  the unambiguous default — never guessed among two or more.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.access import AccessContext, resolve_access_context
from dnd_ai.queries.world_authority import resolve_world_authority

# The capability `dnd_ai.api.access.resolve_party_perspective` requires the
# caller to hold for a character before it will authorize *any* party
# perspective through that character (its `capability_code` default). A
# character the user cannot satisfy this for must not have parties
# advertised under it — see the party-row query below.
_KNOWLEDGE_PERSPECTIVE_CAPABILITY = "character.view_knowledge"

# The capability every campaign read route requires. A campaign is offered
# (listed, selected at startup, accepted as a stored preference) only while
# the caller holds it — never on the strength of a bare membership.
CAMPAIGN_VIEW_CAPABILITY = "campaign.view"


@dataclass(frozen=True)
class PartyPerspectiveRefView:
    """A party the portal may legitimately request a party-scoped
    knowledge/quest perspective through *for the character this appears
    under* — the character is a current `campaign.party_memberships` member
    of it on the campaign's own timeline, and the party is associated with
    the campaign. Exactly the pair `dnd_ai.api.access.
    resolve_party_perspective` will accept, so the portal never has to
    guess a `party_id` (Phase 13D §4 — "do not expose parties or characters
    the user cannot select")."""

    party_id: uuid.UUID
    party_name: str


@dataclass(frozen=True)
class CharacterPerspectiveView:
    character_id: uuid.UUID
    character_name: str
    authorized_parties: tuple[PartyPerspectiveRefView, ...] = ()


@dataclass(frozen=True)
class CampaignBootstrapView:
    campaign_id: uuid.UUID
    campaign_name: str
    world_id: uuid.UUID | None
    world_name: str | None
    timeline_id: uuid.UUID | None
    timeline_name: str | None
    roles: tuple[str, ...]
    character_perspectives: tuple[CharacterPerspectiveView, ...]
    selected_character_id: uuid.UUID | None
    capabilities: tuple[str, ...]
    # The caller's capabilities on this campaign's *world* (docs/adr/0019-scoped-system-
    # world-and-campaign-roles.md): independent of `capabilities`, which are campaign-
    # scoped. Lets the portal present shared-canon authoring read-only without inferring
    # it from a campaign role.
    world_capabilities: tuple[str, ...] = ()


def _world_capabilities(
    connection: Connection, user_id: uuid.UUID, world_id: uuid.UUID | None
) -> tuple[str, ...]:
    if world_id is None:
        return ()
    authority = resolve_world_authority(connection, user_id=user_id, world_id=world_id)
    return () if authority is None else tuple(sorted(authority.capabilities))


STARTUP_MODE_RESUME_LAST_VISITED = "resume_last_visited"
STARTUP_MODE_PREFERRED_CAMPAIGN = "preferred_campaign"


@dataclass(frozen=True)
class CampaignPreferencesView:
    """The caller's stored campaign-startup values, already filtered to the
    authorized campaign set. `startup_mode` is fully determined by whether a
    still-authorized `preferred_campaign_id` exists."""

    startup_mode: str
    preferred_campaign_id: uuid.UUID | None
    last_visited_campaign_id: uuid.UUID | None


@dataclass(frozen=True)
class SessionBootstrapView:
    """The complete, audience-safe portal-bootstrap payload for one
    authenticated user, recomputed fresh from current database state on
    every call — nothing here is cached or read from the browser-session
    row itself (docs/PLAN.md §23.4's "every request re-resolves" rule,
    applied to authorization data the same way it already applies to
    session validity).

    `startup_campaign_id` and `campaign_preferences` are derived from the
    user's stored portal preferences, filtered through the authorized
    campaign set computed in the same call (see this module's docstring):
    a stored ID that is no longer authorized never appears here.
    """

    user_id: uuid.UUID
    display_name: str
    startup_campaign_id: uuid.UUID | None
    campaign_preferences: CampaignPreferencesView
    campaigns: tuple[CampaignBootstrapView, ...]


_BOOTSTRAP_SCOPE_FROM_WHERE = """
    FROM security.campaign_memberships cm
    JOIN campaign.campaigns c ON c.campaign_id = cm.campaign_id
    JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = c.lifecycle_status_id
    JOIN security.membership_statuses ms
      ON ms.membership_status_id = cm.membership_status_id
    WHERE cm.user_id = :user_id
      AND cm.ended_at IS NULL
      AND ms.code = 'active'
      AND ms.is_active
      AND cls.code = 'active'
"""


def _campaign_view_access(
    connection: Connection, *, user_id: uuid.UUID, campaign_id: uuid.UUID
) -> AccessContext | None:
    """`resolve_access_context` for `campaign_id`, but only while it carries
    `campaign.view`; `None` otherwise (no membership, or a membership with no
    role assignment currently in force that grants it)."""
    access = resolve_access_context(connection, user_id=user_id, campaign_id=campaign_id)
    if access is None or not access.has_capability(CAMPAIGN_VIEW_CAPABILITY):
        return None
    return access


def _scoped_campaign_rows(connection: Connection, *, user_id: uuid.UUID) -> list[Any]:
    return list(
        connection.execute(
            text(
                "SELECT cm.campaign_membership_id, c.campaign_id, c.name AS campaign_name "
                + _BOOTSTRAP_SCOPE_FROM_WHERE
                + " ORDER BY c.name, c.campaign_id"
            ),
            {"user_id": user_id},
        )
        .mappings()
        .all()
    )


def list_bootstrap_campaign_ids(connection: Connection, *, user_id: uuid.UUID) -> list[uuid.UUID]:
    """The campaign IDs the session bootstrap would list for `user_id`,
    ordered `(name, campaign_id)` — the single definition of "authorized
    bootstrap campaign scope" shared with `is_campaign_bootstrap_authorized`
    so preference writes can never drift from what the bootstrap offers."""
    return [
        row["campaign_id"]
        for row in _scoped_campaign_rows(connection, user_id=user_id)
        if _campaign_view_access(connection, user_id=user_id, campaign_id=row["campaign_id"])
        is not None
    ]


def is_campaign_bootstrap_authorized(
    connection: Connection, *, user_id: uuid.UUID, campaign_id: uuid.UUID
) -> bool:
    """True only when `campaign_id` is in the same scope the bootstrap lists
    (active membership in an active campaign) *and* the resolved access
    carries `campaign.view` — the bootstrap skips a campaign otherwise, so
    this does too."""
    in_scope = connection.execute(
        text(
            "SELECT 1 " + _BOOTSTRAP_SCOPE_FROM_WHERE + " AND c.campaign_id = :campaign_id LIMIT 1"
        ),
        {"user_id": user_id, "campaign_id": campaign_id},
    ).scalar()
    if in_scope is None:
        return False
    return _campaign_view_access(connection, user_id=user_id, campaign_id=campaign_id) is not None


def resolve_startup_campaign_id(
    campaign_ids: Sequence[uuid.UUID],
    preferred: uuid.UUID | None,
    last_visited: uuid.UUID | None,
) -> uuid.UUID | None:
    """Pure landing-campaign precedence (docs/UI_DESIGN.md §4.2 steps 2-6).
    `preferred`/`last_visited` are assumed unfiltered; membership in
    `campaign_ids` is checked here."""
    if not campaign_ids:
        return None
    if len(campaign_ids) == 1:
        return campaign_ids[0]
    if preferred is not None and preferred in campaign_ids:
        return preferred
    if last_visited is not None and last_visited in campaign_ids:
        return last_visited
    return None


def get_session_bootstrap(connection: Connection, *, user_id: uuid.UUID) -> SessionBootstrapView:
    """Read-only. Never mutates state — no session/preference row is
    written by this query, matching a `GET` endpoint's own contract.

    `user_id` is assumed already authenticated (an `AuthenticatedPrincipal.
    user_id` — the caller, `dnd_ai.api.local_auth.session_bootstrap_
    endpoint`, only ever reaches this function after `get_authenticated_
    user_id` has already resolved one), so `security.users.display_name`
    is fetched unconditionally rather than treated as a not-found case."""
    display_name = connection.execute(
        text("SELECT display_name FROM security.users WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).scalar()
    assert isinstance(display_name, str)

    membership_rows = _scoped_campaign_rows(connection, user_id=user_id)

    campaigns: list[CampaignBootstrapView] = []
    for row in membership_rows:
        campaign_id = row["campaign_id"]
        membership_id = row["campaign_membership_id"]

        # `None` both when resolve_access_context finds no authorizing
        # membership (should not happen: the scan above uses the same
        # active/ended_at criteria) and when the membership has no role
        # currently granting `campaign.view`. Either way the campaign is not
        # offered, and one such row never breaks the rest of the bootstrap.
        access = _campaign_view_access(connection, user_id=user_id, campaign_id=campaign_id)
        if access is None:
            continue

        # World and timeline for the World -> Timeline -> Campaign hierarchy
        # the portal renders (docs/UI_DESIGN.md §4.1's CampaignContextPanel,
        # §5.2's "world name when permitted"). Resolved from
        # `access.timeline_id` — the campaign's own pinned timeline, already
        # authorized by `resolve_access_context` — never from anything the
        # caller supplied, so no world or timeline outside the user's own
        # active memberships can appear here. One extra join, still inside
        # the per-campaign loop that already re-resolves authorization on
        # every request.
        timeline_row = (
            connection.execute(
                text("""
                    SELECT t.name AS timeline_name, w.world_id, w.name AS world_name
                    FROM campaign.timelines t
                    JOIN core.worlds w ON w.world_id = t.world_id
                    WHERE t.timeline_id = :timeline
                """),
                {"timeline": access.timeline_id},
            )
            .mappings()
            .one_or_none()
        )
        timeline_name = timeline_row["timeline_name"] if timeline_row is not None else None
        world_id = timeline_row["world_id"] if timeline_row is not None else None
        world_name = timeline_row["world_name"] if timeline_row is not None else None

        role_codes = tuple(
            connection.execute(
                text("""
                    SELECT r.code
                    FROM security.membership_roles mr
                    JOIN security.roles r ON r.role_id = mr.role_id
                    WHERE mr.campaign_membership_id = :membership_id
                      AND mr.revoked_at IS NULL
                      AND (mr.expires_at IS NULL OR mr.expires_at > now())
                      AND r.is_active
                    ORDER BY r.sort_order, r.code
                """),
                {"membership_id": membership_id},
            ).scalars()
        )

        # A character is a selectable perspective only when the user holds
        # `character.view_knowledge` for it (Phase 15 checkpoint 15.2A-1): of the
        # built-in relationship types that is owner, primary_controller,
        # co_controller, and portrayer; viewer-type relationships and
        # former_controller grant visibility or nothing, never selection. The
        # candidates are still characters with a relationship-derived capability.
        character_ids = [
            character_id
            for character_id, codes in access.character_capabilities.items()
            if codes
            and access.has_capability(_KNOWLEDGE_PERSPECTIVE_CAPABILITY, character_id=character_id)
        ]
        character_perspectives: tuple[CharacterPerspectiveView, ...] = ()
        if character_ids:
            character_rows = (
                connection.execute(
                    text("""
                        SELECT entity_id, canonical_name
                        FROM core.entities
                        WHERE entity_id = ANY(:ids)
                        ORDER BY canonical_name, entity_id
                    """),
                    {"ids": character_ids},
                )
                .mappings()
                .all()
            )
            # Party perspectives the portal may legitimately request
            # through each character: the character is a *current*
            # (`effective_to_world_time_id IS NULL`) member of the party on
            # the campaign's own timeline, and the party is associated with
            # the campaign. This is exactly what `dnd_ai.api.access.
            # resolve_party_perspective` re-proves per request — surfacing
            # it here just saves the portal from guessing a `party_id`
            # (Phase 13D §4).
            #
            # `resolve_party_perspective` additionally requires the caller
            # to hold `character.view_knowledge` for the named character
            # (requirement 1 of its own docstring); a character that is only
            # *discoverable* is never listed (the perspective list above already
            # requires `character.view_knowledge`), so every listed character can
            # advertise parties. Kept as a re-check of the resolver's own gate.
            # A revoked capability or relationship affects the next bootstrap
            # because `access` is re-resolved every call.
            knowledge_perspective_ids = [
                character_id
                for character_id in character_ids
                if access.has_capability(
                    _KNOWLEDGE_PERSPECTIVE_CAPABILITY, character_id=character_id
                )
            ]
            party_rows = (
                connection.execute(
                    text("""
                        SELECT pm.member_entity_id, p.party_id, p.name AS party_name
                        FROM campaign.party_memberships pm
                        JOIN campaign.parties p ON p.party_id = pm.party_id
                        JOIN campaign.campaign_parties cp
                          ON cp.party_id = pm.party_id AND cp.campaign_id = :campaign_id
                        WHERE pm.timeline_id = :timeline_id
                          AND pm.member_entity_id = ANY(:ids)
                          AND pm.effective_to_world_time_id IS NULL
                        ORDER BY p.name, p.party_id
                    """),
                    {
                        "campaign_id": campaign_id,
                        "timeline_id": access.timeline_id,
                        "ids": knowledge_perspective_ids,
                    },
                )
                .mappings()
                .all()
                if knowledge_perspective_ids
                else []
            )
            parties_by_character: dict[uuid.UUID, list[PartyPerspectiveRefView]] = {}
            for party_row in party_rows:
                parties_by_character.setdefault(party_row["member_entity_id"], []).append(
                    PartyPerspectiveRefView(
                        party_id=party_row["party_id"],
                        party_name=party_row["party_name"],
                    )
                )

            character_perspectives = tuple(
                CharacterPerspectiveView(
                    character_id=character_row["entity_id"],
                    character_name=character_row["canonical_name"],
                    authorized_parties=tuple(
                        parties_by_character.get(character_row["entity_id"], [])
                    ),
                )
                for character_row in character_rows
            )

        selected_character_id = (
            character_perspectives[0].character_id if len(character_perspectives) == 1 else None
        )

        campaigns.append(
            CampaignBootstrapView(
                campaign_id=campaign_id,
                campaign_name=row["campaign_name"],
                world_id=world_id,
                world_name=world_name,
                timeline_id=access.timeline_id,
                timeline_name=timeline_name,
                roles=role_codes,
                character_perspectives=character_perspectives,
                selected_character_id=selected_character_id,
                capabilities=tuple(sorted(access.role_capabilities)),
                world_capabilities=_world_capabilities(connection, user_id, world_id),
            )
        )

    authorized_ids = [campaign.campaign_id for campaign in campaigns]
    stored = (
        connection.execute(
            text("""
                SELECT preferred_campaign_id, last_visited_campaign_id
                FROM security.user_portal_preferences
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        .mappings()
        .one_or_none()
    )
    stored_preferred = stored["preferred_campaign_id"] if stored is not None else None
    stored_last_visited = stored["last_visited_campaign_id"] if stored is not None else None
    # A stored ID never grants access: drop anything no longer authorized.
    preferred = stored_preferred if stored_preferred in authorized_ids else None
    last_visited = stored_last_visited if stored_last_visited in authorized_ids else None

    return SessionBootstrapView(
        user_id=user_id,
        display_name=display_name,
        startup_campaign_id=resolve_startup_campaign_id(authorized_ids, preferred, last_visited),
        campaign_preferences=CampaignPreferencesView(
            startup_mode=(
                STARTUP_MODE_PREFERRED_CAMPAIGN
                if preferred is not None
                else STARTUP_MODE_RESUME_LAST_VISITED
            ),
            preferred_campaign_id=preferred,
            last_visited_campaign_id=last_visited,
        ),
        campaigns=tuple(campaigns),
    )
