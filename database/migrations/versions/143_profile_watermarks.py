"""Add per-field restriction watermarks to character public-profile drafts

Revision ID: 143_profile_watermarks
Revises: 142_character_public_profiles
Create Date: 2026-11-07 15:00:00.000000

Purpose:
    P03-A slice A2b-1 (docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md section 9, decision D7).
    Text copied from a character's legacy description keeps the source-read restriction until a
    release covers it. Each draft field gets a *restriction watermark*: the draft `row_version` at
    which the field's current content was last written while it had a legacy origin. A release
    covers a field when its `from_draft_row_version` is at or above the watermark. Restriction and
    withholding are derived on every read; nothing per reader is stored.

Forward migration:
    1. Preflight. Counts draft and release rows whose either field has a legacy origin. If any
       exist the upgrade raises and changes nothing (the migration is transactional): no application
       path at the parent writes a legacy origin, so a non-zero count means hand-written rows whose
       disclosure history is unknown, and the operator must decide. The migration never guesses a
       watermark or a coverage.
    2. Adds `public_appearance_restricted_row_version` and `public_background_restricted_row_version`
       (BIGINT NULL) to `campaign.character_public_profiles`.
    3. CHECKs per field: the watermark is NULL exactly when the field's
       `origin_entity_row_version` is NULL (which migration 142's origin trigger ties to a legacy
       origin), is at least 1, and is at most `row_version`.
    4. Trigger `campaign.enforce_public_profile_restriction_watermarks()` (BEFORE INSERT OR UPDATE):
       it sets nothing, it refuses. A legacy-origin INSERT needs `watermark = row_version`; an UPDATE
       that changes a legacy-origin field's text, origin or source version needs `watermark = OLD.
       row_version + 1` (the value `core.bump_row_version()` gives the row, so the rule does not
       depend on trigger order); an UPDATE that leaves the content alone may not lower it. So a
       command that forgets to advance a watermark fails instead of silently lifting a restriction.

Rollback:
    Supported when no row carries a legacy origin: drops the trigger, its function, the CHECKs and
    the two columns, which is lossless for authored-only data. With a legacy-origin draft or release
    present the downgrade raises and changes nothing, because dropping the watermarks would show
    copied text to every reader of the down-level code.

Data implications:
    No existing row is rewritten: authored drafts keep `row_version`, text and origins and gain NULL
    watermarks; releases are not touched. No audit row is written.

Locking considerations:
    ALTER TABLE on a small new table (brief ACCESS EXCLUSIVE), no rewrite beyond adding nullable
    columns, and a full scan of both tables for the preflight.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "143_profile_watermarks"
down_revision = "142_character_public_profiles"
branch_labels = None
depends_on = None

_LEGACY_COUNT = """
    SELECT
        (SELECT count(*) FROM campaign.character_public_profiles d
          WHERE d.public_appearance_origin_entity_row_version IS NOT NULL
             OR d.public_background_origin_entity_row_version IS NOT NULL
             OR EXISTS (SELECT 1 FROM campaign.public_profile_field_origins o
                        WHERE o.public_profile_field_origin_id
                              IN (d.public_appearance_origin_id, d.public_background_origin_id)
                          AND o.code <> 'authored'))
      + (SELECT count(*) FROM campaign.character_public_profile_releases r
          WHERE r.public_appearance_origin_entity_row_version IS NOT NULL
             OR r.public_background_origin_entity_row_version IS NOT NULL
             OR EXISTS (SELECT 1 FROM campaign.public_profile_field_origins o
                        WHERE o.public_profile_field_origin_id
                              IN (r.public_appearance_origin_id, r.public_background_origin_id)
                          AND o.code <> 'authored'))
