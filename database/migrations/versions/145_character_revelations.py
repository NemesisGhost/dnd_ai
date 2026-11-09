"""Add character revelations, the audience snapshot, character.view_public_profile and public_summary

Revision ID: 145_character_revelations
Revises: 144_profile_provenance_guard
Create Date: 2026-11-08 12:00:00.000000

Purpose:
    P03-A slice A3a (docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md section 10). A
    revelation makes a character discoverable, and its latest public-profile release readable, to
    one member, one access group, the campaign's current members, or its current and future
    members. A3a is storage only: no audience response reads these tables yet (A3b).

Forward migration:
    1. Creates the lookup `security.revelation_audience_kinds` (`member`, `access_group`,
       `campaign_current`, `campaign_current_and_future`).
    2. Creates `security.character_revelations`: closed at most once, otherwise immutable, one live
       row per audience (partial unique index, NULLS NOT DISTINCT), with triggers for the target
       shape, the same-campaign scope and the release precondition (a release must exist for the
       character in the campaign when the row is inserted).
    3. Creates `security.character_revelation_members`, the `campaign_current` snapshot. Rows can
       be inserted only by the transaction that created the revelation, and only ever have
       `removed_at` set (once).
    4. Inserts the `character.view_public_profile` capability row (the seed file is frozen) and
       refuses any role capability, relationship-type capability or `allow` resource grant naming
       it: its only allow source is a revelation.
    5. Adds the nullable, authored-only `public_summary` to the public-profile draft and release.
    6. Revokes UPDATE (except the closure columns), DELETE and TRUNCATE from the application roles.

Rollback:
    Supported but lossy: drops the three tables, the functions, the capability row and both
    `public_summary` columns. It refuses first, atomically, while any role capability,
    relationship-type capability or resource grant names `character.view_public_profile`.

Data implications:
    No backfill. After the upgrade no character has a revelation and every response is unchanged.

Locking considerations:
    DDL on new tables, two ADD COLUMN (nullable, no rewrite) on small tables, and triggers on three
    existing tables (brief SHARE ROW EXCLUSIVE locks).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "145_character_revelations"
down_revision = "144_profile_provenance_guard"
branch_labels = None
depends_on = None

_CAPABILITY = "character.view_public_profile"
_SUMMARY_MAX = 4000
_APP_ROLES = ("app_read_write", "integration_worker")

_KINDS = (
    ("member", "Member", "One campaign member.", 10),
    ("access_group", "Access group", "The members of one access group.", 20),
    (
        "campaign_current",
        "Campaign, current members",
        "The active members of the campaign at the moment of creation (a snapshot).",
        30,
    ),
    (
        "campaign_current_and_future",
        "Campaign, current and future members",
        "Every active member of the campaign, whenever they joined.",
        40,
    ),
)

_END_REASONS = ("revoked", "target_membership_ended", "access_group_deactivated")

# (table, trigger-name stem) for the capability guard; the relationship-type table's full name
# would push the trigger name past PostgreSQL's 63-byte identifier limit.
_GUARDED_TABLES = (
    ("role_capabilities", "role_capabilities"),
    ("character_relationship_type_capabilities", "relationship_type_capabilities"),
    ("resource_grants", "resource_grants"),
)


def upgrade() -> None:
    """Apply the migration."""
    op.execute("""
        CREATE TABLE security.revelation_audience_kinds (
            revelation_audience_kind_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_revelation_audience_kinds_code UNIQUE (code),
            CONSTRAINT ck_revelation_audience_kinds_code_length CHECK (char_length(code) <= 100),
            CONSTRAINT ck_revelation_audience_kinds_code_format
                CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.revelation_audience_kinds IS
        'Who a character revelation reaches: one member, one access group, the campaign''s '
        'current members (a snapshot), or its current and future members (P03-A A3).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.revelation_audience_kinds.code IS
        'Stable machine-readable identifier. Application logic may reference '
        'codes, but foreign keys use IDs (conventions §11.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_revelation_audience_kinds_set_updated_at
        BEFORE UPDATE ON security.revelation_audience_kinds
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    for code, display_name, description, sort_order in _KINDS:
        op.execute(f"""
            INSERT INTO security.revelation_audience_kinds
                (code, display_name, description, sort_order)
            VALUES ('{code}', '{display_name}', '{description}', {sort_order})
            ON CONFLICT (code) DO NOTHING;
        """)

    end_reasons = ", ".join(f"'{reason}'" for reason in _END_REASONS)
    op.execute(f"""
        CREATE TABLE security.character_revelations (
            character_revelation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id             UUID NOT NULL
                                    REFERENCES campaign.campaigns(campaign_id)
                                    ON DELETE RESTRICT,
            character_id            UUID NOT NULL
                                    REFERENCES character.characters(character_id)
                                    ON DELETE RESTRICT,
            revelation_audience_kind_id UUID NOT NULL
                                    REFERENCES security.revelation_audience_kinds(
                                        revelation_audience_kind_id) ON DELETE RESTRICT,
            target_campaign_membership_id UUID
                                    REFERENCES security.campaign_memberships(
                                        campaign_membership_id) ON DELETE RESTRICT,
            target_access_group_id  UUID
                                    REFERENCES security.access_groups(access_group_id)
                                    ON DELETE RESTRICT,
            created_by_membership_id UUID NOT NULL
                                    REFERENCES security.campaign_memberships(
                                        campaign_membership_id) ON DELETE RESTRICT,
            authority_source_code   TEXT NOT NULL,
            character_reveal_delegation_id UUID
                                    REFERENCES security.character_reveal_delegations(
                                        character_reveal_delegation_id) ON DELETE RESTRICT,
            reason                  TEXT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at                TIMESTAMPTZ,
            ended_by_membership_id  UUID
                                    REFERENCES security.campaign_memberships(
                                        campaign_membership_id) ON DELETE RESTRICT,
            end_reason              TEXT,
            revocation_reason       TEXT,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_character_revelations_reason
                CHECK (char_length(reason) BETWEEN 1 AND 1000),
            CONSTRAINT ck_character_revelations_revocation_reason
                CHECK (revocation_reason IS NULL OR char_length(revocation_reason) BETWEEN 1 AND 1000),
            CONSTRAINT ck_character_revelations_authority_source
                CHECK (authority_source_code IN ('owner', 'delegation')),
            CONSTRAINT ck_character_revelations_delegation_pairing CHECK (
                (authority_source_code = 'delegation')
                = (character_reveal_delegation_id IS NOT NULL)
            ),
            CONSTRAINT ck_character_revelations_end_reason_values
                CHECK (end_reason IS NULL OR end_reason IN ({end_reasons})),
            CONSTRAINT ck_character_revelations_closure_together
                CHECK ((ended_at IS NULL) = (end_reason IS NULL)),
            CONSTRAINT ck_character_revelations_revoker_only_for_revocation CHECK (
                end_reason = 'revoked'
                OR (ended_by_membership_id IS NULL AND revocation_reason IS NULL)
            ),
            CONSTRAINT ck_character_revelations_revocation_complete CHECK (
                end_reason IS DISTINCT FROM 'revoked'
                OR (ended_by_membership_id IS NOT NULL AND revocation_reason IS NOT NULL)
            ),
            CONSTRAINT ck_character_revelations_ended_after_created
                CHECK (ended_at IS NULL OR ended_at >= created_at)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.character_revelations IS
        'A deliberate revelation of one character to an audience in one campaign (P03-A A3): a '
        'member, an access group, the campaign''s current members (a snapshot in '
        'character_revelation_members) or its current and future members. It confers discovery '
        'and the character''s latest public-profile release for that character only, and '
        'survives the revealer losing authority. Closed at most once (ended_at/end_reason), '
        'never otherwise edited; one live row per audience.';
    """)
    for stem, column in (
        ("campaign_id", "campaign_id"),
        ("character_id", "character_id"),
        ("kind", "revelation_audience_kind_id"),
    ):
        op.execute(
            f"CREATE INDEX ix_character_revelations_{stem} "
            f"ON security.character_revelations ({column});"
        )
    for stem, column in (
        ("target_membership", "target_campaign_membership_id"),
        ("target_group", "target_access_group_id"),
        ("delegation", "character_reveal_delegation_id"),
        ("ended_by", "ended_by_membership_id"),
    ):
        op.execute(
            f"CREATE INDEX ix_character_revelations_{stem} "
            f"ON security.character_revelations ({column}) WHERE {column} IS NOT NULL;"
        )
    op.execute(
        "CREATE INDEX ix_character_revelations_created_by "
        "ON security.character_revelations (created_by_membership_id);"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_character_revelations_live
        ON security.character_revelations (
            campaign_id, character_id, revelation_audience_kind_id,
            target_campaign_membership_id, target_access_group_id
        ) NULLS NOT DISTINCT
        WHERE ended_at IS NULL;
    """)
    op.execute("""
        CREATE TRIGGER tr_character_revelations_set_updated_at
        BEFORE UPDATE ON security.character_revelations
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TRIGGER tr_character_revelations_enforce_immutable
        BEFORE UPDATE ON security.character_revelations
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns(
            'campaign_id', 'character_id', 'revelation_audience_kind_id',
            'target_campaign_membership_id', 'target_access_group_id',
            'created_by_membership_id', 'authority_source_code',
            'character_reveal_delegation_id', 'reason', 'created_at'
        );
    """)

    op.execute("""
        CREATE FUNCTION security.enforce_character_revelation_shape_and_scope()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_kind TEXT;
            v_world UUID;
            v_character_world UUID;
            v_campaign UUID;
            v_grantee UUID;
        BEGIN
            SELECT code INTO v_kind FROM security.revelation_audience_kinds
            WHERE revelation_audience_kind_id = NEW.revelation_audience_kind_id;
            IF v_kind = 'member' AND (NEW.target_campaign_membership_id IS NULL
                                      OR NEW.target_access_group_id IS NOT NULL) THEN
                RAISE EXCEPTION 'A member revelation names exactly a membership target'
                    USING ERRCODE = 'integrity_constraint_violation';
            ELSIF v_kind = 'access_group' AND (NEW.target_access_group_id IS NULL
                                               OR NEW.target_campaign_membership_id IS NOT NULL) THEN
                RAISE EXCEPTION 'An access_group revelation names exactly a group target'
                    USING ERRCODE = 'integrity_constraint_violation';
            ELSIF v_kind IN ('campaign_current', 'campaign_current_and_future')
                  AND (NEW.target_campaign_membership_id IS NOT NULL
                       OR NEW.target_access_group_id IS NOT NULL) THEN
                RAISE EXCEPTION 'A campaign revelation names no target'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

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

            IF NEW.target_campaign_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_campaign FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.target_campaign_membership_id;
                IF v_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION 'Membership % does not belong to campaign %',
                        NEW.target_campaign_membership_id, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF NEW.target_access_group_id IS NOT NULL THEN
                SELECT campaign_id INTO v_campaign FROM security.access_groups
                WHERE access_group_id = NEW.target_access_group_id;
                IF v_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION 'Access group % does not belong to campaign %',
                        NEW.target_access_group_id, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            SELECT campaign_id INTO v_campaign FROM security.campaign_memberships
            WHERE campaign_membership_id = NEW.created_by_membership_id;
            IF v_campaign IS DISTINCT FROM NEW.campaign_id THEN
                RAISE EXCEPTION 'Creating membership % does not belong to campaign %',
                    NEW.created_by_membership_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.ended_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_campaign FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.ended_by_membership_id;
                IF v_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION 'Revoking membership % does not belong to campaign %',
                        NEW.ended_by_membership_id, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF NEW.character_reveal_delegation_id IS NOT NULL THEN
                SELECT campaign_id, grantee_campaign_membership_id INTO v_campaign, v_grantee
                FROM security.character_reveal_delegations
                WHERE character_reveal_delegation_id = NEW.character_reveal_delegation_id;
                IF v_campaign IS DISTINCT FROM NEW.campaign_id
                   OR v_grantee IS DISTINCT FROM NEW.created_by_membership_id THEN
                    RAISE EXCEPTION 'Delegation % is not a delegation of campaign % to the creator',
                        NEW.character_reveal_delegation_id, NEW.campaign_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            -- D9-d: a release must exist when the revelation is created. Releases are immutable
            -- and undeletable, so this can never later become false.
            IF TG_OP = 'INSERT' AND NOT EXISTS (
                SELECT 1 FROM campaign.character_public_profile_releases
                WHERE campaign_id = NEW.campaign_id AND character_id = NEW.character_id
            ) THEN
                RAISE EXCEPTION 'Character % has no release in campaign %',
                    NEW.character_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_character_revelation_shape_and_scope() IS
        'A revelation''s target shape must match its audience kind; the character, targets, '
        'creator, revoker and delegation must belong to the revelation''s campaign (and the '
        'delegation to the creator); and a release must exist when the row is inserted.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_revelations_enforce_shape_and_scope
        BEFORE INSERT OR UPDATE ON security.character_revelations
        FOR EACH ROW EXECUTE FUNCTION security.enforce_character_revelation_shape_and_scope();
    """)

    op.execute("""
        CREATE FUNCTION security.enforce_character_revelation_closed_once()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF OLD.ended_at IS NOT NULL THEN
                RAISE EXCEPTION 'Character revelation % is closed and cannot change',
                    OLD.character_revelation_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_character_revelation_closed_once() IS
        'A closed revelation (ended_at set) can never change again, so a revelation is closed at '
        'most once and never reopened.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_revelations_closed_once
        BEFORE UPDATE ON security.character_revelations
        FOR EACH ROW EXECUTE FUNCTION security.enforce_character_revelation_closed_once();
    """)

    op.execute("""
        CREATE TABLE security.character_revelation_members (
            character_revelation_member_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            character_revelation_id UUID NOT NULL
                                    REFERENCES security.character_revelations(
                                        character_revelation_id) ON DELETE RESTRICT,
            campaign_id             UUID NOT NULL
                                    REFERENCES campaign.campaigns(campaign_id)
                                    ON DELETE RESTRICT,
            campaign_membership_id  UUID NOT NULL
                                    REFERENCES security.campaign_memberships(
                                        campaign_membership_id) ON DELETE RESTRICT,
            added_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            removed_at              TIMESTAMPTZ,
            removal_reason          TEXT,
            CONSTRAINT ux_character_revelation_members_member
                UNIQUE (character_revelation_id, campaign_membership_id),
            CONSTRAINT ck_character_revelation_members_removal_together
                CHECK ((removed_at IS NULL) = (removal_reason IS NULL)),
            CONSTRAINT ck_character_revelation_members_removal_values
                CHECK (removal_reason IS NULL OR removal_reason = 'membership_ended')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.character_revelation_members IS
        'The campaign_current snapshot of a revelation (P03-A A3): the active memberships at the '
        'moment of creation. Rows are inserted only by the creating transaction; the only change '
        'ever made is setting removed_at once, when the membership ends. A reopened membership '
        'never regains a removed row.';
    """)
    op.execute(
        "CREATE INDEX ix_character_revelation_members_campaign_id "
        "ON security.character_revelation_members (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_character_revelation_members_membership "
        "ON security.character_revelation_members (campaign_membership_id);"
    )
    op.execute("""
        CREATE FUNCTION security.enforce_character_revelation_member_rules()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_kind TEXT;
            v_campaign UUID;
            v_created TIMESTAMPTZ;
            v_membership_campaign UUID;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF OLD.removed_at IS NOT NULL
                   OR NEW.removed_at IS NULL
                   OR NEW.character_revelation_id IS DISTINCT FROM OLD.character_revelation_id
                   OR NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
                   OR NEW.campaign_membership_id IS DISTINCT FROM OLD.campaign_membership_id
                   OR NEW.added_at IS DISTINCT FROM OLD.added_at THEN
                    RAISE EXCEPTION
                        'A snapshot row can only be removed, once (character_revelation_members)'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;

            SELECT k.code, r.campaign_id, r.created_at INTO v_kind, v_campaign, v_created
            FROM security.character_revelations r
            JOIN security.revelation_audience_kinds k
                ON k.revelation_audience_kind_id = r.revelation_audience_kind_id
            WHERE r.character_revelation_id = NEW.character_revelation_id;
            IF v_kind IS DISTINCT FROM 'campaign_current' THEN
                RAISE EXCEPTION 'Only a campaign_current revelation has a snapshot'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF v_campaign IS DISTINCT FROM NEW.campaign_id THEN
                RAISE EXCEPTION 'Snapshot campaign differs from the revelation''s'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            SELECT campaign_id INTO v_membership_campaign FROM security.campaign_memberships
            WHERE campaign_membership_id = NEW.campaign_membership_id;
            IF v_membership_campaign IS DISTINCT FROM NEW.campaign_id THEN
                RAISE EXCEPTION 'Membership % does not belong to campaign %',
                    NEW.campaign_membership_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            -- Only the transaction that created the revelation may add to its snapshot.
            IF v_created IS DISTINCT FROM now() THEN
                RAISE EXCEPTION 'A snapshot is fixed when the revelation is created'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_character_revelation_member_rules() IS
        'Snapshot rows belong to a campaign_current revelation of the same campaign, name a '
        'member of that campaign, and are inserted only by the transaction that created the '
        'revelation (created_at = now()). The only update is setting removed_at once.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_revelation_members_rules
        BEFORE INSERT OR UPDATE ON security.character_revelation_members
        FOR EACH ROW EXECUTE FUNCTION security.enforce_character_revelation_member_rules();
    """)
    op.execute("""
        CREATE FUNCTION security.refuse_character_revelation_member_delete()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION 'Snapshot rows are never deleted (character_revelation_members)'
                USING ERRCODE = 'integrity_constraint_violation';
        END
        $fn$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.refuse_character_revelation_member_delete() IS
        'Refuses DELETE and TRUNCATE of security.character_revelation_members.';
    """)
    op.execute("""
        CREATE TRIGGER tr_character_revelation_members_no_delete
        BEFORE DELETE ON security.character_revelation_members
        FOR EACH ROW EXECUTE FUNCTION security.refuse_character_revelation_member_delete();
    """)
    op.execute("""
        CREATE TRIGGER tr_character_revelation_members_no_truncate
        BEFORE TRUNCATE ON security.character_revelation_members
        FOR EACH STATEMENT EXECUTE FUNCTION security.refuse_character_revelation_member_delete();
    """)

    # Vocabulary only: sort order 160 follows character.reveal (150).
    op.execute(f"""
        INSERT INTO security.capabilities (code, display_name, sort_order, is_active)
        VALUES ('{_CAPABILITY}', 'View public profile', 160, true)
        ON CONFLICT (code) DO NOTHING;
    """)
    op.execute(f"""
        CREATE FUNCTION security.reject_view_public_profile_capability_row()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF TG_TABLE_NAME = 'resource_grants' AND to_jsonb(NEW) ->> 'effect' <> 'allow' THEN
                RETURN NEW;
            END IF;
            IF EXISTS (
                SELECT 1 FROM security.capabilities
                WHERE capability_id = NEW.capability_id AND code = '{_CAPABILITY}'
            ) THEN
                RAISE EXCEPTION
                    '{_CAPABILITY} comes only from a character revelation, not from %',
                    TG_TABLE_NAME
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
    """)
    op.execute(f"""
        COMMENT ON FUNCTION security.reject_view_public_profile_capability_row() IS
        'Refuses a role capability, relationship-type capability or allow resource grant naming '
        '{_CAPABILITY}: its only allow source is a character revelation. A deny grant is '
        'accepted and honoured.';
    """)
    for table, stem in _GUARDED_TABLES:
        op.execute(f"""
            CREATE TRIGGER tr_{stem}_reject_view_public_profile
            BEFORE INSERT OR UPDATE ON security.{table}
            FOR EACH ROW EXECUTE FUNCTION security.reject_view_public_profile_capability_row();
        """)

    for table in ("character_public_profiles", "character_public_profile_releases"):
        op.execute(f"ALTER TABLE campaign.{table} ADD COLUMN public_summary TEXT;")
        op.execute(f"""
            ALTER TABLE campaign.{table} ADD CONSTRAINT ck_{table}_public_summary_length
            CHECK (public_summary IS NULL OR char_length(public_summary) <= {_SUMMARY_MAX});
        """)

    for role in _APP_ROLES:
        op.execute(
            f"REVOKE UPDATE, DELETE, TRUNCATE ON security.character_revelations FROM {role};"
        )
        op.execute(
            f"GRANT UPDATE (ended_at, ended_by_membership_id, end_reason, revocation_reason, "
            f"updated_at) ON security.character_revelations TO {role};"
        )
        op.execute(
            f"REVOKE UPDATE, DELETE, TRUNCATE ON security.character_revelation_members FROM {role};"
        )
        op.execute(
            f"GRANT UPDATE (removed_at, removal_reason) "
            f"ON security.character_revelation_members TO {role};"
        )
    for table in ("character_revelations", "character_revelation_members"):
        op.execute(f"REVOKE ALL ON security.{table} FROM app_read_only;")


def downgrade() -> None:
    """Revert the migration (lossy: every revelation, snapshot and public_summary is dropped)."""
    op.execute(f"""
        DO $guard$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM security.role_capabilities rc
                JOIN security.capabilities c ON c.capability_id = rc.capability_id
                WHERE c.code = '{_CAPABILITY}'
            ) OR EXISTS (
                SELECT 1 FROM security.character_relationship_type_capabilities rc
                JOIN security.capabilities c ON c.capability_id = rc.capability_id
                WHERE c.code = '{_CAPABILITY}'
            ) OR EXISTS (
                SELECT 1 FROM security.resource_grants g
                JOIN security.capabilities c ON c.capability_id = g.capability_id
                WHERE c.code = '{_CAPABILITY}'
            ) THEN
                RAISE EXCEPTION
                    'Refusing to downgrade 145_character_revelations: a role capability, '
                    'relationship-type capability or resource grant names {_CAPABILITY}';
            END IF;
        END
        $guard$;
    """)
    for table in ("character_public_profile_releases", "character_public_profiles"):
        op.execute(f"ALTER TABLE campaign.{table} DROP COLUMN IF EXISTS public_summary;")
    for table, stem in _GUARDED_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS tr_{stem}_reject_view_public_profile ON security.{table};"
        )
    op.execute("DROP FUNCTION IF EXISTS security.reject_view_public_profile_capability_row();")
    op.execute("DROP TABLE IF EXISTS security.character_revelation_members;")
    op.execute("DROP TABLE IF EXISTS security.character_revelations;")
    op.execute("DROP TABLE IF EXISTS security.revelation_audience_kinds;")
    op.execute("DROP FUNCTION IF EXISTS security.refuse_character_revelation_member_delete();")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_character_revelation_member_rules();")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_character_revelation_closed_once();")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_character_revelation_shape_and_scope();")
    op.execute(f"DELETE FROM security.capabilities WHERE code = '{_CAPABILITY}'")
