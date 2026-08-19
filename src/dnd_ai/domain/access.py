"""Effective access resolution (docs/architecture/DATABASE_MODEL.md §19.7,
docs/PLAN.md §23.3).

Centralizes campaign membership, role-derived capability, character
relationship-derived capability, and typed resource-grant resolution into
one `AccessContext` so every command and query service authorizes the same
way instead of re-deriving `security.*` joins independently
(docs/architecture/SYSTEM_ARCHITECTURE.md §5.4 — no HTTP or framework types
here). Read-only: this module never mutates state.

Deferred to later Phase 10 workstreams, per §19.7's own step list:

- step 6, party/public knowledge-derived access — depends on the knowledge
  domain's own visibility rules (docs/architecture/DATABASE_MODEL.md §14)
  and is resolved by the query layer that already has a character
  perspective, not duplicated here;
- step 8, filtering rows/fields/search/AI context — that is what callers do
  *with* an `AccessContext`, not part of resolving one;
- step 9, auditing sensitive reads — only the caller knows which read was
  sensitive; this module is called far too often (every query, every
  command) to be the right place to decide that.
"""

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from .errors import DomainAuthorizationError

_TARGET_COLUMNS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)

_GrantKey = tuple[str, uuid.UUID]


def _as_uuid(value: object) -> uuid.UUID:
    assert isinstance(value, uuid.UUID)
    return value


def _as_str(value: object) -> str:
    assert isinstance(value, str)
    return value


@dataclass(frozen=True)
class AccessContext:
    """A resolved snapshot of one user's effective access to one campaign
    timeline, per docs/architecture/DATABASE_MODEL.md §19.7 steps 1-7.

    Resolve fresh per request rather than caching across requests — roles,
    relationships, and grants can change between calls, and nothing here
    subscribes to invalidation.
    """

    user_id: uuid.UUID
    campaign_id: uuid.UUID
    campaign_membership_id: uuid.UUID
    timeline_id: uuid.UUID
    role_capabilities: frozenset[str]
    character_capabilities: dict[uuid.UUID, frozenset[str]]
    grant_effects: dict[_GrantKey, dict[str, str]] = field(repr=False)

    def has_capability(
        self,
        capability_code: str,
        *,
        character_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        knowledge_item_id: uuid.UUID | None = None,
        quest_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        event_id: uuid.UUID | None = None,
    ) -> bool:
        """Deny-by-default: True only if a role, character relationship, or
        active `allow` resource grant supplies the capability, and no
        matching active `deny` resource grant overrides it (§19.6 — an
        explicit deny overrides an allow at the same or broader path).

        At most one resource-target keyword may be supplied — a caller
        checking a character-scoped capability passes `character_id`; one
        checking any other protected resource passes exactly one of the
        others. Passing none checks only role/character-relationship
        capabilities with no resource grant involved.
        """
        targets: dict[str, uuid.UUID | None] = {
            "character_id": character_id,
            "entity_id": entity_id,
            "knowledge_item_id": knowledge_item_id,
            "quest_id": quest_id,
            "session_id": session_id,
            "event_id": event_id,
        }
        supplied = [
            (field_name, value) for field_name, value in targets.items() if value is not None
        ]
        if len(supplied) > 1:
            raise ValueError("has_capability accepts at most one resource target")

        baseline = capability_code in self.role_capabilities
        if character_id is not None:
            baseline = baseline or capability_code in self.character_capabilities.get(
                character_id, frozenset()
            )

        if not supplied:
            return baseline

        field_name, target_id = supplied[0]
        effect = self.grant_effects.get((field_name, target_id), {}).get(capability_code)
        if effect == "deny":
            return False
        if effect == "allow":
            return True
        return baseline

    def resource_grant_targets(
        self, capability_code: str, field_name: str
    ) -> tuple[frozenset[uuid.UUID], frozenset[uuid.UUID]]:
        """The resource IDs of `field_name` (one of `_TARGET_COLUMNS`) for
        which an active, resolved resource grant sets `capability_code` to
        `deny`/`allow` respectively.

        `has_capability()` resolves deny-overrides-allow-overrides-baseline
        for one resource at a time — the right shape for a single-resource
        endpoint, but a *list* endpoint (many rows, one baseline capability
        check, individually-targetable resource grants layered on top) has
        no single resource to pass it. Calling `has_capability()` once per
        row would work but means re-deriving the same `grant_effects` scan
        per row; this instead exposes the two sets once, so a caller can
        push per-row visibility into a SQL `WHERE`/`CASE` (denied IDs
        excluded outright, allowed IDs included regardless of the row's own
        baseline) without loading unfiltered rows just to discard them
        after the fact. A row's own baseline — the role/character-
        relationship check alone, with no resource target — is still the
        caller's own responsibility, exactly as it is for `has_capability()`
        when no resource-target keyword is supplied.
        """
        if field_name not in _TARGET_COLUMNS:
            raise ValueError(f"{field_name!r} is not a resource-grant target column")
        denied = frozenset(
            target_id
            for (target_field, target_id), effects in self.grant_effects.items()
            if target_field == field_name and effects.get(capability_code) == "deny"
        )
        allowed = frozenset(
            target_id
            for (target_field, target_id), effects in self.grant_effects.items()
            if target_field == field_name and effects.get(capability_code) == "allow"
        )
        return denied, allowed