"""


def upgrade() -> None:
    """Apply the migration."""
    op.execute(f"""
        DO $preflight$
        DECLARE
            v_legacy BIGINT;
        BEGIN
            {_LEGACY_COUNT} INTO v_legacy;
            IF v_legacy > 0 THEN
                RAISE EXCEPTION
                    'Refusing 143_profile_watermarks: % public-profile draft or release row(s) '
                    'already carry a legacy origin. Their disclosure history is unknown; decide '
                    'their restriction by hand before upgrading.', v_legacy
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END
        $preflight$;
    """)
    for field in ("appearance", "background"):
        op.execute(f"""
            ALTER TABLE campaign.character_public_profiles
                ADD COLUMN public_{field}_restricted_row_version BIGINT;
        """)
        op.execute(f"""
            COMMENT ON COLUMN campaign.character_public_profiles.public_{field}_restricted_row_version IS
            'The draft row_version at which this field''s current content was last written while it '
            'had a legacy origin (the restriction watermark). A release covers the field when its '
            'from_draft_row_version is at or above it. NULL exactly when the field is not copied.';
        """)
        op.execute(f"""
            ALTER TABLE campaign.character_public_profiles
                ADD CONSTRAINT ck_character_public_profiles_{field}_watermark_paired
                    CHECK ((public_{field}_restricted_row_version IS NULL)
                           = (public_{field}_origin_entity_row_version IS NULL)),
                ADD CONSTRAINT ck_character_public_profiles_{field}_watermark_positive
                    CHECK (public_{field}_restricted_row_version IS NULL
                           OR public_{field}_restricted_row_version >= 1),
                ADD CONSTRAINT ck_character_public_profiles_{field}_watermark_bounded
                    CHECK (public_{field}_restricted_row_version IS NULL
                           OR public_{field}_restricted_row_version <= row_version);
        """)

    op.execute("""
        CREATE FUNCTION campaign.enforce_public_profile_restriction_watermarks()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            -- Appearance.
            IF NEW.public_appearance_origin_entity_row_version IS NOT NULL THEN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.public_appearance_restricted_row_version IS DISTINCT FROM NEW.row_version THEN
                        RAISE EXCEPTION
                            'A new legacy-origin appearance needs its watermark set to row_version'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSIF NEW.public_appearance IS DISTINCT FROM OLD.public_appearance
                   OR NEW.public_appearance_origin_id IS DISTINCT FROM OLD.public_appearance_origin_id
                   OR NEW.public_appearance_origin_entity_row_version
                        IS DISTINCT FROM OLD.public_appearance_origin_entity_row_version THEN
                    IF NEW.public_appearance_restricted_row_version
                        IS DISTINCT FROM OLD.row_version + 1 THEN
                        RAISE EXCEPTION
                            'Changing a legacy-origin appearance must advance its watermark to the new row_version'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSIF NEW.public_appearance_restricted_row_version
                        < OLD.public_appearance_restricted_row_version THEN
                    RAISE EXCEPTION 'A restriction watermark never decreases'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            -- Background.
            IF NEW.public_background_origin_entity_row_version IS NOT NULL THEN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.public_background_restricted_row_version IS DISTINCT FROM NEW.row_version THEN
                        RAISE EXCEPTION
                            'A new legacy-origin background needs its watermark set to row_version'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSIF NEW.public_background IS DISTINCT FROM OLD.public_background
                   OR NEW.public_background_origin_id IS DISTINCT FROM OLD.public_background_origin_id
                   OR NEW.public_background_origin_entity_row_version
                        IS DISTINCT FROM OLD.public_background_origin_entity_row_version THEN
                    IF NEW.public_background_restricted_row_version
                        IS DISTINCT FROM OLD.row_version + 1 THEN
                        RAISE EXCEPTION
                            'Changing a legacy-origin background must advance its watermark to the new row_version'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSIF NEW.public_background_restricted_row_version
                        < OLD.public_background_restricted_row_version THEN
                    RAISE EXCEPTION 'A restriction watermark never decreases'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_public_profile_restriction_watermarks() IS
        'Refuses (never sets) a draft write that would lift a restriction: a legacy-origin field '
        'must carry a watermark equal to the row_version at which its content last changed, and a '
        'watermark never decreases.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_public_profiles_enforce_watermarks
        BEFORE INSERT OR UPDATE ON campaign.character_public_profiles
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_public_profile_restriction_watermarks();
    """)


def downgrade() -> None:
    """Revert the migration (refused when any row carries a legacy origin)."""
    op.execute(f"""
        DO $guard$
        DECLARE
            v_legacy BIGINT;
        BEGIN
            {_LEGACY_COUNT} INTO v_legacy;
            IF v_legacy > 0 THEN
                RAISE EXCEPTION
                    'Refusing to downgrade 143_profile_watermarks: % public-profile draft or '
                    'release row(s) carry a legacy origin, and dropping the restriction '
                    'watermarks would show copied text to every reader of the older code.',
                    v_legacy
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END
        $guard$;
    """)
    op.execute(
        "DROP TRIGGER IF EXISTS tr_character_public_profiles_enforce_watermarks "
        "ON campaign.character_public_profiles;"
    )
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_public_profile_restriction_watermarks();")
    for field in ("appearance", "background"):
        op.execute(f"""
            ALTER TABLE campaign.character_public_profiles
                DROP CONSTRAINT IF EXISTS ck_character_public_profiles_{field}_watermark_bounded,
                DROP CONSTRAINT IF EXISTS ck_character_public_profiles_{field}_watermark_positive,
                DROP CONSTRAINT IF EXISTS ck_character_public_profiles_{field}_watermark_paired,
                DROP COLUMN IF EXISTS public_{field}_restricted_row_version;
        """)
