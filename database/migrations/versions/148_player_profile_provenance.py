"""Add the player_profile origin and its provenance to public-profile drafts and releases

Revision ID: 148_player_profile_provenance
Revises: 147_character_player_profiles
Create Date: 2026-11-12 12:00:00.000000

Purpose:
    P03-A slice A5b (docs/PHASE15_P03A_A5_PLAYER_PROFILE_DESIGN_2026-11-11.md section 6.3, decision
    D16). A public-profile draft field may now come from a campaign player profile. Such text is
    *restricted* exactly as legacy-copied text is (migrations 143 and 144): it stays withheld from a
    reader who may not read its source until a release covers its current content. This revision is
    storage and database rules only. It adds no copy command: A5a left no production writer of the
    profile, and A5c adds the copy, so until then no application path writes a `player_profile`
    origin. Tests seed one through `tests/player_profile_support.py`.

Forward migration:
    1. Inserts the origin `player_profile` into `campaign.public_profile_field_origins`.
    2. On drafts and releases, for each of `public_appearance` and `public_background`, adds
       `public_<field>_origin_player_profile_version_id` (UUID NULL) and
       `public_<field>_origin_player_profile_field_id` (UUID NULL, FK to
       `campaign.player_profile_fields`), with a composite foreign key
       `(version_id, campaign_id, character_id)` to the profile versions' scope key, so a draft or
       release can cite only its own campaign's profile of the same character (MATCH SIMPLE: checked
       only when set). They deliberately do not reuse `origin_entity_row_version`, which means the
       character's `core.entities.row_version` at a legacy copy. CHECKs: the pair is set together,
       and legacy and player-profile provenance never coexist. Partial FK indexes.
    3. Replaces `campaign.enforce_public_profile_field_origins()` (CREATE OR REPLACE): the allowed
       codes per field are `authored`, `legacy_<field>` and `player_profile`; `legacy_<field>`
       exactly when `origin_entity_row_version` is set; `player_profile` exactly when the pair is
       set; the cited field must be copy-eligible (so `boundaries` and `profile_notes` can never be
       the origin of a public field); NULL text has the `authored` origin.
    4. Replaces the drafts' `ck_character_public_profiles_<field>_watermark_paired` so the watermark
       is set exactly when either provenance is.
    5. Replaces `campaign.enforce_public_profile_restriction_watermarks()` (CREATE OR REPLACE):
       "restricted provenance" is now either provenance. An INSERT needs the watermark to equal
       `row_version`; an UPDATE that changes the text, origin or any provenance column needs it to
       equal `OLD.row_version + 1`; otherwise it never decreases; and restricted provenance cannot
       be relabelled authored while text remains (it may be removed only by clearing the text).

Rollback:
    Guarded and atomic. Refuses, changing nothing, while any draft or release has the
    `player_profile` origin or a non-NULL player-profile column. Otherwise restores 142's origin
    function, 143's paired CHECK and 144's watermark function exactly, drops the columns and
    deletes the lookup row.

Data implications:
    No row is rewritten, no `row_version` moves and no audit row is written. Existing drafts and
    releases read NULL provenance, which their `authored` or legacy origins already imply.

Locking considerations:
    ALTER TABLE ADD COLUMN (nullable) and constraint changes on two small tables, with a full-table
    validation of the new CHECKs; no table rewrite.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "148_player_profile_provenance"
down_revision = "147_character_player_profiles"
branch_labels = None
depends_on = None

_DRAFTS = "campaign.character_public_profiles"
_RELEASES = "campaign.character_public_profile_releases"
_FIELDS = ("appearance", "background")
_LOOKUP = "campaign.public_profile_field_origins"
_VERSIONS = "campaign.character_player_profile_versions"
_PP_FIELDS = "campaign.player_profile_fields"


def _version_col(field: str) -> str:
    return f"public_{field}_origin_player_profile_version_id"


def _field_col(field: str) -> str:
    return f"public_{field}_origin_player_profile_field_id"


# --- the new functions ------------------------------------------------------------------------


def _origins_function() -> str:
    parts = []
    for field in _FIELDS:
        parts.append(f"""
            SELECT code INTO v_code FROM campaign.public_profile_field_origins
            WHERE public_profile_field_origin_id = NEW.public_{field}_origin_id;
            IF v_code NOT IN ('authored', 'legacy_{field}', 'player_profile') THEN
                RAISE EXCEPTION 'Origin % cannot describe the public {field}', v_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (v_code = 'legacy_{field}')
               <> (NEW.public_{field}_origin_entity_row_version IS NOT NULL) THEN
                RAISE EXCEPTION
                    'A legacy {field} origin needs the source row version, and only it does'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (v_code = 'player_profile') <> (NEW.{_version_col(field)} IS NOT NULL)
               OR (v_code = 'player_profile') <> (NEW.{_field_col(field)} IS NOT NULL) THEN
                RAISE EXCEPTION
                    'A player-profile {field} origin needs its source version and field, and only it does'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF v_code = 'player_profile' THEN
                SELECT is_copy_eligible INTO v_eligible FROM campaign.player_profile_fields
                WHERE player_profile_field_id = NEW.{_field_col(field)};
                IF v_eligible IS DISTINCT FROM true THEN
                    RAISE EXCEPTION 'That player-profile field cannot be the origin of a public field'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF NEW.public_{field} IS NULL AND v_code <> 'authored' THEN
                RAISE EXCEPTION 'An empty public {field} has the authored origin'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        """)
    return f"""
        CREATE OR REPLACE FUNCTION campaign.enforce_public_profile_field_origins()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_code TEXT;
            v_eligible BOOLEAN;
        BEGIN
            {"".join(parts)}
            RETURN NEW;
        END
        $fn$;
    """


def _watermark_field(field: str) -> str:
    entity = f"public_{field}_origin_entity_row_version"
    pp_version = _version_col(field)
    pp_field = _field_col(field)
    mark = f"public_{field}_restricted_row_version"
    return f"""
            IF TG_OP = 'UPDATE'
               AND (OLD.{entity} IS NOT NULL OR OLD.{pp_version} IS NOT NULL)
               AND NEW.{entity} IS NULL AND NEW.{pp_version} IS NULL
               AND NEW.public_{field} IS NOT NULL THEN
                RAISE EXCEPTION
                    'Copied {field} text cannot be relabelled authored; clear the field instead'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.{entity} IS NOT NULL OR NEW.{pp_version} IS NOT NULL THEN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.{mark} IS DISTINCT FROM NEW.row_version THEN
                        RAISE EXCEPTION
                            'A new copied {field} needs its watermark set to row_version'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSIF NEW.public_{field} IS DISTINCT FROM OLD.public_{field}
                   OR NEW.public_{field}_origin_id IS DISTINCT FROM OLD.public_{field}_origin_id
                   OR NEW.{entity} IS DISTINCT FROM OLD.{entity}
                   OR NEW.{pp_version} IS DISTINCT FROM OLD.{pp_version}
                   OR NEW.{pp_field} IS DISTINCT FROM OLD.{pp_field} THEN
                    IF NEW.{mark} IS DISTINCT FROM OLD.row_version + 1 THEN
                        RAISE EXCEPTION
                            'Changing a copied {field} must advance its watermark to the new row_version'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSIF NEW.{mark} < OLD.{mark} THEN
                    RAISE EXCEPTION 'A restriction watermark never decreases'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
    """


def _watermark_function() -> str:
    return f"""
        CREATE OR REPLACE FUNCTION campaign.enforce_public_profile_restriction_watermarks()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            {_watermark_field("appearance")}
            {_watermark_field("background")}
            RETURN NEW;
        END
        $fn$;
    """


# --- revision 144's function, restored verbatim by the downgrade -----------------------------------


def _field_144(field: str) -> str:
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


def _function_144() -> str:
    return f"""
        CREATE OR REPLACE FUNCTION campaign.enforce_public_profile_restriction_watermarks()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            {_field_144("appearance")}
            {_field_144("background")}
            RETURN NEW;
        END
        $fn$;
    """


# --- revision 142's origin function, restored verbatim by the downgrade ----------------------------

_ORIGINS_FUNCTION_142 = """
        CREATE OR REPLACE FUNCTION campaign.enforce_public_profile_field_origins()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_code TEXT;
        BEGIN
            SELECT code INTO v_code FROM campaign.public_profile_field_origins
            WHERE public_profile_field_origin_id = NEW.public_appearance_origin_id;
            IF v_code NOT IN ('authored', 'legacy_appearance') THEN
                RAISE EXCEPTION 'Origin % cannot describe the public appearance', v_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (v_code = 'legacy_appearance')
               <> (NEW.public_appearance_origin_entity_row_version IS NOT NULL) THEN
                RAISE EXCEPTION
                    'A legacy appearance origin needs the source row version, and only it does'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.public_appearance IS NULL AND v_code <> 'authored' THEN
                RAISE EXCEPTION 'An empty public appearance has the authored origin'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT code INTO v_code FROM campaign.public_profile_field_origins
            WHERE public_profile_field_origin_id = NEW.public_background_origin_id;
            IF v_code NOT IN ('authored', 'legacy_background') THEN
                RAISE EXCEPTION 'Origin % cannot describe the public background', v_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (v_code = 'legacy_background')
               <> (NEW.public_background_origin_entity_row_version IS NOT NULL) THEN
                RAISE EXCEPTION
                    'A legacy background origin needs the source row version, and only it does'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.public_background IS NULL AND v_code <> 'authored' THEN
                RAISE EXCEPTION 'An empty public background has the authored origin'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """

_ORIGINS_COMMENT_142 = (
    "Each public-profile field''s origin must suit the field, carry the source row version "
    "exactly when it is a legacy origin, and be the authored origin for empty text."
)
_ORIGINS_COMMENT_148 = (
    "Each public-profile field''s origin must suit the field: authored, legacy (the source row "
    "version exactly then) or player_profile (its source version and a copy-eligible field "
    "exactly then), and be the authored origin for empty text."
)
_WATERMARK_COMMENT_144 = (
    "Refuses (never sets) a draft write that would lift a restriction: a legacy-origin field "
    "must carry a watermark equal to the row_version at which its content last changed, a "
    "watermark never decreases, and a legacy provenance can be removed only by clearing the "
    "field''s text in the same write."
)
_WATERMARK_COMMENT_148 = (
    "Refuses (never sets) a draft write that would lift a restriction: a field with copied "
    "provenance (legacy or player profile) must carry a watermark equal to the row_version at "
    "which its content last changed, a watermark never decreases, and copied provenance can be "
    "removed only by clearing the field''s text in the same write."
)


def upgrade() -> None:
    """Apply the migration."""
    op.execute(f"""
        INSERT INTO {_LOOKUP} (code, display_name, description, sort_order)
        VALUES ('player_profile', 'Copied from the player profile',
                'Copied by the server from a campaign player-profile field.', 40)
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute(f"""
        COMMENT ON TABLE {_LOOKUP} IS
        'Where a public-profile field''s text came from: authored by a GM, copied by the server '
        'from a legacy character description field (P03-A A2), or copied from a campaign player '
        'profile (A5). A record of provenance, not a safety label.';
    """)

    for table, stem in (
        (_DRAFTS, "character_public_profiles"),
        (_RELEASES, "character_public_profile_releases"),
    ):
        for field in _FIELDS:
            version, pp_field = _version_col(field), _field_col(field)
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN {version} UUID, ADD COLUMN {pp_field} UUID;"
            )
            op.execute(f"""
                ALTER TABLE {table}
                    ADD CONSTRAINT fk_{stem}_{field}_pp_version
                        FOREIGN KEY ({version}, campaign_id, character_id)
                        REFERENCES {_VERSIONS} (
                            character_player_profile_version_id, campaign_id, character_id),
                    ADD CONSTRAINT fk_{stem}_{field}_pp_field
                        FOREIGN KEY ({pp_field})
                        REFERENCES {_PP_FIELDS} (player_profile_field_id) ON DELETE RESTRICT,
                    ADD CONSTRAINT ck_{stem}_{field}_pp_pair
                        CHECK (({version} IS NULL) = ({pp_field} IS NULL)),
                    ADD CONSTRAINT ck_{stem}_{field}_provenance_exclusive
                        CHECK (public_{field}_origin_entity_row_version IS NULL
                               OR {version} IS NULL);
            """)
            op.execute(f"""
                COMMENT ON COLUMN {table}.{version} IS
                'The campaign player-profile version this field''s text was copied from; NULL unless '
                'the origin is player_profile. The composite foreign key stops it naming another '
                'campaign''s or another character''s profile. A record of provenance for GMs; never '
                'sent to an audience.';
            """)
            op.execute(f"""
                COMMENT ON COLUMN {table}.{pp_field} IS
                'Which player-profile field (a copy-eligible one) this field''s text was copied '
                'from; NULL exactly when the version column is NULL.';
            """)
            op.execute(
                f"CREATE INDEX ix_{stem}_{field}_pp_version ON {table} ({version}) "
                f"WHERE {version} IS NOT NULL;"
            )
            op.execute(
                f"CREATE INDEX ix_{stem}_{field}_pp_field ON {table} ({pp_field}) "
                f"WHERE {pp_field} IS NOT NULL;"
            )

    for field in _FIELDS:
        op.execute(f"""
            ALTER TABLE {_DRAFTS}
                DROP CONSTRAINT ck_character_public_profiles_{field}_watermark_paired,
                ADD CONSTRAINT ck_character_public_profiles_{field}_watermark_paired CHECK (
                    (public_{field}_restricted_row_version IS NULL)
                    = (public_{field}_origin_entity_row_version IS NULL
                       AND {_version_col(field)} IS NULL));
        """)
        op.execute(f"""
            COMMENT ON COLUMN {_DRAFTS}.public_{field}_restricted_row_version IS
            'The draft row_version at which this field''s current content was last written while it '
            'had copied provenance (the restriction watermark). A release covers the field when its '
            'from_draft_row_version is at or above it. NULL exactly when the field is not copied.';
        """)

    op.execute(_origins_function())
    op.execute(
        f"COMMENT ON FUNCTION campaign.enforce_public_profile_field_origins() IS "
        f"'{_ORIGINS_COMMENT_148}';"
    )
    op.execute(_watermark_function())
    op.execute(
        f"COMMENT ON FUNCTION campaign.enforce_public_profile_restriction_watermarks() IS "
        f"'{_WATERMARK_COMMENT_148}';"
    )


