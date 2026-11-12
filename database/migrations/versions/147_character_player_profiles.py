"""Add campaign-scoped character player-profile storage (infrastructure, no application writer)

Revision ID: 147_character_player_profiles
Revises: 146_public_profile_identity
Create Date: 2026-11-11 12:00:00.000000

Purpose:
    P03-A slice A5a (docs/PHASE15_P03A_A5_PLAYER_PROFILE_DESIGN_2026-11-11.md section 6.1,
    decisions D13, D17 and D18). OD-18 gives each character a *player profile* in each campaign:
    narrative the character's controllers write for the campaign's GMs and for the character's
    eligible controllers. It is separate from world canon (`character.character_descriptions`) and
    from GM-private portrayal, and it is never canon. This revision is **storage only**: the
    application roles can SELECT the tables and cannot write them, because the writer (the
    controller edit command, its grants, attribution and authorization) arrives with P03-B.
    Tests populate valid versions through `tests/player_profile_support.py`.

Forward migration:
    1. Creates the lookup `campaign.player_profile_fields` (the eleven D13 fields, with whether a
       field may later be copied into a public-profile draft). `boundaries` and `profile_notes` are
       not copy-eligible. `profile_notes` is shared with GMs and controllers; it is not a private
       notebook.
    2. Creates `campaign.character_player_profiles`, the mutable head and the lock anchor: one row
       per (campaign, character), `row_version` kept current by `core.bump_row_version()`, and no
       text columns.
    3. Creates `campaign.character_player_profile_versions`, the append-only versions: one row per
       profile state, attributed to the editing campaign membership. A composite foreign key stops
       a version naming another campaign's or another character's head.
    4. Adds local integrity triggers (docs/DATABASE_CONVENTIONS.md section 20.4): scope (the
       character is in the campaign's world and the editing membership belongs to the campaign), a
       version must carry the head's current `row_version`, a head must have a version at its
       `row_version` by commit (DEFERRABLE INITIALLY DEFERRED), and versions refuse UPDATE, DELETE
       and TRUNCATE.
    5. Revokes INSERT/UPDATE/DELETE/TRUNCATE on all three tables from `app_read_write` and
       `integration_worker`, and every privilege on the profile tables from `app_read_only`.

Rollback:
    Guarded. Refuses, changing nothing, while any head or version row exists: player-authored
    content cannot be recreated. On an empty store it drops the tables, functions and lookup.

Data implications:
    Only the eleven lookup rows are inserted. Nothing is backfilled; every character has no profile
    after the upgrade.

Locking considerations:
    DDL on new tables and an insert into a new lookup; no rewrite of any existing table.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "147_character_player_profiles"
down_revision = "146_public_profile_identity"
branch_labels = None
depends_on = None

# (code, display name, description, is_copy_eligible). Order is the sort order (x10).
_FIELDS = (
    (
        "portrayal_guidance",
        "Portrayal guidance",
        "How the player would like the character portrayed.",
        True,
    ),
    ("personality", "Personality", "The character's temperament and manner.", True),
    ("ideals", "Ideals", "What the character believes in.", True),
    ("bonds", "Bonds", "The people, places and causes the character is tied to.", True),
    ("flaws", "Flaws", "The character's weaknesses and vices.", True),
    ("goals", "Goals", "What the character is trying to achieve.", True),
    ("fears", "Fears", "What the character fears.", True),
    ("loyalties", "Loyalties", "Whom or what the character is loyal to.", True),
    (
        "boundaries",
        "Boundaries",
        "Topics the player asks the table to handle with care. Never copied into a public profile.",
        False,
    ),
    ("speech_patterns", "Speech patterns", "How the character speaks.", True),
    (
        "profile_notes",
        "Notes for the GM and controllers",
        "Notes written for the campaign's GMs and the character's controllers. Not a private "
        "notebook, and never copied into a public profile.",
        False,
    ),
)

_TEXT_MAX = 4000  # PUBLIC_PROFILE_TEXT_MAX_LENGTH, so any copy fits a public field

_APP_ROLES = ("app_read_write", "integration_worker")
_HEAD = "campaign.character_player_profiles"
_VERSIONS = "campaign.character_player_profile_versions"
_LOOKUP = "campaign.player_profile_fields"


def upgrade() -> None:
    """Apply the migration."""
    op.execute(f"""
        CREATE TABLE {_LOOKUP} (
            player_profile_field_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code             TEXT NOT NULL,
            display_name     TEXT NOT NULL,
            description      TEXT,
            is_copy_eligible BOOLEAN NOT NULL,
            sort_order       core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active        BOOLEAN NOT NULL DEFAULT true,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_player_profile_fields_code UNIQUE (code),
            CONSTRAINT ck_player_profile_fields_code_length CHECK (char_length(code) <= 100),
            CONSTRAINT ck_player_profile_fields_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute(f"""
        COMMENT ON TABLE {_LOOKUP} IS
        'The fields of a character''s campaign player profile (P03-A A5, decision D13) and whether '
        'a field may later be copied into a public-profile draft. A catalog, not a safety label.';
    """)
    op.execute(f"""
        COMMENT ON COLUMN {_LOOKUP}.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute(f"""
        COMMENT ON COLUMN {_LOOKUP}.is_copy_eligible IS
        'Whether the field may be copied into a public-profile draft. False for boundaries and '
        'profile_notes, which no structured publication may carry. Manual transcription by an '
        'authorized reader is not prevented.';
    """)
    op.execute(f"""
        CREATE TRIGGER tr_player_profile_fields_set_updated_at
        BEFORE UPDATE ON {_LOOKUP}
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    for index, (code, display_name, description, eligible) in enumerate(_FIELDS, start=1):
        quoted_description = description.replace("'", "''")
        op.execute(f"""
            INSERT INTO {_LOOKUP} (code, display_name, description, is_copy_eligible, sort_order)
            VALUES ('{code}', '{display_name}', '{quoted_description}', {str(eligible).lower()},
                    {index * 10})
            ON CONFLICT (code) DO NOTHING;
        """)

    # --- the head -------------------------------------------------------------------------------
    op.execute(f"""
        CREATE TABLE {_HEAD} (
            character_player_profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id  UUID NOT NULL
                         REFERENCES campaign.campaigns(campaign_id) ON DELETE RESTRICT,
            character_id UUID NOT NULL
                         REFERENCES character.characters(character_id) ON DELETE RESTRICT,
            row_version  BIGINT NOT NULL DEFAULT 1,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_character_player_profiles_campaign_character
                UNIQUE (campaign_id, character_id),
            CONSTRAINT ux_character_player_profiles_scope
                UNIQUE (character_player_profile_id, campaign_id, character_id),
            CONSTRAINT ck_character_player_profiles_row_version_positive CHECK (row_version >= 1)
        );
    """)
    op.execute(f"""
        COMMENT ON TABLE {_HEAD} IS
        'The head of one character''s player profile in one campaign (P03-A A5): the player-authored '
        'narrative for the campaign''s GMs and the character''s controllers. Never world canon and '
        'never a GM-private store. One row per (campaign, character); campaign B has its own for the '
        'same character. It holds no text: content lives in character_player_profile_versions. It is '
        'the lock anchor of the edit protocol. The application cannot write it until P03-B.';
    """)
    op.execute(f"""
        COMMENT ON COLUMN {_HEAD}.row_version IS
        'Optimistic-concurrency token, incremented by every UPDATE (core.bump_row_version()). Every '
        'value has exactly one version row, checked at commit.';
    """)
    op.execute(f"CREATE INDEX ix_character_player_profiles_character_id ON {_HEAD} (character_id);")
    op.execute(f"""
        CREATE TRIGGER tr_character_player_profiles_set_updated_at
        BEFORE UPDATE ON {_HEAD}
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_player_profiles_bump_row_version
        BEFORE UPDATE ON {_HEAD}
        FOR EACH ROW EXECUTE FUNCTION core.bump_row_version();
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_player_profiles_enforce_immutable
        BEFORE UPDATE ON {_HEAD}
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns(
            'campaign_id', 'character_id', 'created_at'
        );
    """)

    # --- the versions ---------------------------------------------------------------------------
    field_columns = ",\n            ".join(f"{code} TEXT" for code, *_ in _FIELDS)
    field_checks = ",\n            ".join(
        f"CONSTRAINT ck_character_player_profile_versions_{code}_text CHECK ("
        f"{code} IS NULL OR (char_length({code}) <= {_TEXT_MAX} AND {code} ~ '\\S'))"
        for code, *_ in _FIELDS
    )
    op.execute(f"""
        CREATE TABLE {_VERSIONS} (
            character_player_profile_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            character_player_profile_id UUID NOT NULL,
            campaign_id  UUID NOT NULL
                         REFERENCES campaign.campaigns(campaign_id) ON DELETE RESTRICT,
            character_id UUID NOT NULL
                         REFERENCES character.characters(character_id) ON DELETE RESTRICT,
            profile_row_version BIGINT NOT NULL,
            {field_columns},
            edited_by_campaign_membership_id UUID NOT NULL
                         REFERENCES security.campaign_memberships(campaign_membership_id),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_character_player_profile_versions_profile
                FOREIGN KEY (character_player_profile_id, campaign_id, character_id)
                REFERENCES {_HEAD} (character_player_profile_id, campaign_id, character_id),
            CONSTRAINT ux_character_player_profile_versions_row_version
                UNIQUE (character_player_profile_id, profile_row_version),
            CONSTRAINT ux_character_player_profile_versions_scope
                UNIQUE (character_player_profile_version_id, campaign_id, character_id),
            CONSTRAINT ck_character_player_profile_versions_row_version_positive
                CHECK (profile_row_version >= 1),
            {field_checks}
        );
    """)
    op.execute(f"""
        COMMENT ON TABLE {_VERSIONS} IS
        'Immutable versions of a character''s campaign player profile (P03-A A5): one row per profile '
        'state, attributed to the editing campaign membership. Append-only: UPDATE, DELETE and '
        'TRUNCATE are refused. Player-authored, campaign-scoped, never canon. The application cannot '
        'write it until P03-B.';
    """)
    comments = {
        "profile_row_version": (
            "The head row_version this version made current; unique per profile. The version with "
            "the head's current row_version is the current profile."
        ),
        "edited_by_campaign_membership_id": (
            "The campaign membership that made this edit (attribution). The membership may have "
            "ended since; the version keeps naming it."
        ),
        "created_at": "When this version was written.",
    }
    for code, display_name, *_ in _FIELDS:
        shared = (
            "Shared with the campaign's GMs and the character's controllers; not a private "
            "notebook. Never copied into a public profile."
            if code == "profile_notes"
            else "Never copied into a public profile."
            if code == "boundaries"
            else "May be copied into a public-profile draft by a GM."
        )
        comments[code] = (
            f"{display_name}: player-authored profile text, at most {_TEXT_MAX} characters, NULL "
            f"when empty (whitespace-only text is refused). {shared}"
        )
    for column, comment in comments.items():
        escaped = comment.replace("'", "''")
        op.execute(f"COMMENT ON COLUMN {_VERSIONS}.{column} IS '{escaped}';")
    op.execute(
        f"CREATE INDEX ix_character_player_profile_versions_editor "
        f"ON {_VERSIONS} (edited_by_campaign_membership_id);"
    )
    op.execute(
        f"CREATE INDEX ix_character_player_profile_versions_campaign_id ON {_VERSIONS} (campaign_id);"
    )
    op.execute(
        f"CREATE INDEX ix_character_player_profile_versions_character_id "
        f"ON {_VERSIONS} (character_id);"
    )

    # --- local integrity triggers ---------------------------------------------------------------
    op.execute("""
        CREATE FUNCTION campaign.enforce_player_profile_scope()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_world UUID;
            v_character_world UUID;
            v_membership_campaign UUID;
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
            IF TG_TABLE_NAME = 'character_player_profile_versions' THEN
                SELECT campaign_id INTO v_membership_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.edited_by_campaign_membership_id;
                IF v_membership_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION 'Editing membership % does not belong to campaign %',
                        NEW.edited_by_campaign_membership_id, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_player_profile_scope() IS
        'A player profile or one of its versions names one campaign: the character must be in the '
        'campaign''s world, and a version''s editing membership must belong to the campaign.';
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_player_profiles_enforce_scope
        BEFORE INSERT OR UPDATE ON {_HEAD}
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_player_profile_scope();
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_player_profile_versions_enforce_scope
        BEFORE INSERT ON {_VERSIONS}
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_player_profile_scope();
    """)

    op.execute("""
        CREATE FUNCTION campaign.enforce_player_profile_version_matches_head()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_head_version BIGINT;
        BEGIN
            SELECT row_version INTO v_head_version
            FROM campaign.character_player_profiles
            WHERE character_player_profile_id = NEW.character_player_profile_id;
            IF v_head_version IS DISTINCT FROM NEW.profile_row_version THEN
                RAISE EXCEPTION
                    'A player-profile version must carry its head''s current row_version'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_player_profile_version_matches_head() IS
        'A new player-profile version must carry the head''s current row_version, so a writer bumps '
        'the head first and inserts the version it made current.';
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_player_profile_versions_match_head
        BEFORE INSERT ON {_VERSIONS}
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_player_profile_version_matches_head();
    """)

    op.execute("""
        CREATE FUNCTION campaign.enforce_player_profile_head_has_version()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM campaign.character_player_profile_versions
                WHERE character_player_profile_id = NEW.character_player_profile_id
                  AND profile_row_version = NEW.row_version
            ) THEN
                RAISE EXCEPTION
                    'Player profile % has no version at row_version %',
                    NEW.character_player_profile_id, NEW.row_version
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NULL;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_player_profile_head_has_version() IS
        'At commit, a player-profile head must have a version at its current row_version: a head '
        'never exists, or advances, without the content it made current.';
    """)
    op.execute(f"""
        CREATE CONSTRAINT TRIGGER tr_character_player_profiles_has_version
        AFTER INSERT OR UPDATE ON {_HEAD}
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_player_profile_head_has_version();
    """)

    op.execute("""
        CREATE FUNCTION campaign.enforce_player_profile_version_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION
                'campaign.character_player_profile_versions is append-only: a version is permanent'
                USING ERRCODE = 'integrity_constraint_violation';
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION campaign.enforce_player_profile_version_immutable() IS
        'Refuses every UPDATE, DELETE and TRUNCATE of campaign.character_player_profile_versions.';
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_player_profile_versions_immutable
        BEFORE UPDATE OR DELETE ON {_VERSIONS}
        FOR EACH ROW EXECUTE FUNCTION campaign.enforce_player_profile_version_immutable();
    """)
    op.execute(f"""
        CREATE TRIGGER tr_character_player_profile_versions_no_truncate
        BEFORE TRUNCATE ON {_VERSIONS}
        FOR EACH STATEMENT EXECUTE FUNCTION campaign.enforce_player_profile_version_immutable();
    """)

    # D18 at the grant level: the application reads the profile and writes none of it. The
    # reporting role reads neither profile table (deny-by-default since revision 115).
    for role in _APP_ROLES:
        for table in (_LOOKUP, _HEAD, _VERSIONS):
            op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {table} FROM {role};")
    op.execute(f"REVOKE ALL ON {_HEAD} FROM app_read_only;")
    op.execute(f"REVOKE ALL ON {_VERSIONS} FROM app_read_only;")


def downgrade() -> None:
    """Revert the migration, refusing (and changing nothing) while any profile content exists."""
    op.execute(f"""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM {_HEAD}) OR EXISTS (SELECT 1 FROM {_VERSIONS}) THEN
                RAISE EXCEPTION
                    'Refusing to downgrade 147: player-authored profile content exists and cannot '
                    'be recreated'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END
        $guard$;
    """)
    op.execute(f"DROP TABLE {_VERSIONS};")
    op.execute(f"DROP TABLE {_HEAD};")
    op.execute(f"DROP TABLE {_LOOKUP};")
    op.execute("DROP FUNCTION campaign.enforce_player_profile_version_immutable();")
    op.execute("DROP FUNCTION campaign.enforce_player_profile_head_has_version();")
    op.execute("DROP FUNCTION campaign.enforce_player_profile_version_matches_head();")
    op.execute("DROP FUNCTION campaign.enforce_player_profile_scope();")
