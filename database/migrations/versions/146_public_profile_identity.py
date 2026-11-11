"""Add publishable species and size to character public-profile drafts and releases

Revision ID: 146_public_profile_identity
Revises: 145_character_revelations
Create Date: 2026-11-10 12:00:00.000000

Purpose:
    P03-A slice A4a (docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md section 12.8, decision
    D6). A GM may choose, per draft, to publish the character's actual species and size. A release
    snapshots the selected definition values (the species id, code and display name, and the size
    code) together with the `core.entities.row_version` they were read at, so a later definition,
    ruleset or draft change never alters what audiences were told. A4a is storage and authoring
    only: no audience response reads these columns yet.

Forward migration:
    1. Adds the draft flags `should_publish_species` and `should_publish_size` (NOT NULL, default
       false). A constant default fires no row trigger, so no `row_version` moves.
    2. Adds the five nullable release columns `released_species_id` (FK to `rules.species`,
       ON DELETE RESTRICT, partial index), `released_species_code`,
       `released_species_display_name`, `released_size_category` and
       `identity_entity_row_version`, with three CHECKs: the species columns are all null or all
       set; the size is null or one of the six codes; the entity row version is set exactly when
       species or size is, and is at least 1.
    3. Replaces the A2 retry key `ux_character_public_profile_releases_draft_version` with
       `ux_character_public_profile_releases_draft_identity`, UNIQUE NULLS NOT DISTINCT over
       (profile, from_draft_row_version, identity_entity_row_version). For a release that publishes
       neither field it is exactly the A2 key.
    4. Adds the BEFORE INSERT trigger `campaign.enforce_public_profile_release_identity()`: a
       published species, its code and display name, a published size and the entity row version
       must equal the live definition, the `rules.species` row and `core.entities.row_version`.

Rollback:
    Supported but lossy: drops the trigger, function, index, constraints and columns, losing the
    draft flags and every identity snapshot (older code never serves them), and restores the A2
    unique constraint. It refuses first, atomically, while any profile holds two releases of one
    draft version, because the A2 unique constraint could not then be restored.

Data implications:
    No backfill. Existing drafts read both flags false and existing releases have null identity
    columns; no row_version changes.

Locking considerations:
    ADD COLUMN with a constant default (no rewrite on PostgreSQL 18) and nullable columns on two
    small tables, one constraint swap, one index and one trigger (brief SHARE ROW EXCLUSIVE locks).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "146_public_profile_identity"
down_revision = "145_character_revelations"
branch_labels = None
depends_on = None

_RELEASES = "campaign.character_public_profile_releases"
_DRAFTS = "campaign.character_public_profiles"


def upgrade() -> None:
    """Apply the migration."""
    for column, description in (
        ("should_publish_species", "species"),
        ("should_publish_size", "size"),
    ):
        op.execute(f"ALTER TABLE {_DRAFTS} ADD COLUMN {column} BOOLEAN NOT NULL DEFAULT false;")
        op.execute(f"""
            COMMENT ON COLUMN {_DRAFTS}.{column} IS
            'Whether the next release publishes the character''s actual {description}. Off by '
            'default. It only selects what the next release snapshots; it publishes nothing by '
            'itself (P03-A A4, decision D6).';
        """)

    op.execute(f"""
        ALTER TABLE {_RELEASES}
            ADD COLUMN released_species_id UUID
                REFERENCES rules.species(species_id) ON DELETE RESTRICT,
            ADD COLUMN released_species_code TEXT,
            ADD COLUMN released_species_display_name TEXT,
            ADD COLUMN released_size_category TEXT,
            ADD COLUMN identity_entity_row_version BIGINT;
    """)
    op.execute(f"""
        ALTER TABLE {_RELEASES}
            ADD CONSTRAINT ck_character_public_profile_releases_species_snapshot CHECK (
                (released_species_id IS NULL) = (released_species_code IS NULL)
                AND (released_species_id IS NULL) = (released_species_display_name IS NULL)
            ),
            ADD CONSTRAINT ck_character_public_profile_releases_size_category CHECK (
                released_size_category IS NULL OR released_size_category IN
                    ('tiny', 'small', 'medium', 'large', 'huge', 'gargantuan')
            ),
            ADD CONSTRAINT ck_character_public_profile_releases_identity_version CHECK (
                (identity_entity_row_version IS NOT NULL)
                    = (released_species_id IS NOT NULL OR released_size_category IS NOT NULL)
                AND (identity_entity_row_version IS NULL OR identity_entity_row_version >= 1)
            );
    """)
    for column, comment in (
        (
            "released_species_id",
            "The character's species_id when a release published its species; NULL when it did "
            "not. Kept for GM provenance and never sent to an audience. ON DELETE RESTRICT: a "
            "species a release names cannot be deleted.",
        ),
        (
            "released_species_code",
            "The released species' rules.species.code at release time; NULL unless the species "
            "was published. A snapshot: later ruleset changes never alter it.",
        ),
        (
            "released_species_display_name",
            "The released species' rules.species.display_name at release time; NULL unless the "
            "species was published. A snapshot, so a relabelled species never changes what "
            "audiences were told.",
        ),
        (
            "released_size_category",
            "The character's size_category (one of the six size codes) when a release published "
            "its size; NULL when it did not.",
        ),
        (
            "identity_entity_row_version",
            "The character's core.entities.row_version the species and size snapshot was read "
            "at; set exactly when species or size is published. Part of the retry key: the same "
            "draft version may be released again after a definition change.",
        ),
    ):
        escaped = comment.replace("'", "''")
        op.execute(f"COMMENT ON COLUMN {_RELEASES}.{column} IS '{escaped}';")
    op.execute(f"""
        CREATE INDEX ix_character_public_profile_releases_released_species_id
        ON {_RELEASES} (released_species_id) WHERE released_species_id IS NOT NULL;
    """)

    op.execute(f"""
        ALTER TABLE {_RELEASES}
            DROP CONSTRAINT ux_character_public_profile_releases_draft_version;
    """)
    op.execute(f"""
        ALTER TABLE {_RELEASES}
            ADD CONSTRAINT ux_character_public_profile_releases_draft_identity
            UNIQUE NULLS NOT DISTINCT (
                character_public_profile_id, from_draft_row_version, identity_entity_row_version
            );
    """)
    op.execute(f"""
        COMMENT ON COLUMN {_RELEASES}.from_draft_row_version IS
        'The draft row_version this release snapshots. With identity_entity_row_version it is '
        'the natural retry key: a draft version that publishes neither species nor size is '
        'released at most once; one that does may be released again under a new character '
        'row_version.';
    """)

    op.execute("""
        CREATE FUNCTION campaign.enforce_public_profile_release_identity()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_species UUID;
            v_size TEXT;
            v_code TEXT;
            v_display TEXT;
            v_version BIGINT;
        BEGIN
            IF NEW.released_species_id IS NULL AND NEW.released_size_category IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT species_id, size_category INTO v_species, v_size
            FROM character.characters WHERE character_id = NEW.character_id;
            SELECT row_version INTO v_version
            FROM core.entities WHERE entity_id = NEW.character_id;
            IF NEW.identity_entity_row_version IS DISTINCT FROM v_version THEN
                RAISE EXCEPTION
                    'a release must snapshot the character at its current core.entities.row_version'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.released_species_id IS NOT NULL THEN
                SELECT code, display_name INTO v_code, v_display
                FROM rules.species WHERE species_id = NEW.released_species_id;
                IF NEW.released_species_id IS DISTINCT FROM v_species
                   OR NEW.released_species_code IS DISTINCT FROM v_code
                   OR NEW.released_species_display_name IS DISTINCT FROM v_display THEN
                    RAISE EXCEPTION
                        'a published species must equal the character''s actual species'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF NEW.released_size_category IS NOT NULL
               AND NEW.released_size_category IS DISTINCT FROM v_size THEN
                RAISE EXCEPTION 'a published size must equal the character''s actual size'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_public_profile_release_identity() IS
        'A release that publishes species or size must snapshot the character''s actual current '
        'values, the species'' current code and display name, and the current '
        'core.entities.row_version (D6). Refuses any apparent-species value.';
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_public_profile_releases_enforce_identity
        BEFORE INSERT ON {_RELEASES}
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_public_profile_release_identity();
    """)
    op.execute(f"""
        COMMENT ON TRIGGER tr_character_public_profile_releases_enforce_identity ON {_RELEASES} IS
        'Refuses a release whose published species, size or entity row version differs from the '
        'live definition (P03-A A4, D6).';
    """)


def downgrade() -> None:
    """Revert the migration (lossy: the draft flags and every identity snapshot are dropped)."""
    op.execute(f"""
        DO $guard$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM {_RELEASES}
                GROUP BY character_public_profile_id, from_draft_row_version
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Refusing to downgrade 146_public_profile_identity: a profile holds two '
                    'releases of one draft version, so the A2 unique constraint cannot be '
                    'restored';
            END IF;
        END
        $guard$;
    """)
    op.execute(
        f"DROP TRIGGER IF EXISTS tr_character_public_profile_releases_enforce_identity "
        f"ON {_RELEASES};"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_public_profile_release_identity();")
    op.execute(f"""
        ALTER TABLE {_RELEASES}
            DROP CONSTRAINT IF EXISTS ux_character_public_profile_releases_draft_identity;
    """)
    op.execute(f"""
        ALTER TABLE {_RELEASES}
            ADD CONSTRAINT ux_character_public_profile_releases_draft_version
            UNIQUE (character_public_profile_id, from_draft_row_version);
    """)
    op.execute(f"""
        COMMENT ON COLUMN {_RELEASES}.from_draft_row_version IS
        'The draft row_version this release snapshots. Unique per profile: a draft version is '
        'released at most once, which makes it the natural retry key.';
    """)
    op.execute(
        "DROP INDEX IF EXISTS campaign.ix_character_public_profile_releases_released_species_id;"
    )
    op.execute(f"""
        ALTER TABLE {_RELEASES}
            DROP CONSTRAINT IF EXISTS ck_character_public_profile_releases_identity_version,
            DROP CONSTRAINT IF EXISTS ck_character_public_profile_releases_size_category,
            DROP CONSTRAINT IF EXISTS ck_character_public_profile_releases_species_snapshot;
    """)
    op.execute(f"""
        ALTER TABLE {_RELEASES}
            DROP COLUMN IF EXISTS identity_entity_row_version,
            DROP COLUMN IF EXISTS released_size_category,
            DROP COLUMN IF EXISTS released_species_display_name,
            DROP COLUMN IF EXISTS released_species_code,
            DROP COLUMN IF EXISTS released_species_id;
    """)
    op.execute(f"""
        ALTER TABLE {_DRAFTS}
            DROP COLUMN IF EXISTS should_publish_size,
            DROP COLUMN IF EXISTS should_publish_species;
    """)
