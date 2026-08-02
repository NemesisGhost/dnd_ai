"""Shared characters, NPCs, and player characters

Revision ID: 017_characters
Revises: 016_close_ruleset_refs
Create Date: 2026-08-02 15:00:00.000000

Purpose:
    Delivers the character hierarchy from docs/PLAN.md §7.1:

        core.entities
            -> character.characters
                -> character.npcs
                -> character.player_characters

    This is Phase 4's most consequential first-time obligation: the first
    REAL class-table inheritance subtype chain. Phase 2 could only build and
    test core.enforce_entity_subtype() abstractly, against a synthetic table
    created inside a test transaction (see docs/PHASE2_VERIFICATION.md,
    "Partially met: subtype consistency"). This revision is where that
    mechanism either holds up against production shape or doesn't.

    character.characters is deliberately NOT abstract: DATABASE_MODEL.md §7.1
    and PLAN.md §7.1 both note that future subtypes (companions, familiars,
    summons, special creature actors) reuse character.characters directly
    without also being an NPC or a player character. The entity_types row
    for "character" is therefore directly instantiable, not merely a shared
    ancestor.

Forward migration:
    - core.entity_types rows: character, npc, player_character
    - character.characters
    - character.npcs
    - character.player_characters
    - AFTER INSERT OR UPDATE triggers on all three, wired to the shared
      core.enforce_entity_subtype() from Phase 2

Rollback:
    Supported. Drops all three tables and the three entity_types rows.

Data implications:
    Creates three entity_types rows, no character rows.

Locking considerations:
    None. All tables are new and empty.

Deferred to later phases:
    - character.characters.origin_location_id (Phase 5, which owns
      world.locations — nothing to reference yet).
    - Full NPC portrayal/simulation apparatus (npc_portrayal_profiles,
      npc_characteristics, npc_goals, npc_routines, npc_preferences,
      npc_boundaries, npc_disclosure_rules, npc_agent_assignments) and
      character.character_controllers / security.character_permissions —
      Phase 4's own exit criteria require only that NPC and PC share a
      mechanical model and that the subtype chain is sound; the AI- and
      control-facing apparatus belongs with Phase 10, which actually builds
      the AI agents and Discord mapping it serves.
    - campaign.party_memberships.member_entity_id enforcing "must be a
      character" — a separate, small revision immediately following this
      one, per Phase 3's own documented deferral.

See: docs/PLAN.md §7.1 (character hierarchy), §7.2 (shared character data),
     Phase 4 exit criteria and first-time obligations
     docs/architecture/DATABASE_MODEL.md §7.1
     docs/DATABASE_CONVENTIONS.md §7.4 (subtype consistency)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "017_characters"
down_revision = "016_close_ruleset_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. core.entity_types rows
    # ==========================================================================
    op.execute("""
        INSERT INTO core.entity_types (code, display_name, required_subtype_table)
        VALUES ('character', 'Character', 'character.characters')
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, parent_entity_type_id, required_subtype_table)
        VALUES (
            'npc', 'NPC',
            (SELECT entity_type_id FROM core.entity_types WHERE code = 'character'),
            'character.npcs'
        )
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO core.entity_types
            (code, display_name, parent_entity_type_id, required_subtype_table)
        VALUES (
            'player_character', 'Player Character',
            (SELECT entity_type_id FROM core.entity_types WHERE code = 'character'),
            'character.player_characters'
        )
        ON CONFLICT (code) DO NOTHING;
    """)

    # ==========================================================================
    # 2. character.characters
    # ==========================================================================
    # character_id is the parent entity's own UUID, not a new one (conventions
    # §7.1 class-table inheritance) — REFERENCES core.entities directly as the
    # primary key rather than a DEFAULT gen_random_uuid().
    #
    # size_category is a fixed, universal vocabulary (the six D&D size
    # categories are constant across virtually every edition and every
    # ruleset this platform is likely to model), unlike canon/lifecycle
    # status or ability names, which genuinely vary by ruleset or need GM
    # extension. A CHECK is used rather than a lookup table for exactly that
    # reason — conventions' "lookup tables over ENUM" guidance targets
    # extensible vocabularies, and this one is not.
    op.execute("""
        CREATE TABLE character.characters (
            character_id   UUID PRIMARY KEY
                           REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            species_id     UUID NOT NULL
                           REFERENCES rules.species(species_id) ON DELETE RESTRICT,
            size_category  TEXT NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_characters_size_category CHECK (
                size_category IN ('tiny', 'small', 'medium', 'large', 'huge', 'gargantuan')
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.characters IS
        'Identity-level mechanical data shared by every character: species and size. '
        'NPCs and player characters both extend this row rather than duplicating it '
        '(docs/PLAN.md §7.1). origin_location_id arrives in Phase 5 once '
        'world.locations exists.';
    """)
    op.execute("""
        CREATE TRIGGER tr_characters_set_updated_at
        BEFORE UPDATE ON character.characters
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_characters_species_id ON character.characters (species_id);")
    op.execute("""
        CREATE TRIGGER tr_characters_enforce_subtype
        AFTER INSERT OR UPDATE ON character.characters
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('character_id');
    """)

    # ==========================================================================
    # 3. character.npcs
    # ==========================================================================
    # Deliberately minimal: the portrayal/simulation apparatus (§8 in PLAN.md)
    # is a Phase 10 concern (see this revision's docstring). All this table
    # asserts is that an entity is an NPC.
    op.execute("""
        CREATE TABLE character.npcs (
            npc_id      UUID PRIMARY KEY
                       REFERENCES character.characters(character_id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.npcs IS
        'Marks a character as an NPC. Portrayal, goals, routines, and other simulation '
        'apparatus (docs/PLAN.md §8) are deferred to Phase 10, which builds the AI '
        'agents that consume them.';
    """)
    op.execute("""
        CREATE TRIGGER tr_npcs_set_updated_at
        BEFORE UPDATE ON character.npcs
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_npcs_enforce_subtype
        AFTER INSERT OR UPDATE ON character.npcs
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('npc_id');
    """)

    # ==========================================================================
    # 4. character.player_characters
    # ==========================================================================
    # player_user_id is basic identity (who plays this character), not a
    # control assignment — character.character_controllers, which handles
    # temporary/session-specific control handoffs, is deferred to Phase 10
    # alongside the rest of the control apparatus.
    op.execute("""
        CREATE TABLE character.player_characters (
            player_character_id  UUID PRIMARY KEY
                                 REFERENCES character.characters(character_id)
                                 ON DELETE CASCADE,
            player_user_id       UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        COMMENT ON TABLE character.player_characters IS
        'Marks a character as player-controlled. player_user_id is basic ownership '
        'identity; timeline- or session-scoped control handoffs '
        '(character.character_controllers) are deferred to Phase 10.';
    """)
    op.execute("""
        CREATE TRIGGER tr_player_characters_set_updated_at
        BEFORE UPDATE ON character.player_characters
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_player_characters_player_user_id "
        "ON character.player_characters (player_user_id) WHERE player_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_player_characters_enforce_subtype
        AFTER INSERT OR UPDATE ON character.player_characters
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_subtype('player_character_id');
    """)


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS character.player_characters;")
    op.execute("DROP TABLE IF EXISTS character.npcs;")
    op.execute("DROP TABLE IF EXISTS character.characters;")
    op.execute("""
        DELETE FROM core.entity_types WHERE code IN ('npc', 'player_character', 'character');
    """)
