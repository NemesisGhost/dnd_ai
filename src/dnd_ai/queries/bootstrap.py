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
- roles: only `security.membership_roles` rows currently in force
  (`revoked_at IS NULL`, `expires_at IS NULL OR expires_at > now()`,
  `security.roles.is_active`) for that membership — the same conditions
  `resolve_access_context`'s own role-capability join already applies,
  duplicated here only because that resolver returns capability codes, not
  role codes, and the bootstrap contract wants both;
- capabilities: `AccessContext.role_capabilities` verbatim — the
  campaign-wide, role-derived capability set, never re-derived here;
- character perspectives: every `character_id` key of `AccessContext.
  character_capabilities` with a non-empty capability set — i.e. every
  character this membership currently holds *some* relationship-derived
  capability for (owner, controller, viewer, portrayer, ...), the same
  `security.membership_character_relationships` resolution
  `resolve_access_context` already performs; a relationship type mapped to
  no capabilities at all (`security.character_relationship_type_
  capabilities` has no row for it) is not offered as a selectable
  perspective, since there would be nothing authorized to do through it.

Selection defaults (no persisted preference exists yet — see this module's
own `SessionBootstrapView` docstring):

- `selected_campaign_id` is `None` with no accessible campaigns, otherwise
  the first campaign in the same deterministic `(campaign name, campaign_
  id)` ordering `get_session_bootstrap`'s own query returns rows in — an
  arbitrary but stable, audience-safe choice (never a hint about
  inaccessible campaigns, since the ordering only ever ranges over rows
  this user's own membership already authorized);
- `selected_character_id` is `None` unless exactly one character
  perspective is authorized for that campaign, in which case that one is
  the unambiguous default — never guessed among two or more.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.access import resolve_access_context


@dataclass(frozen=True)
class CharacterPerspectiveView:
    character_id: uuid.UUID
    character_name: str


@dataclass(frozen=True)
class CampaignBootstrapView:
    campaign_id: uuid.UUID
    campaign_name: str
    timeline_id: uuid.UUID | None
    timeline_name: str | None
    roles: tuple[str, ...]
    character_perspectives: tuple[CharacterPerspectiveView, ...]
    selected_character_id: uuid.UUID | None
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class SessionBootstrapView:
    """The complete, audience-safe portal-bootstrap payload for one
    authenticated user, recomputed fresh from current database state on
    every call — nothing here is cached or read from the browser-session
    row itself (docs/PLAN.md §23.4's "every request re-resolves" rule,
    applied to authorization data the same way it already applies to
    session validity).

    `selected_campaign_id` has no persisted-preference backing yet: a
    search of `security.*`/`campaign.*` for a "last selected campaign/
    character" column or table found none (Phase 13C, docs/PLAN.md §1951,
    is where the portal is expected to hold that state client-side against
    this bootstrap response, or a future increment adds real persistence);
    this module deliberately does not add speculative persistence merely to
    answer this query, and instead returns the deterministic fallback
    `get_session_bootstrap`'s own docstring describes.
    """

    user_id: uuid.UUID
    display_name: str
    selected_campaign_id: uuid.UUID | None
    campaigns: tuple[CampaignBootstrapView, ...]


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

    membership_rows = (
        connection.execute(
            text("""
                SELECT cm.campaign_membership_id, c.campaign_id, c.name AS campaign_name
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
                ORDER BY c.name, c.campaign_id
            """),
            {"user_id": user_id},
        )
        .mappings()
        .all()
    )

    campaigns: list[CampaignBootstrapView] = []
    for row in membership_rows:
        campaign_id = row["campaign_id"]
        membership_id = row["campaign_membership_id"]

        access = resolve_access_context(connection, user_id=user_id, campaign_id=campaign_id)
        if access is None:
            # The membership scan above and resolve_access_context's own
            # membership check use the same active/ended_at criteria, so
            # this should not happen in practice; skip defensively rather
            # than raise, so one inconsistent row cannot break the whole
            # bootstrap response for every other campaign.
            continue

        timeline_row = (
            connection.execute(
                text("SELECT name FROM campaign.timelines WHERE timeline_id = :timeline"),
                {"timeline": access.timeline_id},
            )
            .mappings()
            .one_or_none()
        )
        timeline_name = timeline_row["name"] if timeline_row is not None else None

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

        character_ids = [
            character_id for character_id, codes in access.character_capabilities.items() if codes
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
            character_perspectives = tuple(
                CharacterPerspectiveView(
                    character_id=character_row["entity_id"],
                    character_name=character_row["canonical_name"],
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
                timeline_id=access.timeline_id,
                timeline_name=timeline_name,
                roles=role_codes,
                character_perspectives=character_perspectives,
                selected_character_id=selected_character_id,
                capabilities=tuple(sorted(access.role_capabilities)),
            )
        )

    selected_campaign_id = campaigns[0].campaign_id if campaigns else None

    return SessionBootstrapView(
        user_id=user_id,
        display_name=display_name,
        selected_campaign_id=selected_campaign_id,
        campaigns=tuple(campaigns),
    )
