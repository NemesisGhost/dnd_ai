"""The Phase 15 route manifest: every operation of the application, classified.

`classify(app)` walks the application's OpenAPI document and puts every (method, template)
into exactly one class:

- `gm` — a route that needs a campaign capability a plain member does not hold. `canon.edit`
  is the GM authoring and operating capability; `access.manage` is campaign access
  administration. A member without the capability is refused (403), an outsider finds nothing
  (404), and no Foundry device or machine principal gets through.
- `member_read` — a read open to every campaign member (`campaign.view`) whose content is
  filtered for the player; the guard shows it is *not* refused to a player and not found by an
  outsider.
- `world` — a world-scoped authoring route (the caller needs authority over the world, not a
  campaign membership).
- `out_of_scope` — public, authentication, account, device, platform-level or non-Phase-15
  routes, each with the reason. They are deliberately not swept into the GM guard.

A route that matches no rule fails `test_every_route_is_classified`, so a route added later
cannot silently escape the guard. `PHASE15` marks the families Phase 15 added or completed.
"""

import re
from dataclasses import dataclass

CAMPAIGN = "/campaigns/{campaign_id}"

# Families: (segment after the campaign id) -> (family, capability, introduced or completed in Phase 15)
_GM_FAMILIES: dict[str, tuple[str, str, bool]] = {
    "authoring": (
        "authoring (world content, characters, builds, dungeons, relationships, routes, NPC portrayal, item definitions, items, encounter preparation, sources)",
        "canon.edit",
        True,
    ),
    "clock": ("campaign clock", "canon.edit", True),
    "world-times": ("world-time points", "canon.edit", True),
    "calendars": ("calendars", "canon.edit", True),
    "parties": ("parties, party membership, party inventory", "canon.edit", True),
    "sessions": ("session definition, participation, start, end, log", "canon.edit", True),
    "events": ("events and corrections", "canon.edit", True),
    "quests": ("quest runtime and progress", "canon.edit", True),
    "knowledge": ("knowledge runtime and audience", "canon.edit", True),
    "dungeon-areas": ("dungeon state", "canon.edit", True),
    "organizations": ("organization state", "canon.edit", True),
    "relationships": ("relationship kernel", "canon.edit", True),
    "items": ("item instances, custody, operations", "canon.edit", True),
    "encounters": ("encounter preparation and operation", "canon.edit", True),
    "sources": ("sources", "canon.edit", True),
    "entities": ("lifecycle, publication, provenance, revisions", "canon.edit", True),
    "review-queue": ("review queue", "canon.edit", True),
    "travel": ("routes and travel", "canon.edit", True),
    "characters": ("character state operations", "canon.edit", False),
    "checks": ("check resolution", "canon.edit", False),
    "interactions": ("interactions", "canon.edit", False),
    "invitations": ("campaign invitations", "access.manage", False),
    "memberships": ("memberships and roles", "access.manage", False),
    "character-relationships": ("character-relationship administration", "access.manage", True),
    "resource-grants": ("resource grants", "access.manage", False),
    "access-groups": ("access groups", "access.manage", False),
    "access-group-memberships": ("access-group membership", "access.manage", False),
    "access-overview": ("access overview", "access.manage", False),
    "eligible-accounts": ("eligible-account lookup", "access.manage", False),
    "members": ("member access preview", "access.manage", False),
    "audit-history": ("audit history (privacy-redacted)", "access.manage", True),
    "foundry": ("Foundry pairing administration", "access.manage", False),
    "integration": ("integration administration", "canon.edit", False),
    "update": ("campaign administration", "canon.edit", False),
    "archive": ("campaign administration", "canon.edit", False),
    "reactivate": ("campaign administration", "canon.edit", False),
    "settings": ("campaign administration", "canon.edit", False),
}

# Reads open to every member: each is player-safe (content is filtered for the caller).
_MEMBER_READS = frozenset(
    {
        f"{CAMPAIGN}/characters/{{character_id}}",
        f"{CAMPAIGN}/characters/{{character_id}}/inventory",
        f"{CAMPAIGN}/characters/{{character_id}}/sheet",
        f"{CAMPAIGN}/clock",
        f"{CAMPAIGN}/dungeon-areas/{{dungeon_area_id}}",
        f"{CAMPAIGN}/encounters/{{encounter_id}}",
        f"{CAMPAIGN}/knowledge",
        f"{CAMPAIGN}/knowledge/{{knowledge_item_id}}",
        f"{CAMPAIGN}/organizations/{{organization_id}}",
        f"{CAMPAIGN}/organizations/{{organization_id}}/members",
        f"{CAMPAIGN}/parties",
        f"{CAMPAIGN}/parties/{{party_id}}",
        f"{CAMPAIGN}/quests",
        f"{CAMPAIGN}/quests/{{quest_id}}",
        f"{CAMPAIGN}/relationships/{{relationship_id}}",
        f"{CAMPAIGN}/sessions",
        f"{CAMPAIGN}/sessions/{{session_id}}",
        f"{CAMPAIGN}/summary",
    }
)
# Everything under /world/ is the world explorer: player-safe reads.
_WORLD_EXPLORER = re.compile(r"^/campaigns/\{campaign_id\}/world/")

