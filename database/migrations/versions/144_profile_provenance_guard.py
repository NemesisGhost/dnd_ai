"""Refuse relabelling copied public-profile text as authored

Revision ID: 144_profile_provenance_guard
Revises: 143_profile_watermarks
Create Date: 2026-11-07 18:00:00.000000

Purpose:
    P03-A slice A2b-1 review finding (invariant I1, "provenance travels with content"). Migration
    143's trigger only inspected a field whose NEW row still carried a legacy source version, so an
    UPDATE that moved a legacy-origin field to the authored origin, with the source version and
    watermark cleared and the text kept, passed every CHECK and the trigger: restricted copied text
    became unrestricted authored text. This revision closes that.

Forward migration:
    Replaces `campaign.enforce_public_profile_restriction_watermarks()` (CREATE OR REPLACE; the
    trigger, columns and CHECKs are unchanged). New rule, per field: an UPDATE whose OLD row has a
    legacy source version (`origin_entity_row_version IS NOT NULL`) and whose NEW row has none (the
    authored origin, no source version, no watermark) is refused unless the NEW text is NULL.
    Removing the origin, the source version and the watermark is therefore permitted only in the one
    write that clears the field, which is what the save command does. Replacement text is refused
    as well as unchanged text. Every rule of revision 143 is kept unchanged.

Why a follow-up revision and not an edit of 143:
    143 is not on any pushed branch, but it may already be applied to a developer's database, and
    Alembic would not re-run an edited 143 there: that database would keep the weaker function
    while reporting the same revision as a fresh one. A new revision reaches both.

Rollback:
    Restores revision 143's function body, which lacks the relabel rule. A guard runs first, before
    any function or schema change, and refuses (changing nothing) while any DRAFT has a legacy
    provenance in either field (a source version, or an origin other than `authored`): at 143 such a
    draft could be relabelled authored, so copied text would become unrestricted. Immutable releases
    do not block this downgrade; the guarded function protects mutable drafts only (the releases'
    own legacy rows are guarded by revision 143's downgrade). Clear or release the copied fields
    first, or stay at 144.

Data implications:
    None. No row is read or rewritten. Existing rows that already carry a relabelled field (possible
    only by hand-written SQL against a database at 143) are not repaired or detected here.

Locking considerations:
    CREATE OR REPLACE FUNCTION takes no table lock beyond the catalog row.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "144_profile_provenance_guard"
down_revision = "143_profile_watermarks"
branch_labels = None
depends_on = None


def _field(field: str, *, guard_relabel: bool) -> str:
    relabel = ""
    if guard_relabel:
        relabel = f"""
            IF TG_OP = 'UPDATE'
               AND OLD.public_{field}_origin_entity_row_version IS NOT NULL
               AND NEW.public_{field}_origin_entity_row_version IS NULL
               AND NEW.public_{field} IS NOT NULL THEN
                RAISE EXCEPTION
                    'Copied {field} text cannot be relabelled authored; clear the field instead'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        """
    return f"""
            {relabel}
            IF NEW.public_{field}_origin_entity_row_version IS NOT NULL THEN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.public_{field}_restricted_row_version IS DISTINCT FROM NEW.row_version THEN
                        RAISE EXCEPTION
                            'A new legacy-origin {field} needs its watermark set to row_version'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSIF NEW.public_{field} IS DISTINCT FROM OLD.public_{field}
                   OR NEW.public_{field}_origin_id IS DISTINCT FROM OLD.public_{field}_origin_id
                   OR NEW.public_{field}_origin_entity_row_version
                        IS DISTINCT FROM OLD.public_{field}_origin_entity_row_version THEN
                    IF NEW.public_{field}_restricted_row_version
                        IS DISTINCT FROM OLD.row_version + 1 THEN
                        RAISE EXCEPTION
                            'Changing a legacy-origin {field} must advance its watermark to the new row_version'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSIF NEW.public_{field}_restricted_row_version
                        < OLD.public_{field}_restricted_row_version THEN
                    RAISE EXCEPTION 'A restriction watermark never decreases'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
    """


def _function(*, guard_relabel: bool) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION campaign.enforce_public_profile_restriction_watermarks()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            {_field("appearance", guard_relabel=guard_relabel)}
            {_field("background", guard_relabel=guard_relabel)}
            RETURN NEW;
        END
        $fn$;
    """


def upgrade() -> None:
    """Apply the migration."""
    op.execute(_function(guard_relabel=True))
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_public_profile_restriction_watermarks() IS
        'Refuses (never sets) a draft write that would lift a restriction: a legacy-origin field '
        'must carry a watermark equal to the row_version at which its content last changed, a '
        'watermark never decreases, and a legacy provenance can be removed only by clearing the '
        'field''s text in the same write.';
    """)


def downgrade() -> None:
    """Revert to revision 143's function, refused while any draft holds copied text's provenance."""
    op.execute("""
        DO $guard$
        DECLARE
            v_legacy BIGINT;
        BEGIN
            SELECT count(*) INTO v_legacy
              FROM campaign.character_public_profiles d
             WHERE d.public_appearance_origin_entity_row_version IS NOT NULL
                OR d.public_background_origin_entity_row_version IS NOT NULL
                OR EXISTS (SELECT 1 FROM campaign.public_profile_field_origins o
                            WHERE o.public_profile_field_origin_id
                                  IN (d.public_appearance_origin_id, d.public_background_origin_id)
                              AND o.code <> 'authored');
            IF v_legacy > 0 THEN
                RAISE EXCEPTION
                    'Refusing to downgrade 144_profile_provenance_guard: % public-profile draft(s) '
                    'carry a legacy provenance, and the older trigger would let their copied text '
                    'be relabelled authored. Clear or release those fields first.', v_legacy
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END
        $guard$;
    """)
    op.execute(_function(guard_relabel=False))
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_public_profile_restriction_watermarks() IS
        'Refuses (never sets) a draft write that would lift a restriction: a legacy-origin field '
        'must carry a watermark equal to the row_version at which its content last changed, and a '
        'watermark never decreases.';
    """)
