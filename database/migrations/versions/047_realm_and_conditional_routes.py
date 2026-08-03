"""Register the missing 'realm' location kind; add conditional-route columns

Revision ID: 047_realm_conditional_routes
Revises: 046_dungeon_state_updated_at
Create Date: 2026-08-03 10:00:00.000000

Purpose:
    Closes two Phase 5 completeness gaps found in exit review.

    1. docs/DOMAIN_MODEL.md §9.1 lists location subtypes as "plane, realm,
       continent, nation, region, settlement, district, building, dungeon,
       dungeon area, geographic feature." Revision 038 registered every one
       of those except "realm" — a plain oversight, not an intentional
       removal. Nothing in any Phase 5 planning document argues for
       dropping it. Fixed by registering it the same way the other six
       no-subtype-table location kinds were registered: a core.entity_types
       leaf under 'location'.

    2. docs/PLAN.md §9.2 and docs/architecture/DATABASE_MODEL.md §9.2 both
       list "conditional routes" among the connection kinds Phase 5 area
       connections support; revision 039 built normal/secret doors,
       passages, portals, stairs, ladders, pits, bridges, teleportation
       links, and one-way routes (is_one_way), but not conditional routes.
       This is a genuine, documented Phase 5 requirement, not later-phase
       scope creep, so it is implemented now — but only the descriptive
       half: marking a connection as conditional and recording what the
       condition is. Actually *evaluating* a condition (checking whether a
       party currently satisfies it) requires the interaction/check
       resolution Phase 6 builds and, for quest-gated conditions, the quest
       state Phase 7 builds — neither exists yet. This is the same shape
       campaign.character_conditions.source_description (Phase 4) and
       knowledge.party_discoveries.discovery_method (revision 041) already
       use for "the fact is recorded now, the causal/evaluable mechanism
       arrives later." The deferral is recorded explicitly in PLAN.md
       Phase 6's first-time obligations (already amended by this commit),
       not left as a silent gap.

Forward migration:
    - core.entity_types row: realm (parent 'location', no subtype table)
    - world.area_connections.is_conditional BOOLEAN NOT NULL DEFAULT false
    - world.area_connections.condition_description TEXT

Rollback:
    Supported. Drops both new columns and the entity_types row.

Data implications:
    Creates one entity_types row. No existing area_connections rows to
    backfill.

Locking considerations:
    ADD COLUMN ... NOT NULL DEFAULT false on an empty table does not
    rewrite it in a way that matters here (no existing rows).

See: docs/DOMAIN_MODEL.md §9.1 (location subtypes)
     docs/PLAN.md §9.2 (dungeon structures — conditional routes), Phase 6
     first-time obligations (deferred evaluation)
     docs/architecture/DATABASE_MODEL.md §9.2
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "047_realm_conditional_routes"
down_revision = "046_dungeon_state_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.entity_types: the missing 'realm' leaf
    # ==========================================================================
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, parent_entity_type_id)
        VALUES (
            'realm', 'Realm',
            (SELECT entity_type_id FROM core.entity_types WHERE code = 'location')
        )
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. world.area_connections: conditional routes (descriptive half only)
    # ==========================================================================
    op.execute("""
        ALTER TABLE world.area_connections
        ADD COLUMN is_conditional BOOLEAN NOT NULL DEFAULT false;
    """)
    op.execute("""
        ALTER TABLE world.area_connections
        ADD COLUMN condition_description TEXT;
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.is_conditional IS
        'True for a conditional route (docs/PLAN.md §9.2) — traversable only when some '
        'condition holds. Descriptive only: evaluating the condition requires '
        'interaction/check resolution (Phase 6) or quest state (Phase 7), neither of '
        'which exists yet. See PLAN.md Phase 6''s first-time obligations.';
    """)
    op.execute("""
        COMMENT ON COLUMN world.area_connections.condition_description IS
        'Free-text description of what the condition is (e.g. "requires the brass key" '
        'or "only open while the beacon is lit"). Not yet machine-evaluable — same '
        'placeholder shape as campaign.character_conditions.source_description.';
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("ALTER TABLE world.area_connections DROP COLUMN IF EXISTS condition_description;")
    op.execute("ALTER TABLE world.area_connections DROP COLUMN IF EXISTS is_conditional;")
    op.execute("DELETE FROM core.entity_types WHERE code = 'realm';")
