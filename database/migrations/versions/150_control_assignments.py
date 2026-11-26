"""Add control-assignment columns and uniqueness to membership character relationships

Revision ID: 150_control_assignments
Revises: 149_reservation_fk_deferrable
Create Date: 2026-11-25 12:00:00.000000

Purpose:
    P15-C11-S01-T01 (docs/delivery/p15-c11-s01-assignment-storage-plan.md section 3.1; ADR 0021
    sections 2.2-2.3). A control assignment is a row of `security.membership_character_relationships`
    with `is_control_assignment` true: a `primary_controller` or `co_controller` held for an
    `ongoing` or `dated` period. This revision adds the storage and its invariants only. It changes
    no resolver and no reader, and no writer exists until S02, so only tests create an assignment
    row. Legacy rows (`is_control_assignment` false) keep their semantics exactly.

Forward migration:
    1. Adds `is_control_assignment`, `campaign_id` (backfilled from the row's membership, then NOT
       NULL, immutable), `is_primary` (derived from the type), `assignment_period_kind`,
       `revoked_by_membership_id` and `revocation_reason`.
    2. Replaces `security.enforce_membership_character_relationship_scope()` (every existing check
       kept) so it also fills `campaign_id` and `is_primary`, refuses a foreign `campaign_id`, a
       non-controller assignment type and a `revoked_by_membership_id` of another campaign.
    3. Adds the CHECK constraints (all of them leave a legacy row untouched).
    4. Re-creates `ux_membership_character_relationships_active_type` under the same name with the
       extra predicate `NOT is_control_assignment` (R01 UniqueWait declarations name it), and adds
       `ux_..._live_primary` (one live primary per campaign and character) and
       `ux_..._live_assignment` (one live assignment per membership and character).

Rollback:
    Refuses, changing nothing, while any `is_control_assignment` row exists: it never deletes
    assignments silently and never lets one become a legacy row that would confer more access.
    Otherwise it restores the previous index, trigger function, columns and comments exactly.

Data implications:
    No existing column changes. Every existing row gains its membership's campaign, a false
    `is_control_assignment`, a NULL kind and no revoker.

Locking considerations:
    ACCESS EXCLUSIVE on `security.membership_character_relationships` for the duration of the
    transaction: ADD COLUMN with a constant default is metadata-only, the backfill UPDATE and the
    NOT NULL scan touch every row once, and the index rebuild reads the table once. The table is
    small (one row per human-character relationship).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "150_control_assignments"
down_revision = "149_reservation_fk_deferrable"
branch_labels = None
depends_on = None

_TABLE = "security.membership_character_relationships"
_FUNCTION = "security.enforce_membership_character_relationship_scope()"
_INDEX_ACTIVE_TYPE = "ux_membership_character_relationships_active_type"

# The function and its comment exactly as revision 080 created them (the downgrade restores them
# byte for byte, so the indentation is part of the value).
_LEGACY_FUNCTION = """
        CREATE OR REPLACE FUNCTION security.enforce_membership_character_relationship_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_id       UUID;
            v_campaign_world    UUID;
            v_character_world   UUID;
            v_timeline_world    UUID;
            v_from_world        UUID;
            v_from_sort_key     BIGINT;
            v_to_world          UUID;
            v_to_sort_key       BIGINT;
            v_actor_campaign    UUID;
        BEGIN
            SELECT cm.campaign_id, t.world_id INTO v_campaign_id, v_campaign_world
            FROM security.campaign_memberships cm
            JOIN campaign.campaigns c ON c.campaign_id = cm.campaign_id
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE cm.campaign_membership_id = NEW.campaign_membership_id;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            IF v_character_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Membership % belongs to world %, but character % belongs to world %',
                    NEW.campaign_membership_id, v_campaign_world, NEW.character_id, v_character_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.timeline_id IS NOT NULL THEN
                SELECT world_id INTO v_timeline_world
                FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

                IF v_timeline_world IS DISTINCT FROM v_campaign_world THEN
                    RAISE EXCEPTION
                        'Membership % belongs to world %, but timeline % belongs to world %',
                        NEW.campaign_membership_id, v_campaign_world, NEW.timeline_id, v_timeline_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.granted_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.granted_by_membership_id;

                IF v_actor_campaign IS DISTINCT FROM v_campaign_id THEN
                    RAISE EXCEPTION
                        'Relationship for membership % (campaign %) has granted_by_membership_id % '
                        'belonging to campaign %',
                        NEW.campaign_membership_id, v_campaign_id,
                        NEW.granted_by_membership_id, v_actor_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.effective_from_world_time_id IS NULL THEN
                NEW.effective_period := NULL;
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_from_world, v_from_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_from_world_time_id;

            IF v_from_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Start world time % belongs to world %, but relationship belongs to world %',
                    NEW.effective_from_world_time_id, v_from_world, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.effective_to_world_time_id IS NULL THEN
                NEW.effective_period := int8range(v_from_sort_key, NULL, '[)');
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_to_world, v_to_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_to_world_time_id;

            IF v_to_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'End world time % belongs to world %, but relationship belongs to world %',
                    NEW.effective_to_world_time_id, v_to_world, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_to_sort_key <= v_from_sort_key THEN
                RAISE EXCEPTION
                    'Relationship end (sort_key %) must be later than its start (sort_key %)',
                    v_to_sort_key, v_from_sort_key
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            NEW.effective_period := int8range(v_from_sort_key, v_to_sort_key, '[)');
            RETURN NEW;
        END;
        $$;
