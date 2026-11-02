"""Add the NPC detail level and versioned portrayal profiles

Revision ID: 131_npc_portrayal
Revises: 130_routes
Create Date: 2026-10-07 09:00:00.000000

Purpose:
    Phase 15 checkpoint 15.3A-3 (decision D-21, option a). An NPC gets one versioned
    portrayal profile (how to play them: voice, speech style, vocabulary, mannerisms, emotional
    baseline, conversational habits, topics avoided, disclosure boundaries and roleplay
    guidance) and a detail level that says how much authoring the NPC deserves. Goals,
    routines, preferences and per-timeline emotional state stay planned for Phase 20, and the
    AI context builder does not read the profile yet.

Forward migration:
    - `character.npcs.detail_level` (TEXT, default `standard`, one of `minimal`, `standard`,
      `major`).
    - `character.npc_portrayal_profiles`: append-only versions per NPC (unique
      `(npc_id, version_number)`), every field GM-only free text bounded at 4000 characters, the
      author and a change note. A trigger refuses UPDATE and any DELETE except the cascade from
      deleting the NPC itself.

Rollback:
    Supported: drops the trigger, function, table and column (profile history is lost).

Data implications:
    Existing NPCs become `standard`; no profile rows exist until one is saved.

Locking considerations:
    ADD COLUMN with a constant default is metadata-only; the new table is empty.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "131_npc_portrayal"
down_revision = "130_routes"
branch_labels = None
depends_on = None

_TEXT_FIELDS = (
    "voice",
    "speech_style",
    "vocabulary",
    "mannerisms",
    "emotional_baseline",
    "conversational_habits",
    "topics_avoided",
    "disclosure_boundaries",
    "roleplay_guidance",
)


def upgrade() -> None:
    op.execute("""
        ALTER TABLE character.npcs
        ADD COLUMN detail_level TEXT NOT NULL DEFAULT 'standard',
        ADD CONSTRAINT ck_npcs_detail_level
            CHECK (detail_level IN ('minimal', 'standard', 'major'));
    """)
    op.execute("""
        COMMENT ON COLUMN character.npcs.detail_level IS
        'How much authoring this NPC deserves: minimal (a background figure), standard (a named '
        'NPC), major (a fully portrayed NPC). A GM planning aid; it changes no rule.';
    """)
    columns = ",\n            ".join(
        f"{name} TEXT CONSTRAINT ck_npc_portrayal_profiles_{name}_length "
        f"CHECK ({name} IS NULL OR char_length({name}) <= 4000)"
        for name in _TEXT_FIELDS
    )
    op.execute(f"""
        CREATE TABLE character.npc_portrayal_profiles (
            npc_portrayal_profile_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            npc_id                    UUID NOT NULL
                                      REFERENCES character.npcs(npc_id) ON DELETE CASCADE,
            version_number            INTEGER NOT NULL,
            {columns},
            change_note               TEXT
                                      CONSTRAINT ck_npc_portrayal_profiles_change_note_length
                                      CHECK (change_note IS NULL OR char_length(change_note) <= 1000),
            created_by_user_id        UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_npc_portrayal_profiles_version_positive CHECK (version_number >= 1),
            CONSTRAINT ux_npc_portrayal_profiles_version UNIQUE (npc_id, version_number)
        );
    """)
    op.execute(
        "CREATE INDEX ix_npc_portrayal_profiles_created_by_user_id "
        "ON character.npc_portrayal_profiles (created_by_user_id);"
    )
    op.execute("""
        COMMENT ON TABLE character.npc_portrayal_profiles IS
        'Versioned, GM-only performance guidance for an NPC. Each save appends a version; no '
        'version is ever changed or deleted (only removed with its NPC). Never part of a '
        'player read; the AI context builder does not read it until Phase 20.';
    """)
    op.execute("""
        CREATE FUNCTION character.enforce_npc_portrayal_append_only()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'npc_portrayal_profiles versions are append-only'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            -- A delete is allowed only as the cascade from deleting the NPC itself.
            IF EXISTS (SELECT 1 FROM character.npcs WHERE npc_id = OLD.npc_id) THEN
                RAISE EXCEPTION 'npc_portrayal_profiles versions are append-only'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN OLD;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION character.enforce_npc_portrayal_append_only() IS
        'Refuses UPDATE and any DELETE of a portrayal version except the cascade from deleting '
        'the NPC.';
    """)
    op.execute("""
        CREATE TRIGGER tr_npc_portrayal_profiles_append_only
        BEFORE UPDATE OR DELETE ON character.npc_portrayal_profiles
        FOR EACH ROW EXECUTE FUNCTION character.enforce_npc_portrayal_append_only();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS tr_npc_portrayal_profiles_append_only "
        "ON character.npc_portrayal_profiles;"
    )
    op.execute("DROP FUNCTION IF EXISTS character.enforce_npc_portrayal_append_only();")
    op.execute("DROP TABLE IF EXISTS character.npc_portrayal_profiles;")
    op.execute("""
        ALTER TABLE character.npcs
        DROP CONSTRAINT IF EXISTS ck_npcs_detail_level,
        DROP COLUMN IF EXISTS detail_level;
    """)