def resolve_user_by_external_identity(
    connection: Connection, *, issuer: str, subject: str
) -> uuid.UUID | None:
    """Resolve an OIDC (issuer, subject) pair to its linked `security.users`
    row (docs/architecture/DATABASE_MODEL.md §19.1 step 1). Returns None for
    an unknown or revoked identity, or one linked to a user whose own
    lifecycle status code is not `'active'` — the caller decides how to
    respond (for example, provisioning a new user on first login is an
    application command, not this lookup). A revoked external identity or
    a non-active (inactive/archived/deleted) user must not authenticate
    even though the row itself still exists.

    Checks `core.lifecycle_statuses.code = 'active'` only — deliberately
    never that lookup row's own `is_active` flag. Per revision
    `080_security_identity_and_access.py`'s own "Deliberate scoping
    decisions" (and docs/architecture/DATABASE_MODEL.md §19's account of
    it), `is_active` on a lookup table means whether that *value* is
    currently offered for *new* assignment — a different question from
    whether a user already assigned `'active'` should retroactively stop
    counting as one, which is exactly why that same revision's own
    `security.campaign_has_access_manager()` deliberately excludes
    `core.lifecycle_statuses.is_active` from its otherwise-analogous
    `membership_statuses`/`capabilities` `is_active` checks. Extending
    that semantics here would be the same scope creep that decision
    already declined."""
    value = connection.execute(
        text("""
            SELECT ei.user_id
            FROM security.external_identities ei
            JOIN security.users u ON u.user_id = ei.user_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE ei.issuer = :issuer
              AND ei.subject = :subject
              AND ei.revoked_at IS NULL
              AND ls.code = 'active'
        """),
        {"issuer": issuer, "subject": subject},
    ).scalar()
    return _as_uuid(value) if value is not None else None


def foundry_issuer(external_system_id: uuid.UUID) -> str:
    """The synthetic `security.external_identities.issuer` value that scopes
    a Foundry-side user id to one registered `integration.external_systems`
    row (docs/architecture/DATABASE_MODEL.md §19.1). The single source of
    truth for this format — `dnd_ai.commands.integration.
    link_foundry_identity` (which writes the mapping) and
    `resolve_foundry_system_user_id` below (which reads it back during
    authentication) both call this rather than each formatting their own
    copy of the string, so the two can never drift apart."""
    return f"foundry:{external_system_id}"