"""

_LEGACY_FUNCTION_COMMENT = """
        COMMENT ON FUNCTION security.enforce_membership_character_relationship_scope() IS
        'Same-world guard for security.membership_character_relationships, same-campaign '
        'guard for granted_by_membership_id, plus derivation of effective_period from its '
        'world-time endpoints when supplied (conventions §9.5, ADR 0010 interval '
        'contract). Unlike campaign.party_memberships, both endpoints are optional here '
        '— the guard clears effective_period to NULL rather than raising when no start '
        'endpoint is supplied.';
"""

_NEW_FUNCTION = """
        CREATE OR REPLACE FUNCTION security.enforce_membership_character_relationship_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_id       UUID;
            v_campaign_world    UUID;
            v_character_world   UUID;
            v_timeline_world    UUID;
            v_from_world        UUID;
            v_from_sort_key     BIGINT;
            v_to_world          UUID;
            v_to_sort_key       BIGINT;
            v_actor_campaign    UUID;
            v_type_code         TEXT;
            v_revoker_campaign  UUID;
        BEGIN
            SELECT cm.campaign_id, t.world_id INTO v_campaign_id, v_campaign_world
            FROM security.campaign_memberships cm
            JOIN campaign.campaigns c ON c.campaign_id = cm.campaign_id
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE cm.campaign_membership_id = NEW.campaign_membership_id;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            IF v_character_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Membership % belongs to world %, but character % belongs to world %',
                    NEW.campaign_membership_id, v_campaign_world, NEW.character_id, v_character_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.timeline_id IS NOT NULL THEN
                SELECT world_id INTO v_timeline_world
                FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

                IF v_timeline_world IS DISTINCT FROM v_campaign_world THEN
                    RAISE EXCEPTION
                        'Membership % belongs to world %, but timeline % belongs to world %',
                        NEW.campaign_membership_id, v_campaign_world, NEW.timeline_id, v_timeline_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.granted_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.granted_by_membership_id;

                IF v_actor_campaign IS DISTINCT FROM v_campaign_id THEN
                    RAISE EXCEPTION
                        'Relationship for membership % (campaign %) has granted_by_membership_id % '
                        'belonging to campaign %',
                        NEW.campaign_membership_id, v_campaign_id,
                        NEW.granted_by_membership_id, v_actor_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            -- Control-assignment storage (revision 150): the denormalized campaign, the derived
            -- primary flag, the controller-only type rule and the revoker's campaign. A row whose
            -- membership no longer exists (only possible when foreign keys were bypassed) is
            -- tolerated exactly as the earlier checks tolerate it.
            IF NEW.campaign_id IS NULL THEN
                NEW.campaign_id := v_campaign_id;
            ELSIF v_campaign_id IS NOT NULL AND NEW.campaign_id <> v_campaign_id THEN
                RAISE EXCEPTION
                    'Relationship for membership % (campaign %) names campaign %',
                    NEW.campaign_membership_id, v_campaign_id, NEW.campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            SELECT code INTO v_type_code
            FROM security.character_relationship_types
            WHERE character_relationship_type_id = NEW.character_relationship_type_id;

            NEW.is_primary := (v_type_code = 'primary_controller');

            IF NEW.is_control_assignment
               AND v_type_code NOT IN ('primary_controller', 'co_controller') THEN
                RAISE EXCEPTION
                    'A control assignment must be a primary_controller or co_controller, not %',
                    v_type_code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.revoked_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_revoker_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.revoked_by_membership_id;

                IF v_revoker_campaign IS DISTINCT FROM v_campaign_id THEN
                    RAISE EXCEPTION
                        'Relationship for membership % (campaign %) has revoked_by_membership_id % '
                        'belonging to campaign %',
                        NEW.campaign_membership_id, v_campaign_id,
                        NEW.revoked_by_membership_id, v_revoker_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.effective_from_world_time_id IS NULL THEN
                NEW.effective_period := NULL;
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_from_world, v_from_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_from_world_time_id;

            IF v_from_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Start world time % belongs to world %, but relationship belongs to world %',
                    NEW.effective_from_world_time_id, v_from_world, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.effective_to_world_time_id IS NULL THEN
                NEW.effective_period := int8range(v_from_sort_key, NULL, '[)');
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_to_world, v_to_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_to_world_time_id;

            IF v_to_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'End world time % belongs to world %, but relationship belongs to world %',
                    NEW.effective_to_world_time_id, v_to_world, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_to_sort_key <= v_from_sort_key THEN
                RAISE EXCEPTION
                    'Relationship end (sort_key %) must be later than its start (sort_key %)',
                    v_to_sort_key, v_from_sort_key
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            NEW.effective_period := int8range(v_from_sort_key, v_to_sort_key, '[)');
            RETURN NEW;
        END;
        $$;
