"""Add campaign-scoped character public-profile drafts and immutable releases

Revision ID: 142_character_public_profiles
Revises: 141_character_reveal_delegations
Create Date: 2026-11-07 12:00:00.000000

Purpose:
    P03-A slice A2a (docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md section 5). A campaign's
    GMs author a *public profile* for a character: two text fields (`public_appearance`,
    `public_background`) held in a mutable draft, and released as immutable, versioned snapshots by
    someone holding `character.reveal`. A release makes nothing visible by itself; audiences see one
    only through a later revelation (A3/A4). The world definition (`core.entities`,
    `character.character_descriptions`) is never written.

Forward migration:
    1. Creates the lookup `campaign.public_profile_field_origins` (`authored`, `legacy_appearance`,
       `legacy_background`) so a field's provenance is a foreign key, not an ENUM. `player_profile`
       is reserved for A5 and inserted then.
    2. Creates `campaign.character_public_profiles`, one mutable draft per (campaign, character),
       with `row_version` kept current by `core.bump_row_version()`.
    3. Creates `campaign.character_public_profile_releases`, append-only snapshots of a draft at a
       draft version, versioned 1..n per profile, with the releaser's authority source (owner or a
       reveal delegation). A composite foreign key stops a release naming another campaign's or
       another character's profile. `UNIQUE (profile, from_draft_row_version)` lets a draft version
       be released once, which is also the natural retry key.
    4. Adds local integrity triggers (docs/DATABASE_CONVENTIONS.md section 20.4): scope (the
       character is in the campaign's world, memberships and the delegation belong to the campaign,
       the delegation's grantee is the releaser), field origins, and release immutability (UPDATE,
       DELETE and TRUNCATE refused).
    5. Revokes UPDATE/DELETE/TRUNCATE on releases and DELETE/TRUNCATE on drafts from the application
       roles at the grant level, and all access from the reporting role.

Rollback:
    Supported but lossy. Drops both tables, the lookup and the trigger functions; every draft and
    release is lost. Nothing else references them.

Data implications:
    No backfill. Every existing character has no draft and no release after the upgrade.

Locking considerations:
    DDL on new tables plus row-level INSERT on a three-row lookup; no table rewrite of any existing
    table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "142_character_public_profiles"
down_revision = "141_character_reveal_delegations"
branch_labels = None
depends_on = None

_ORIGINS = (
    ("authored", "Authored", "Written by a GM in the public-profile draft.", 10),
    (
        "legacy_appearance",
        "Copied from legacy appearance",
        "Copied by the server from the legacy appearance text.",
        20,
    ),
    (
        "legacy_background",
        "Copied from legacy background",
        "Copied by the server from the legacy background text.",
        30,
    ),
)

_TEXT_MAX = 4000  # NPC_TEXT_MAX_LENGTH, the legacy source field's limit

_APP_ROLES = ("app_read_write", "integration_worker")


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        CREATE TABLE campaign.public_profile_field_origins (
            public_profile_field_origin_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_public_profile_field_origins_code UNIQUE (code),
            CONSTRAINT ck_public_profile_field_origins_code_length CHECK (char_length(code) <= 100),
            CONSTRAINT ck_public_profile_field_origins_code_format
                CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.public_profile_field_origins IS
        'Where a public-profile field''s text came from: authored by a GM, or copied by the '
        'server from a legacy character description field (P03-A A2). A record of provenance, '
        'not a safety label.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.public_profile_field_origins.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_public_profile_field_origins_set_updated_at
        BEFORE UPDATE ON campaign.public_profile_field_origins
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    for code, display_name, description, sort_order in _ORIGINS:
        op.execute(f"""
            INSERT INTO campaign.public_profile_field_origins
                (code, display_name, description, sort_order)
            VALUES ('{code}', '{display_name}', '{description}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    op.execute(f"""
        CREATE TABLE campaign.character_public_profiles (
            character_public_profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id                 UUID NOT NULL
                                        REFERENCES campaign.campaigns(campaign_id)
                                        ON DELETE RESTRICT,
            character_id                UUID NOT NULL
                                        REFERENCES character.characters(character_id)
                                        ON DELETE RESTRICT,
            public_appearance           TEXT,
            public_appearance_origin_id UUID NOT NULL
                                        REFERENCES campaign.public_profile_field_origins(
                                            public_profile_field_origin_id) ON DELETE RESTRICT,
            public_appearance_origin_entity_row_version BIGINT,
            public_background           TEXT,
            public_background_origin_id UUID NOT NULL
                                        REFERENCES campaign.public_profile_field_origins(
                                            public_profile_field_origin_id) ON DELETE RESTRICT,
            public_background_origin_entity_row_version BIGINT,
            row_version                 BIGINT NOT NULL DEFAULT 1,
            created_by_membership_id    UUID
                                        REFERENCES security.campaign_memberships(
                                            campaign_membership_id) ON DELETE SET NULL,
            updated_by_membership_id    UUID
                                        REFERENCES security.campaign_memberships(
                                            campaign_membership_id) ON DELETE SET NULL,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_character_public_profiles_campaign_character
                UNIQUE (campaign_id, character_id),
            CONSTRAINT ux_character_public_profiles_scope
                UNIQUE (character_public_profile_id, campaign_id, character_id),
            CONSTRAINT ck_character_public_profiles_row_version_positive CHECK (row_version >= 1),
            CONSTRAINT ck_character_public_profiles_appearance_length
                CHECK (public_appearance IS NULL OR char_length(public_appearance) <= {_TEXT_MAX}),
            CONSTRAINT ck_character_public_profiles_background_length
                CHECK (public_background IS NULL OR char_length(public_background) <= {_TEXT_MAX})
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.character_public_profiles IS
        'The mutable public-profile draft of one character in one campaign (P03-A A2). GM-only. '
        'Never visible to an audience: only a release, made visible by a later revelation, is. '
        'One row per (campaign, character); campaign B has its own draft for the same character.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profiles.public_appearance IS
        'Draft text for the public appearance; at most 4000 characters (the legacy source '
        'field''s limit). GM-only until released.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profiles.public_background IS
        'Draft text for the public background; at most 4000 characters. GM-only until released.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profiles.public_appearance_origin_entity_row_version IS
        'The character''s core.entities.row_version when the appearance text was copied from '
        'legacy material; NULL unless the origin is a legacy origin.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profiles.public_background_origin_entity_row_version IS
        'The character''s core.entities.row_version when the background text was copied from '
        'legacy material; NULL unless the origin is a legacy origin.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profiles.row_version IS
        'Optimistic-concurrency token, incremented by every UPDATE (core.bump_row_version()). '
        'A save and a release name it as the draft version they were made against.';
    """)
    for index, column, partial in (
        ("character_id", "character_id", False),
        ("appearance_origin_id", "public_appearance_origin_id", False),
        ("background_origin_id", "public_background_origin_id", False),
        ("created_by", "created_by_membership_id", True),
        ("updated_by", "updated_by_membership_id", True),
    ):
        where = f" WHERE {column} IS NOT NULL" if partial else ""
        op.execute(
            f"CREATE INDEX ix_character_public_profiles_{index} "
            f"ON campaign.character_public_profiles ({column}){where};"
        )
    op.execute("""
        CREATE TRIGGER tr_character_public_profiles_set_updated_at
        BEFORE UPDATE ON campaign.character_public_profiles
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_character_public_profiles_bump_row_version
        BEFORE UPDATE ON campaign.character_public_profiles
        FOR EACH ROW EXECUTE FUNCTION core.bump_row_version();
    """)
    op.execute("""
        CREATE TRIGGER tr_character_public_profiles_enforce_immutable
        BEFORE UPDATE ON campaign.character_public_profiles
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns(
            'campaign_id', 'character_id', 'created_at'
        );
    """)

    op.execute(f"""
        CREATE TABLE campaign.character_public_profile_releases (
            character_public_profile_release_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            character_public_profile_id UUID NOT NULL,
            campaign_id                 UUID NOT NULL
                                        REFERENCES campaign.campaigns(campaign_id)
                                        ON DELETE RESTRICT,
            character_id                UUID NOT NULL
                                        REFERENCES character.characters(character_id)
                                        ON DELETE RESTRICT,
            version_number              INTEGER NOT NULL,
            from_draft_row_version      BIGINT NOT NULL,
            public_appearance           TEXT,
            public_appearance_origin_id UUID NOT NULL
                                        REFERENCES campaign.public_profile_field_origins(
                                            public_profile_field_origin_id) ON DELETE RESTRICT,
            public_appearance_origin_entity_row_version BIGINT,
            public_background           TEXT,
            public_background_origin_id UUID NOT NULL
                                        REFERENCES campaign.public_profile_field_origins(
                                            public_profile_field_origin_id) ON DELETE RESTRICT,
            public_background_origin_entity_row_version BIGINT,
            authority_source_code       TEXT NOT NULL,
            character_reveal_delegation_id UUID
                                        REFERENCES security.character_reveal_delegations(
                                            character_reveal_delegation_id),
            released_by_membership_id   UUID NOT NULL
                                        REFERENCES security.campaign_memberships(
                                            campaign_membership_id),
            released_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            release_note                TEXT,
            CONSTRAINT fk_character_public_profile_releases_profile
                FOREIGN KEY (character_public_profile_id, campaign_id, character_id)
                REFERENCES campaign.character_public_profiles (
                    character_public_profile_id, campaign_id, character_id),
            CONSTRAINT ux_character_public_profile_releases_version
                UNIQUE (character_public_profile_id, version_number),
            CONSTRAINT ux_character_public_profile_releases_draft_version
                UNIQUE (character_public_profile_id, from_draft_row_version),
            CONSTRAINT ck_character_public_profile_releases_version_positive
                CHECK (version_number >= 1),
            CONSTRAINT ck_character_public_profile_releases_draft_version_positive
                CHECK (from_draft_row_version >= 1),
            CONSTRAINT ck_character_public_profile_releases_appearance_length
                CHECK (public_appearance IS NULL OR char_length(public_appearance) <= {_TEXT_MAX}),
            CONSTRAINT ck_character_public_profile_releases_background_length
                CHECK (public_background IS NULL OR char_length(public_background) <= {_TEXT_MAX}),
            CONSTRAINT ck_character_public_profile_releases_authority_source
                CHECK (authority_source_code IN ('owner', 'delegation')),
            CONSTRAINT ck_character_public_profile_releases_delegation_pairing CHECK (
                (authority_source_code = 'delegation')
                = (character_reveal_delegation_id IS NOT NULL)
            ),
            CONSTRAINT ck_character_public_profile_releases_note_length
                CHECK (release_note IS NULL OR char_length(release_note) BETWEEN 1 AND 1000)
        );
    """)
    op.execute("""
        COMMENT ON TABLE campaign.character_public_profile_releases IS
        'An immutable, versioned snapshot of a character''s public-profile draft in one campaign '
        '(P03-A A2). Append-only: UPDATE, DELETE and TRUNCATE are refused. A release outlives '
        'the authority that made it. It makes nothing visible by itself; an audience sees the '
        'latest release only through a revelation.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profile_releases.version_number IS
        'Gapless 1..n per profile, allocated under the draft row lock.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profile_releases.from_draft_row_version IS
        'The draft row_version this release snapshots. Unique per profile: a draft version is '
        'released at most once, which makes it the natural retry key.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profile_releases.public_appearance IS
        'Snapshot of the draft''s public appearance at from_draft_row_version.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profile_releases.public_background IS
        'Snapshot of the draft''s public background at from_draft_row_version.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profile_releases.authority_source_code IS
        'How the releaser held character.reveal: owner (a live built-in campaign_owner '
        'assignment) or delegation (a live reveal delegation).';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profile_releases.character_reveal_delegation_id IS
        'The delegation the release was made under; NULL unless authority_source_code is '
        'delegation. The delegation may have ended since; the release stays.';
    """)
    op.execute("""
        COMMENT ON COLUMN campaign.character_public_profile_releases.release_note IS
        'An optional GM-only note on why the release was made. Never shown to an audience.';
    """)
    for index, column, partial in (
        ("campaign_id", "campaign_id", False),
        ("character_id", "character_id", False),
        ("appearance_origin_id", "public_appearance_origin_id", False),
        ("background_origin_id", "public_background_origin_id", False),
        ("delegation", "character_reveal_delegation_id", True),
        ("released_by", "released_by_membership_id", False),
    ):
        where = f" WHERE {column} IS NOT NULL" if partial else ""
        op.execute(
            f"CREATE INDEX ix_character_public_profile_releases_{index} "
            f"ON campaign.character_public_profile_releases ({column}){where};"
        )

    # --- local integrity triggers ---------------------------------------------------------------
    op.execute("""
        CREATE FUNCTION campaign.enforce_public_profile_scope()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_world UUID;
            v_character_world UUID;
            v_membership_campaign UUID;
            v_delegation_campaign UUID;
            v_delegation_grantee UUID;
        BEGIN
            SELECT t.world_id INTO v_world
            FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = NEW.campaign_id;
            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;
            IF v_world IS DISTINCT FROM v_character_world THEN
                RAISE EXCEPTION 'Character % is not in the world of campaign %',
                    NEW.character_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF TG_TABLE_NAME = 'character_public_profiles' THEN
                IF NEW.created_by_membership_id IS NOT NULL THEN
                    SELECT campaign_id INTO v_membership_campaign
                    FROM security.campaign_memberships
                    WHERE campaign_membership_id = NEW.created_by_membership_id;
                    IF v_membership_campaign IS DISTINCT FROM NEW.campaign_id THEN
                        RAISE EXCEPTION 'Membership % does not belong to campaign %',
                            NEW.created_by_membership_id, NEW.campaign_id
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                END IF;
                IF NEW.updated_by_membership_id IS NOT NULL THEN
                    SELECT campaign_id INTO v_membership_campaign
                    FROM security.campaign_memberships
                    WHERE campaign_membership_id = NEW.updated_by_membership_id;
                    IF v_membership_campaign IS DISTINCT FROM NEW.campaign_id THEN
                        RAISE EXCEPTION 'Membership % does not belong to campaign %',
                            NEW.updated_by_membership_id, NEW.campaign_id
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                END IF;
            ELSE
                SELECT campaign_id INTO v_membership_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.released_by_membership_id;
                IF v_membership_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION 'Releasing membership % does not belong to campaign %',
                        NEW.released_by_membership_id, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF NEW.character_reveal_delegation_id IS NOT NULL THEN
                    SELECT campaign_id, grantee_campaign_membership_id
                    INTO v_delegation_campaign, v_delegation_grantee
                    FROM security.character_reveal_delegations
                    WHERE character_reveal_delegation_id = NEW.character_reveal_delegation_id;
                    IF v_delegation_campaign IS DISTINCT FROM NEW.campaign_id
                       OR v_delegation_grantee IS DISTINCT FROM NEW.released_by_membership_id THEN
                        RAISE EXCEPTION
                            'Delegation % is not a delegation of campaign % to the releaser',
                            NEW.character_reveal_delegation_id, NEW.campaign_id
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_public_profile_scope() IS
        'A public-profile draft or release names one campaign: the character must be in the '
        'campaign''s world, the acting memberships must belong to the campaign, and a release''s '
        'delegation must be a delegation of that campaign to the releasing membership.';
    """)
    for table, stem in (
        ("character_public_profiles", "character_public_profiles"),
        ("character_public_profile_releases", "character_public_profile_releases"),
    ):
        op.execute(f"""
            CREATE TRIGGER tr_{stem}_enforce_scope
            BEFORE INSERT OR UPDATE ON campaign.{table}
            FOR EACH ROW EXECUTE FUNCTION campaign.enforce_public_profile_scope();
        """)

    op.execute("""
        CREATE FUNCTION campaign.enforce_public_profile_field_origins()
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
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_public_profile_field_origins() IS
        'Each public-profile field''s origin must suit the field, carry the source row version '
        'exactly when it is a legacy origin, and be the authored origin for empty text.';
    """)
    for table in ("character_public_profiles", "character_public_profile_releases"):
        op.execute(f"""
            CREATE TRIGGER tr_{table}_enforce_origins
            BEFORE INSERT OR UPDATE ON campaign.{table}
            FOR EACH ROW EXECUTE FUNCTION campaign.enforce_public_profile_field_origins();
        """)

    op.execute("""
        CREATE FUNCTION campaign.enforce_public_profile_release_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION
                'campaign.character_public_profile_releases is append-only: a release is permanent'
                USING ERRCODE = 'integrity_constraint_violation';
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_public_profile_release_immutable() IS
        'Refuses every UPDATE, DELETE and TRUNCATE of campaign.character_public_profile_releases.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_public_profile_releases_immutable
        BEFORE UPDATE OR DELETE ON campaign.character_public_profile_releases
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_public_profile_release_immutable();
    """)
    op.execute("""
        CREATE TRIGGER tr_character_public_profile_releases_no_truncate
        BEFORE TRUNCATE ON campaign.character_public_profile_releases
        FOR EACH STATEMENT EXECUTE FUNCTION campaign.enforce_public_profile_release_immutable();
    """)

    # Grant-level boundary: a release is append-only and a draft is never deleted by the
    # application. The reporting role reads neither (deny-by-default since revision 115).
    for role in _APP_ROLES:
        op.execute(
            f"REVOKE UPDATE, DELETE, TRUNCATE ON campaign.character_public_profile_releases "
            f"FROM {role};"
        )
        op.execute(f"REVOKE DELETE, TRUNCATE ON campaign.character_public_profiles FROM {role};")
    op.execute("REVOKE ALL ON campaign.character_public_profile_releases FROM app_read_only;")
    op.execute("REVOKE ALL ON campaign.character_public_profiles FROM app_read_only;")


def downgrade() -> None:
    """Revert the migration (lossy: every draft and release is dropped)."""
    op.execute("DROP TABLE IF EXISTS campaign.character_public_profile_releases;")
    op.execute("DROP TABLE IF EXISTS campaign.character_public_profiles;")
    op.execute("DROP TABLE IF EXISTS campaign.public_profile_field_origins;")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_public_profile_release_immutable();")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_public_profile_field_origins();")
    op.execute("DROP FUNCTION IF EXISTS campaign.enforce_public_profile_scope();")