def hash_foundry_system_key(raw_key: str) -> str:
    """sha256 hex digest of a Foundry-adapter system key. Same rehash-and-
    compare pattern as `dnd_ai.commands.campaign_invitations`'
    `invitation_token_hash` — that module's own docstring justifies plain
    SHA-256 over a slow password-hashing KDF: the input is 256 bits of
    `secrets.token_urlsafe` CSPRNG entropy, never attacker-guessable text,
    so there is nothing here for a slow KDF to protect against that a fast,
    indexable hash doesn't already close off. Shared by `dnd_ai.commands.
    integration.issue_foundry_system_key` (which mints and stores the hash)
    and `resolve_foundry_system_user_id` below (which recomputes it from a
    presented key and compares by lookup) so both sides always agree on
    exactly how a raw key becomes its stored hash."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def resolve_foundry_system_user_id(
    connection: Connection, *, external_system_id: uuid.UUID, raw_key: str, foundry_user_id: str
) -> uuid.UUID | None:
    """Authenticates a Foundry-adapter request as "system external_system_id,
    acting for Foundry user foundry_user_id" and resolves it to a platform
    `security.users.user_id` — the Foundry-adapter counterpart to
    `resolve_user_by_external_identity` above, used by `dnd_ai.api.auth.
    get_authenticated_user_id` so every existing command/query endpoint
    already wired to that one dependency becomes reachable by a Foundry
    adapter with no per-route changes, under the exact same
    `require_campaign_capability` authorization every other caller goes
    through.

    Two checks, both required: (1) raw_key, rehashed, must match the
    active `integration.external_systems.system_key_hash` for
    external_system_id, and that row's own `is_active` must be true — a
    caller cannot authenticate as a system whose credential was never
    issued, was rotated away, or whose whole external-system registration
    has been deactivated; (2) the resulting synthetic issuer
    (`foundry_issuer`) plus foundry_user_id as subject must resolve via
    `resolve_user_by_external_identity` to an active platform user — the
    same `link_foundry_identity`-established mapping workstream 1 built.
    Returns None, uniformly, for every failure mode (unknown system,
    inactive system, wrong key, unlinked or inactive Foundry user)
    deliberately without distinguishing which — the same fail-closed,
    non-disclosing contract `resolve_user_by_external_identity` already
    establishes for its own callers, so `get_authenticated_user_id` can
    raise one uniform `UnauthorizedError` regardless of cause."""
    key_hash = hash_foundry_system_key(raw_key)
    matched = connection.execute(
        text("""
            SELECT 1 FROM integration.external_systems
            WHERE external_system_id = :system AND system_key_hash = :hash AND is_active
        """),
        {"system": external_system_id, "hash": key_hash},
    ).scalar()
    if matched is None:
        return None
    return resolve_user_by_external_identity(
        connection, issuer=foundry_issuer(external_system_id), subject=foundry_user_id
    )


class UnauthorizedTimelineError(DomainAuthorizationError):
    """Raised by `resolve_access_context()` when a caller-supplied
    `timeline_id` is not the campaign's own pinned timeline. A domain
    error, not an HTTP concern (docs/DEVELOPMENT.md §9) — but one that
    carries the supplied, campaign, and canonical timeline IDs in its own
    message (`str(self)`), which is exactly the kind of detail
    `DomainAuthorizationError.safe_message` exists to withhold from an API
    client while still leaving it available for server-side logs. Every
    caller of `resolve_access_context()`, present and future, gets the same
    non-disclosing 404 mapping automatically via `dnd_ai.api.errors`'
    `SafeMessageError` handler — no per-endpoint try/except required."""


def resolve_access_context(
    connection: Connection,
    *,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID | None = None,
) -> AccessContext | None:
    """Resolve §19.7 steps 2-7 into one `AccessContext`, or None if the user
    has no active, authorizing membership in the campaign (suspended,
    revoked, departed, or never-invited all resolve to None — a bare
    membership existing is not enough).

    Timeline scope rule: `campaign.campaigns.timeline_id` is a single
    non-nullable column — "the timeline this campaign is played on"
    (docs/architecture/DATABASE_MODEL.md's campaign.campaigns entry) — and
    nothing in the domain model gives one campaign more than one active
    timeline to resolve access against. §19.2 places any *narrower* timeline
    scoping on the individual relationship/grant row that needs it ("the
    membership belongs to the campaign's timeline through campaign.
    campaigns; narrower timeline scope is placed on the particular
    relationship or grant that requires it"), not on request-level
    substitution of a different timeline entirely. So the only valid value
    for `timeline_id` here is the campaign's own pinned timeline — not an
    ancestor, not a branch/descendant, not a timeline from another world.
    Passing `None` resolves it from the campaign automatically; passing the
    campaign's own timeline explicitly is accepted as a caller's
    self-check; passing anything else raises `UnauthorizedTimelineError`
    rather than silently using it to select timeline-scoped character
    capabilities or resource grants (finding 2) — a branch timeline is
    rejected exactly like an unrelated same-world or different-world one,
    since none of them are the campaign's own timeline.
    """
    membership_id = connection.execute(
        text("""
            SELECT cm.campaign_membership_id
            FROM security.campaign_memberships cm
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = cm.membership_status_id
            WHERE cm.campaign_id = :campaign_id
              AND cm.user_id = :user_id
              AND cm.ended_at IS NULL
              AND ms.code = 'active'
              AND ms.is_active
        """),
        {"campaign_id": campaign_id, "user_id": user_id},
    ).scalar()
    if membership_id is None:
        return None
    membership_id = _as_uuid(membership_id)

    campaign_timeline = connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :campaign_id"),
        {"campaign_id": campaign_id},
    ).scalar()
    if campaign_timeline is None:
        raise ValueError(f"campaign {campaign_id} does not exist")
    campaign_timeline_id = _as_uuid(campaign_timeline)

    if timeline_id is not None and timeline_id != campaign_timeline_id:
        raise UnauthorizedTimelineError(
            f"timeline {timeline_id} is not campaign {campaign_id}'s own timeline "
            f"({campaign_timeline_id}) — resolve_access_context only resolves access "
            "for a campaign's own pinned timeline; see its docstring for the rule."
        )

    role_capabilities = frozenset(
        _as_str(code)
        for code in connection.execute(
            text("""
                SELECT DISTINCT cap.code
                FROM security.membership_roles mr
                JOIN security.roles r ON r.role_id = mr.role_id
                JOIN security.role_capabilities rc ON rc.role_id = r.role_id
                JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
                WHERE mr.campaign_membership_id = :membership_id
                  AND mr.revoked_at IS NULL
                  AND (mr.expires_at IS NULL OR mr.expires_at > now())
                  AND r.is_active
                  AND cap.is_active
            """),
            {"membership_id": membership_id},
        ).scalars()
    )

    character_capabilities: dict[uuid.UUID, set[str]] = {}
    for row in connection.execute(
        text("""
            SELECT mcr.character_id, cap.code
            FROM security.membership_character_relationships mcr
            JOIN security.character_relationship_type_capabilities rtc
              ON rtc.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN security.capabilities cap ON cap.capability_id = rtc.capability_id
            WHERE mcr.campaign_membership_id = :membership_id
              AND mcr.revoked_at IS NULL
              AND (mcr.expires_at IS NULL OR mcr.expires_at > now())
              AND (mcr.timeline_id IS NULL OR mcr.timeline_id = :timeline_id)
              AND cap.is_active
        """),
        {"membership_id": membership_id, "timeline_id": campaign_timeline_id},
    ).mappings():
        character_id = _as_uuid(row["character_id"])
        character_capabilities.setdefault(character_id, set()).add(_as_str(row["code"]))

    grant_effects: dict[_GrantKey, dict[str, str]] = {}
    target_column_list = ", ".join(f"rg.{column}" for column in _TARGET_COLUMNS)
    for row in connection.execute(
        text(f"""
            SELECT {target_column_list}, cap.code AS capability_code, rg.effect
            FROM security.resource_grants rg
            JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
            WHERE rg.campaign_id = :campaign_id
              AND rg.revoked_at IS NULL
              AND (rg.expires_at IS NULL OR rg.expires_at > now())
              AND (rg.timeline_id IS NULL OR rg.timeline_id = :timeline_id)
              AND cap.is_active
              AND (
                    rg.grantee_campaign_membership_id = :membership_id
                    OR rg.grantee_access_group_id IN (
                        SELECT agm.access_group_id
                        FROM security.access_group_memberships agm
                        WHERE agm.campaign_membership_id = :membership_id
                          AND agm.removed_at IS NULL
                    )
                  )
        """),
        {
            "campaign_id": campaign_id,
            "timeline_id": campaign_timeline_id,
            "membership_id": membership_id,
        },
    ).mappings():
        target_field = next(column for column in _TARGET_COLUMNS if row[column] is not None)
        key = (target_field, _as_uuid(row[target_field]))
        capability_code = _as_str(row["capability_code"])
        bucket = grant_effects.setdefault(key, {})
        if bucket.get(capability_code) == "deny":
            continue
        bucket[capability_code] = _as_str(row["effect"])

    return AccessContext(
        user_id=user_id,
        campaign_id=campaign_id,
        campaign_membership_id=membership_id,
        timeline_id=campaign_timeline_id,
        role_capabilities=role_capabilities,
        character_capabilities={
            character_id: frozenset(codes) for character_id, codes in character_capabilities.items()
        },
        grant_effects=grant_effects,
    )