"""

_NEW_FUNCTION_COMMENT = """
        COMMENT ON FUNCTION security.enforce_membership_character_relationship_scope() IS
        'Same-world guard for security.membership_character_relationships, same-campaign '
        'guard for granted_by_membership_id and revoked_by_membership_id, plus derivation of '
        'effective_period from its world-time endpoints when supplied (conventions §9.5, ADR '
        '0010 interval contract). Unlike campaign.party_memberships, both endpoints are '
        'optional here — the guard clears effective_period to NULL rather than raising when no '
        'start endpoint is supplied. Since revision 150 it also fills campaign_id from the '
        'membership (refusing a different value), derives is_primary from the type, and '
        'refuses a control assignment whose type is not primary_controller or '
        'co_controller.';
"""

_NEW_COLUMN_COMMENTS = {
    "is_control_assignment": (
        "True for a control assignment (ADR 0021 section 2.2): a primary_controller or "
        "co_controller held for an ongoing or dated period, resolved by the dedicated, "
        "clock-aware rule and never by the legacy relationship rule. False for every legacy "
        "row. Immutable after insert."
    ),
    "campaign_id": (
        "The campaign of campaign_membership_id, denormalized so uniqueness and resolution can "
        "be scoped to one campaign without a join. Filled by the scope trigger (a different "
        "supplied value is refused) and immutable."
    ),
    "is_primary": (
        "Derived, never client-authoritative: true when the relationship type is "
        "primary_controller. Maintained by the scope trigger on every insert and update; "
        "the live-primary unique index uses it for assignment rows."
    ),
    "assignment_period_kind": (
        "ongoing (no world-time endpoints) or dated (a start world time and an optional end), "
        "present exactly when is_control_assignment is true and NULL otherwise. Immutable "
        "after insert."
    ),
    "revoked_by_membership_id": (
        "The membership that revoked the assignment, in the same campaign. NULL when the row "
        "is unrevoked, or revoked without an actor (for example by membership end)."
    ),
    "revocation_reason": (
        "The recorded reason (1-1000 characters) for an explicit revocation; NULL when the row "
        "is unrevoked or was revoked without one."
    ),
}


def upgrade() -> None:
    """Apply the migration."""
    op.execute(
        f"ALTER TABLE {_TABLE} "
        "ADD COLUMN is_control_assignment BOOLEAN NOT NULL DEFAULT false, "
        "ADD COLUMN campaign_id UUID, "
        "ADD COLUMN is_primary BOOLEAN NOT NULL DEFAULT false, "
        "ADD COLUMN assignment_period_kind TEXT, "
        "ADD COLUMN revoked_by_membership_id UUID, "
        "ADD COLUMN revocation_reason TEXT;"
    )
    # Backfill before the new trigger and constraints exist: the campaign comes from the membership,
    # and the derived primary flag from the type, for every row (legacy rows included).
    op.execute(f"""
        UPDATE {_TABLE} r
        SET campaign_id = cm.campaign_id,
            is_primary = COALESCE(
                (SELECT t.code = 'primary_controller'
                 FROM security.character_relationship_types t
                 WHERE t.character_relationship_type_id = r.character_relationship_type_id),
                false)
        FROM security.campaign_memberships cm
        WHERE cm.campaign_membership_id = r.campaign_membership_id;
    """)
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN campaign_id SET NOT NULL;")
    op.execute(
        f"ALTER TABLE {_TABLE} "
        "ADD CONSTRAINT membership_character_relationships_campaign_id_fkey "
        "FOREIGN KEY (campaign_id) REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE, "
        "ADD CONSTRAINT membership_character_relationships_revoked_by_fkey "
        "FOREIGN KEY (revoked_by_membership_id) "
        "REFERENCES security.campaign_memberships(campaign_membership_id) ON DELETE SET NULL;"
    )

    op.execute(f"""
        ALTER TABLE {_TABLE}
        ADD CONSTRAINT ck_membership_character_relationships_assignment_kind_values
            CHECK (assignment_period_kind IN ('ongoing', 'dated')),
        ADD CONSTRAINT ck_membership_character_relationships_assignment_kind_present
            CHECK (is_control_assignment = (assignment_period_kind IS NOT NULL)),
        ADD CONSTRAINT ck_membership_character_relationships_ongoing_has_no_period
            CHECK (
                assignment_period_kind IS DISTINCT FROM 'ongoing'
                OR (effective_from_world_time_id IS NULL AND effective_to_world_time_id IS NULL)
            ),
        ADD CONSTRAINT ck_membership_character_relationships_dated_has_start
            CHECK (
                assignment_period_kind IS DISTINCT FROM 'dated'
                OR effective_from_world_time_id IS NOT NULL
            ),
        ADD CONSTRAINT ck_membership_character_relationships_assignment_unscoped
            CHECK (NOT is_control_assignment OR (expires_at IS NULL AND timeline_id IS NULL)),
        ADD CONSTRAINT ck_membership_character_relationships_revocation_only_revoked
            CHECK (
                (revoked_by_membership_id IS NULL AND revocation_reason IS NULL)
                OR revoked_at IS NOT NULL
            ),
        ADD CONSTRAINT ck_membership_character_relationships_revocation_reason_length
            CHECK (
                revocation_reason IS NULL OR char_length(revocation_reason) BETWEEN 1 AND 1000
            );
    """)

    op.execute(_NEW_FUNCTION)
    op.execute(_NEW_FUNCTION_COMMENT)
    op.execute(f"""
        CREATE TRIGGER tr_membership_character_relationships_enforce_immutable
        BEFORE UPDATE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns(
            'campaign_id', 'is_control_assignment', 'assignment_period_kind'
        );
    """)

    op.execute(f"DROP INDEX security.{_INDEX_ACTIVE_TYPE};")
    op.execute(f"""
        CREATE UNIQUE INDEX {_INDEX_ACTIVE_TYPE}
        ON {_TABLE} (campaign_membership_id, character_id, character_relationship_type_id)
        WHERE revoked_at IS NULL AND NOT is_control_assignment;
    """)
    op.execute(f"""
        CREATE UNIQUE INDEX ux_membership_character_relationships_live_primary
        ON {_TABLE} (campaign_id, character_id)
        WHERE is_control_assignment AND is_primary AND revoked_at IS NULL;
    """)
    op.execute(f"""
        CREATE UNIQUE INDEX ux_membership_character_relationships_live_assignment
        ON {_TABLE} (campaign_membership_id, character_id)
        WHERE is_control_assignment AND revoked_at IS NULL;
    """)
    op.execute(
        f"CREATE INDEX ix_membership_character_relationships_campaign_id ON {_TABLE} (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_membership_character_relationships_revoked_by "
        f"ON {_TABLE} (revoked_by_membership_id) WHERE revoked_by_membership_id IS NOT NULL;"
    )

    for column, comment in _NEW_COLUMN_COMMENTS.items():
        op.execute(
            f"COMMENT ON COLUMN {_TABLE}.{column} IS '{comment.replace(chr(39), chr(39) * 2)}';"
        )
    op.execute(f"""
        COMMENT ON INDEX security.{_INDEX_ACTIVE_TYPE} IS
        'At most one live legacy relationship per membership, character and type. Control '
        'assignment rows are excluded (they have their own indexes); the name is kept because '
        'R01 UniqueWait declarations reference it.';
    """)
    op.execute("""
        COMMENT ON INDEX security.ux_membership_character_relationships_live_primary IS
        'At most one live primary control assignment per campaign and character, whichever '
        'membership holds it (ADR 0021 section 2.3).';
    """)
    op.execute("""
        COMMENT ON INDEX security.ux_membership_character_relationships_live_assignment IS
        'At most one live control assignment (primary or co-controller) per membership and '
        'character.';
    """)


def downgrade() -> None:
    """Revert the migration (refuses while any control assignment row exists)."""
    op.execute(f"""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM {_TABLE} WHERE is_control_assignment) THEN
                RAISE EXCEPTION
                    'Cannot downgrade revision 150: control assignment rows exist in {_TABLE}. '
                    'Revoke and remove them deliberately first; a downgrade never deletes them or '
                    'turns them into legacy relationships.'
                    USING ERRCODE = 'feature_not_supported';
            END IF;
        END
        $guard$;
    """)
    op.execute(
        "DROP TRIGGER tr_membership_character_relationships_enforce_immutable ON " + _TABLE + ";"
    )
    op.execute("DROP INDEX security.ix_membership_character_relationships_revoked_by;")
    op.execute("DROP INDEX security.ix_membership_character_relationships_campaign_id;")
    op.execute("DROP INDEX security.ux_membership_character_relationships_live_assignment;")
    op.execute("DROP INDEX security.ux_membership_character_relationships_live_primary;")
    op.execute(f"DROP INDEX security.{_INDEX_ACTIVE_TYPE};")
    op.execute(f"""
        CREATE UNIQUE INDEX {_INDEX_ACTIVE_TYPE}
        ON {_TABLE} (
            campaign_membership_id, character_id, character_relationship_type_id
        )
        WHERE revoked_at IS NULL;
    """)
    op.execute(_LEGACY_FUNCTION)
    op.execute(_LEGACY_FUNCTION_COMMENT)
    op.execute(f"""
        ALTER TABLE {_TABLE}
        DROP CONSTRAINT ck_membership_character_relationships_revocation_reason_length,
        DROP CONSTRAINT ck_membership_character_relationships_revocation_only_revoked,
        DROP CONSTRAINT ck_membership_character_relationships_assignment_unscoped,
        DROP CONSTRAINT ck_membership_character_relationships_dated_has_start,
        DROP CONSTRAINT ck_membership_character_relationships_ongoing_has_no_period,
        DROP CONSTRAINT ck_membership_character_relationships_assignment_kind_present,
        DROP CONSTRAINT ck_membership_character_relationships_assignment_kind_values,
        DROP CONSTRAINT membership_character_relationships_revoked_by_fkey,
        DROP CONSTRAINT membership_character_relationships_campaign_id_fkey,
        DROP COLUMN revocation_reason,
        DROP COLUMN revoked_by_membership_id,
        DROP COLUMN assignment_period_kind,
        DROP COLUMN is_primary,
        DROP COLUMN campaign_id,
        DROP COLUMN is_control_assignment;
    """)