# Routes a paired Foundry device is allowed to use (documented scopes); the GM guard excludes
# them from the "no Foundry device" check, never from the player/outsider checks.
FOUNDRY_PERMITTED = frozenset(
    {
        ("POST", f"{CAMPAIGN}/integration/foundry/combat-sync"),
    }
)

_WORLD_ROUTES = frozenset(
    {
        ("GET", "/worlds/{world_id}/calendars"),
        ("POST", "/worlds/{world_id}/calendars"),
    }
)

_OUT_OF_SCOPE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/(healthz|readyz)$"), "health probes (public)"),
    (re.compile(r"^/rulesets$"), "ruleset catalogue (any signed-in user)"),
    (re.compile(r"^/auth/"), "authentication and the caller's own session and preferences"),
    (re.compile(r"^/admin/accounts"), "platform administration (Phase 13), own guard"),
    (re.compile(r"^/campaign-invitations/"), "invitation acceptance and onboarding (token holder)"),
    (re.compile(r"^/foundry/"), "Foundry device pairing and tokens (own principal)"),
    (re.compile(r"^/worlds(/|$)"), "world and timeline administration (Phase 14), own tests"),
    (re.compile(r"^/campaigns$"), "campaign creation (world authority), own tests"),
    (re.compile(r"^/campaigns/archived$"), "the caller's own archived campaigns"),
    (
        re.compile(r"^/campaigns/\{campaign_id\}/(ai|reference-corpus)/"),
        "AI orchestration and the reference corpus (Phase 12): member-level routes with "
        "their own capability checks and tests",
    ),
    (
        re.compile(
            r"^/campaigns/\{campaign_id\}/integration/external-systems/\{external_system_id\}/sync-state$"
        ),
        "integration sync-state view (Phase 11, `campaign.view`): own tests",
    ),
    (
        re.compile(r"^/campaigns/\{campaign_id\}/foundry/pairing-codes$"),
        "Foundry pairing-code issue: a member pairs their own device (own tests)",
    ),
]


@dataclass(frozen=True)
class Entry:
    method: str
    template: str
    klass: str  # gm | member_read | world | out_of_scope
    family: str
    capability: str
    phase15: bool
    mutating: bool

    @property
    def insufficient_authority(self) -> int:
        """What a caller without the authority sees: a campaign member without the capability is
        refused (403); a world non-member and an outsider find nothing (404)."""
        return 404 if self.klass == "world" else 403


def classify(openapi_paths: dict) -> tuple[list[Entry], list[tuple[str, str]]]:
    """`(entries, unclassified)` for every get/post/put/patch/delete operation."""
    entries: list[Entry] = []
    unclassified: list[tuple[str, str]] = []
    for template, operations in sorted(openapi_paths.items()):
        for method in sorted(
            m for m in operations if m in ("get", "post", "put", "patch", "delete")
        ):
            method_name = method.upper()
            mutating = method_name != "GET"
            if (method_name, template) in _WORLD_ROUTES:
                entries.append(
                    Entry(
                        method_name,
                        template,
                        "world",
                        "calendars (world authoring)",
                        "world authority",
                        True,
                        mutating,
                    )
                )
                continue
            reason = next((why for rx, why in _OUT_OF_SCOPE if rx.match(template)), None)
            if reason is not None:
                entries.append(
                    Entry(method_name, template, "out_of_scope", reason, "-", False, mutating)
                )
                continue
            if not template.startswith(CAMPAIGN + "/"):
                unclassified.append((method_name, template))
                continue
            if method_name == "GET" and (
                template in _MEMBER_READS or _WORLD_EXPLORER.match(template)
            ):
                entries.append(
                    Entry(
                        method_name,
                        template,
                        "member_read",
                        "player-safe read",
                        "campaign.view",
                        True,
                        False,
                    )
                )
                continue
            segment = template[len(CAMPAIGN) + 1 :].split("/", 1)[0]
            family = _GM_FAMILIES.get(segment)
            if family is None:
                unclassified.append((method_name, template))
                continue
            name, capability, phase15 = family
            entries.append(Entry(method_name, template, "gm", name, capability, phase15, mutating))
    return entries, unclassified