def downgrade() -> None:
    """Revert the migration, refusing (and changing nothing) while any copied provenance exists."""
    op.execute(f"""
        DO $guard$
        DECLARE
            v_rows BIGINT;
        BEGIN
            SELECT
                (SELECT count(*) FROM {_DRAFTS} d
                  WHERE d.{_version_col("appearance")} IS NOT NULL
                     OR d.{_field_col("appearance")} IS NOT NULL
                     OR d.{_version_col("background")} IS NOT NULL
                     OR d.{_field_col("background")} IS NOT NULL
                     OR EXISTS (SELECT 1 FROM {_LOOKUP} o
                                WHERE o.code = 'player_profile'
                                  AND o.public_profile_field_origin_id
                                      IN (d.public_appearance_origin_id,
                                          d.public_background_origin_id)))
              + (SELECT count(*) FROM {_RELEASES} r
                  WHERE r.{_version_col("appearance")} IS NOT NULL
                     OR r.{_field_col("appearance")} IS NOT NULL
                     OR r.{_version_col("background")} IS NOT NULL
                     OR r.{_field_col("background")} IS NOT NULL
                     OR EXISTS (SELECT 1 FROM {_LOOKUP} o
                                WHERE o.code = 'player_profile'
                                  AND o.public_profile_field_origin_id
                                      IN (r.public_appearance_origin_id,
                                          r.public_background_origin_id)))
            INTO v_rows;
            IF v_rows > 0 THEN
                RAISE EXCEPTION
                    'Refusing to downgrade 148: % public-profile draft or release row(s) carry '
                    'player-profile provenance, and the older triggers would not restrict it.',
                    v_rows
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END
        $guard$;
    """)
    op.execute(_function_144())
    op.execute(
        f"COMMENT ON FUNCTION campaign.enforce_public_profile_restriction_watermarks() IS "
        f"'{_WATERMARK_COMMENT_144}';"
    )
    op.execute(_ORIGINS_FUNCTION_142)
    op.execute(
        f"COMMENT ON FUNCTION campaign.enforce_public_profile_field_origins() IS "
        f"'{_ORIGINS_COMMENT_142}';"
    )
    for field in _FIELDS:
        op.execute(f"""
            ALTER TABLE {_DRAFTS}
                DROP CONSTRAINT ck_character_public_profiles_{field}_watermark_paired,
                ADD CONSTRAINT ck_character_public_profiles_{field}_watermark_paired
                    CHECK ((public_{field}_restricted_row_version IS NULL)
                           = (public_{field}_origin_entity_row_version IS NULL));
        """)
        op.execute(f"""
            COMMENT ON COLUMN {_DRAFTS}.public_{field}_restricted_row_version IS
            'The draft row_version at which this field''s current content was last written while it '
            'had a legacy origin (the restriction watermark). A release covers the field when its '
            'from_draft_row_version is at or above it. NULL exactly when the field is not copied.';
        """)
    for table in (_DRAFTS, _RELEASES):
        for field in _FIELDS:
            op.execute(
                f"ALTER TABLE {table} DROP COLUMN {_version_col(field)}, "
                f"DROP COLUMN {_field_col(field)};"
            )
    op.execute(f"DELETE FROM {_LOOKUP} WHERE code = 'player_profile';")
    op.execute(f"""
        COMMENT ON TABLE {_LOOKUP} IS
        'Where a public-profile field''s text came from: authored by a GM, or copied by the '
        'server from a legacy character description field (P03-A A2). A record of provenance, '
        'not a safety label.';
    """)
