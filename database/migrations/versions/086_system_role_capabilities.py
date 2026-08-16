"""Seed default capabilities for gm/assistant_gm/player/observer

Revision ID: 086_system_role_capabilities
Revises: 085_campaign_owner_capabilities
Create Date: 2026-08-16 15:00:00.000000

Purpose:
    Fixes a High-severity functional gap alongside the Critical timeline-
    reuse authorization fix (docs/PLAN.md's own workstream 30/31 entries
    have the full narrative): migration 080 seeded `security.roles` with
    the 7 system-template role codes as vocabulary only, and migration 085
    extended exactly one of them — `campaign_owner` — with a real
    capability set. The other Phase 10-relevant roles (`gm`, `assistant_
    gm`, `player`, `observer`) still carried zero `security.
    role_capabilities` rows: a caller could `assign_membership_role` any
    of them through the existing API and nothing would happen — the role
    exists, is "assignable," and grants no capability at all.
    `tests/scenario/test_vertical_slice_api.py` had masked this the same
    way it once masked `campaign_owner`'s own gap: by creating campaign-
    scoped, test-only roles with hand-picked `security.role_capabilities`
    rows written directly to the database for its player/observer
    participants, instead of assigning the seeded system-template roles
    through `POST .../memberships/{id}/roles` the way a real deployment
    would have to.

    Scope is deliberately the four roles Phase 10's own vertical slice
    names a participant kind for — `gm` (an assignable narrative-authority
    role distinct from `campaign_owner`, for a human helping run the game
    who is not the campaign's own creator/administrator), `assistant_gm`,
    `player`, and `observer`. `import_reviewer` and `rules_curator` remain
    vocabulary-only, deliberately: their own capabilities
    (`import.approve`, `rules_source.manage`) belong to later phases
    (import tooling — Phase 14; the rules corpus — Phase 12) that have no
    command layer yet to validate a default mapping against, the identical
    "no command layer yet to validate it against" reasoning migration 080
    itself gave for leaving the whole matrix unseeded in the first place.

    `player`/`observer` get `campaign.view` only — campaign membership
    proves you may see the campaign at all; everything character-specific
    (viewing a particular character's detail, knowledge, or state) is
    deliberately left to `security.membership_character_relationships`/
    `.resource_grants`, the per-relationship/per-resource mechanisms this
    codebase already has for exactly that finer scoping (docs/PLAN.md
    workstream 25's own resource-grant-target extension), not duplicated
    onto the role. `gm`/`assistant_gm` get `canon.edit`/`character.
    view_full` in addition — real narrative and character-visibility
    authority — but never `access.manage`: that capability stays
    exclusive to `campaign_owner` (and any role a campaign's own owner
    explicitly grants it to later, one row at a time, through `security.
    role_capabilities`), never bundled into an "ordinary" assignable role
    by a migration's own default seed. `gm` additionally gets `character.
    view_knowledge` (the capability `dnd_ai.api.access.
    resolve_party_perspective` names for authorizing a human to view
    fictional knowledge through a specific party's eyes) — a first-cut,
    conservative choice: `assistant_gm` does not, so the two roles remain
    meaningfully distinct rather than identical twins; a later workstream
    with a concrete need can extend either mapping the same way this one
    extends migration 080's.

Forward migration:
    INSERT `security.role_capabilities` rows for the four system-template
    roles above, `ON CONFLICT (role_id, capability_id) DO NOTHING`
    (matching migration 080/085's own seeding idiom for this table):
        gm:           campaign.view, canon.edit, character.view_full,
                      character.view_knowledge
        assistant_gm: campaign.view, canon.edit, character.view_full
        player:       campaign.view
        observer:     campaign.view

Rollback:
    Supported. Deletes exactly the rows this revision adds, by role code
    and capability code together — never a wildcard across every role
    using any of these capabilities, and never touching `campaign_owner`'s
    own row set (migration 085).

Data implications:
    New lookup-junction rows on an existing table only. No existing row is
    altered. Every campaign that has already assigned `gm`/`assistant_gm`/
    `player`/`observer` to a membership (necessarily a no-op grant until
    now, since the role carried no capability) gains the documented
    default the moment this migration commits — the same "shared system-
    template role, every existing assignment benefits automatically"
    property migration 085 already established for `campaign_owner`.

Locking considerations:
    Ordinary row-level `INSERT`s against `security.role_capabilities`. No
    table rewrite, no new object.

See: database/migrations/versions/080_security_identity_and_access.py
     (role_capabilities' own seeding idiom, and the "a later Phase 10
     workstream owns the rest" scoping note this migration follows through
     on for gm/assistant_gm/player/observer specifically)
     database/migrations/versions/085_campaign_owner_capabilities.py
     (the identical fix, applied to campaign_owner first)
     src/dnd_ai/commands/access_grants.py, dnd_ai.commands.memberships
     (membership_character_relationships/resource_grants — the mechanisms
     player/observer's own character-specific powers still come from)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "086_system_role_capabilities"
down_revision = "085_campaign_owner_capabilities"
branch_labels = None
depends_on = None

_ROLE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "gm": ("campaign.view", "canon.edit", "character.view_full", "character.view_knowledge"),
    "assistant_gm": ("campaign.view", "canon.edit", "character.view_full"),
    "player": ("campaign.view",),
    "observer": ("campaign.view",),
}


def upgrade() -> None:
    """Apply the migration."""

    for role_code, capability_codes in _ROLE_CAPABILITIES.items():
        for capability_code in capability_codes:
            op.execute(f"""
                INSERT INTO security.role_capabilities (role_id, capability_id)
                SELECT r.role_id, c.capability_id
                FROM security.roles r, security.capabilities c
                WHERE r.code = '{role_code}' AND r.campaign_id IS NULL
                  AND c.code = '{capability_code}'
                ON CONFLICT (role_id, capability_id) DO NOTHING;
            """)


def downgrade() -> None:
    """Revert the migration."""

    for role_code, capability_codes in _ROLE_CAPABILITIES.items():
        for capability_code in capability_codes:
            op.execute(f"""
                DELETE FROM security.role_capabilities rc
                USING security.roles r, security.capabilities c
                WHERE rc.role_id = r.role_id AND rc.capability_id = c.capability_id
                  AND r.code = '{role_code}' AND r.campaign_id IS NULL
                  AND c.code = '{capability_code}';
            """)
